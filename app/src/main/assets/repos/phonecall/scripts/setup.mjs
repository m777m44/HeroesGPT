#!/usr/bin/env node
// One-time setup: registers your Twilio number with xAI's SIP service, stores the Worker's
// secrets with wrangler, and writes the CLI config to ~/.config/phonecall.
// Values can come from environment variables of the same name; anything missing is asked for.
import { spawnSync } from "node:child_process";
import { randomBytes, randomInt } from "node:crypto";
import { chmodSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { homedir, tmpdir } from "node:os";
import { join } from "node:path";
import { createInterface } from "node:readline/promises";

const simulate = !process.argv.includes("--no-sim");
const rl = createInterface({ input: process.stdin, output: process.stderr });

async function value(name, question, valid = () => true) {
  let v = process.env[name]?.trim();
  while (!v || !valid(v)) {
    if (v) console.error("  That doesn't look right, try again.");
    v = (await rl.question(`${question}: `)).trim();
  }
  return v;
}

function fail(message) {
  console.error(`\nsetup: ${message}`);
  process.exit(1);
}

const url = (await value("PHONECALL_URL", "Worker URL from `npx wrangler deploy` (https://phonecall.<you>.workers.dev)", (v) => v.startsWith("https://"))).replace(/\/$/, "");
const xaiKey = await value("XAI_API_KEY", "xAI API key");
const twilioSid = await value("TWILIO_ACCOUNT_SID", "Twilio Account SID (starts with AC)", (v) => v.startsWith("AC"));
const twilioToken = await value("TWILIO_AUTH_TOKEN", "Twilio Auth Token");
const number = await value("TWILIO_PHONE_NUMBER", "Twilio number to call from, like +14155550100", (v) => /^\+[1-9]\d{7,14}$/.test(v));
const principal = await value("PRINCIPAL_NAME", 'Your name, as the caller says it ("I\'m calling for ...")');
rl.close();

console.error("\nChecking Twilio...");
const tw = await fetch(`https://api.twilio.com/2010-04-01/Accounts/${twilioSid}/IncomingPhoneNumbers.json?PhoneNumber=${encodeURIComponent(number)}`, {
  headers: { Authorization: `Basic ${Buffer.from(`${twilioSid}:${twilioToken}`).toString("base64")}` },
});
if (!tw.ok) fail(`Twilio rejected the credentials (HTTP ${tw.status}).`);
if (!(await tw.json()).incoming_phone_numbers?.length) fail(`${number} isn't a phone number on this Twilio account.`);

const sipUsername = `phonecall-${randomBytes(4).toString("hex")}`;
const sipPassword = randomBytes(24).toString("hex");
const xai = (path, init = {}) => fetch(`https://api.x.ai${path}`, { ...init, headers: { Authorization: `Bearer ${xaiKey}`, "Content-Type": "application/json", ...init.headers } });

// Registers a number with xAI's SIP service and returns its webhook signing secret.
// A registration left over from an earlier run is replaced, since its secret can't be read back.
async function register(phone, name) {
  const body = JSON.stringify({
    origin: "byo_trunk",
    name,
    phone_number: phone,
    webhook: { name: "phonecall", url: `${url}/xai/webhook` },
    sip_auth: { auth_username: sipUsername, auth_password: sipPassword },
  });
  for (let attempt = 0; attempt < 2; attempt++) {
    const res = await xai("/v2/phone-numbers", { method: "POST", body });
    const data = await res.json().catch(() => ({}));
    if (res.ok) return data.webhook.dispatch_signing_secret;
    const list = await (await xai("/v2/phone-numbers")).json().catch(() => ({}));
    const existing = list.phone_numbers?.find((n) => n.phone_number === phone);
    if (attempt > 0 || !existing) fail(`xAI didn't register ${phone} (HTTP ${res.status}): ${JSON.stringify(data).slice(0, 300)}`);
    console.error(`  Replacing the earlier xAI registration for ${phone}`);
    await xai(`/v2/phone-numbers/${existing.phone_number_id}`, { method: "DELETE" });
  }
}

// NANP reserves 555-0100 to 555-0199 for fiction, so the simulator number can never be a real line.
function fictionalNumber() {
  let areaCode;
  do areaCode = `${randomInt(2, 10)}${randomInt(0, 10)}${randomInt(0, 10)}`;
  while (areaCode.endsWith("11"));
  return `+1${areaCode}55501${String(randomInt(0, 100)).padStart(2, "0")}`;
}

console.error(`Registering ${number} with xAI...`);
const webhookSecrets = [await register(number, "phonecall")];
let simNumber;
if (simulate) {
  simNumber = fictionalNumber();
  console.error(`Registering ${simNumber} for simulated calls...`);
  webhookSecrets.push(await register(simNumber, "phonecall simulator"));
}

// Reuse PHONECALL_TOKEN when given, so connected CLIs and MCP clients keep working after a re-run.
const phonecallToken = process.env.PHONECALL_TOKEN?.trim() || randomBytes(32).toString("hex");
const secrets = {
  XAI_API_KEY: xaiKey,
  XAI_WEBHOOK_SECRET: webhookSecrets.join(","),
  SIP_USERNAME: sipUsername,
  SIP_PASSWORD: sipPassword,
  TWILIO_ACCOUNT_SID: twilioSid,
  TWILIO_AUTH_TOKEN: twilioToken,
  TWILIO_PHONE_NUMBER: number,
  PRINCIPAL_NAME: principal,
  PHONECALL_TOKEN: phonecallToken,
  ...(simNumber ? { SIM_NUMBER: simNumber } : {}),
};

console.error("Storing Worker secrets...");
const dir = mkdtempSync(join(tmpdir(), "phonecall-"));
const file = join(dir, "secrets.json");
writeFileSync(file, JSON.stringify(secrets), { mode: 0o600 });
const [cmd, ...args] = (process.env.WRANGLER ?? "npx wrangler").split(" ");
const result = spawnSync(cmd, [...args, "secret", "bulk", file], { stdio: ["ignore", "inherit", "inherit"] });
rmSync(dir, { recursive: true, force: true });
if (result.status !== 0) fail("wrangler couldn't store the secrets. Run `npx wrangler login`, then `npm run setup` again.");

const configDir = join(homedir(), ".config", "phonecall");
mkdirSync(configDir, { recursive: true, mode: 0o700 });
for (const [name, content] of [
  ["config.json", `${JSON.stringify({ url, token: phonecallToken }, null, 2)}\n`],
  ["token", phonecallToken],
]) {
  writeFileSync(join(configDir, name), content, { mode: 0o600 });
  chmodSync(join(configDir, name), 0o600);
}

console.log(`
Done. phonecall is live at ${url}

CLI config: ~/.config/phonecall/config.json
MCP token:  ~/.config/phonecall/token

Try a simulated call (nobody is dialed):
  phonecall call --simulate "You run the counter at a busy pizza place." \\
    --brief "Order a large pepperoni for pickup at 7pm." --watch
`);
