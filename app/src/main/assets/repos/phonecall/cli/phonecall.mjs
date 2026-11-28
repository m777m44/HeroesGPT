#!/usr/bin/env node
// phonecall: place phone calls with a Grok voice agent and answer its questions while it talks.
import { readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { parseArgs } from "node:util";

const HELP = `phonecall: have a voice agent make a phone call for you

  phonecall call <+number> --brief "<what to get done>"   start a call, print its job id
  phonecall watch <job>                                  wait for the next question or the end of the call
  phonecall reply <job> <question-id> "<answer>"         answer a question while the call is live
  phonecall report <job>                                 summary, questions and transcript (JSON)
  phonecall transcript <job>                             transcript as plain text
  phonecall list                                         recent calls
  phonecall hangup <job>                                 end a call now

call options
  --brief <text> | --brief-file <path>   goal, facts it may share, limits, what counts as done
  --for <name>             who the call is for (default: the server's PRINCIPAL_NAME)
  --as <name>              name the caller gives (default: Sam)
  --voice <id>             eve, ara, rex, sal or leo (default: eve)
  --max-minutes <n>        hard limit on call length (default 10)
  --answer-timeout <sec>   how long the caller waits for a reply to a question (default 60)
  --simulate <persona>     test call: a second AI plays the person you're calling; nobody is dialed
  --watch                  start watching right away

watch prints live progress to stderr and exits with one JSON line on stdout:
  {"type":"input_request","job_id":…,"question_id":"q1","question":"…"}  reply, then watch again
  {"type":"done","job_id":…,"report":{…}}                                  the call is over

Config: PHONECALL_URL and PHONECALL_TOKEN, or ~/.config/phonecall/config.json {"url","token"}.`;

function config() {
  let file = {};
  try {
    file = JSON.parse(readFileSync(join(homedir(), ".config/phonecall/config.json"), "utf8"));
  } catch {}
  const url = process.env.PHONECALL_URL ?? file.url;
  const token = process.env.PHONECALL_TOKEN ?? file.token;
  if (!url || !token) fail("phonecall is not configured: set PHONECALL_URL and PHONECALL_TOKEN or write ~/.config/phonecall/config.json");
  return { url: url.replace(/\/$/, ""), token };
}

function fail(message) {
  console.error(`phonecall: ${message}`);
  process.exit(1);
}

async function api(method, path, body) {
  const { url, token } = config();
  const res = await fetch(url + path, {
    method,
    headers: { Authorization: `Bearer ${token}`, ...(body ? { "Content-Type": "application/json" } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({ error: `HTTP ${res.status}` }));
  if (!res.ok) fail(data.error ?? `HTTP ${res.status}`);
  return data;
}

const out = (obj) => console.log(JSON.stringify(obj));
const time = (ms) => new Date(ms).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });

function describe(e) {
  const d = e.data;
  switch (e.type) {
    case "status":
      return `· ${d.status}${d.reason ? ` (${d.reason})` : ""}${d.to ? ` ${d.to}` : ""}`;
    case "said":
      return `${d.who === "agent" ? "agent" : " them"}: ${d.text}`;
    case "input_request":
      return `? ${d.id}: ${d.question}`;
    case "answer":
      return `↳ ${d.id}: ${d.answer}${d.late ? " (late)" : ""}`;
    case "input_timeout":
      return `! ${d.id} timed out without an answer`;
    case "dtmf":
      return `# pressed ${JSON.stringify(d)}`;
    case "end_call":
      return `· agent hung up: ${d.outcome}${d.notes ? ` (${d.notes})` : ""}`;
    case "error":
      return `! ${d.message}`;
    default:
      return null;
  }
}

async function watch(jobId, verbose) {
  let after = 0;
  for (;;) {
    const r = await api("GET", `/jobs/${jobId}/watch?after=${after}&timeout=25`);
    for (const e of r.events) {
      const line = e.type === "debug" ? (verbose ? `  debug ${JSON.stringify(e.data)}` : null) : describe(e);
      if (line) console.error(`${time(e.at)} ${line}`);
    }
    after = r.cursor;
    if (r.pending.length) {
      const q = r.pending[0];
      return out({ type: "input_request", job_id: jobId, question_id: q.id, question: q.question, more_pending: r.pending.length - 1 });
    }
    if (r.status === "done") return out({ type: "done", job_id: jobId, report: r.report });
  }
}

const [cmd, ...rest] = process.argv.slice(2);
const { values: opt, positionals: pos } = parseArgs({
  args: rest,
  allowPositionals: true,
  options: {
    brief: { type: "string" },
    "brief-file": { type: "string" },
    for: { type: "string" },
    as: { type: "string" },
    voice: { type: "string" },
    "max-minutes": { type: "string" },
    "answer-timeout": { type: "string" },
    simulate: { type: "string" },
    watch: { type: "boolean" },
    verbose: { type: "boolean", short: "v" },
    limit: { type: "string" },
  },
});

switch (cmd) {
  case "call": {
    const brief = opt["brief-file"] ? readFileSync(opt["brief-file"], "utf8") : opt.brief;
    if (!brief) fail("--brief or --brief-file is required");
    if (!pos[0] && !opt.simulate) fail("give the number to call, like +14155550100");
    const r = await api("POST", "/jobs", {
      to: pos[0],
      brief,
      principal: opt.for,
      agent_name: opt.as,
      voice: opt.voice,
      max_minutes: opt["max-minutes"] ? Number(opt["max-minutes"]) : undefined,
      answer_timeout: opt["answer-timeout"] ? Number(opt["answer-timeout"]) : undefined,
      simulate: opt.simulate,
    });
    if (opt.watch) {
      console.error(`job ${r.job_id}`);
      await watch(r.job_id, opt.verbose);
    } else out({ job_id: r.job_id, next: `phonecall watch ${r.job_id}` });
    break;
  }
  case "watch":
    if (!pos[0]) fail("usage: phonecall watch <job>");
    await watch(pos[0], opt.verbose);
    break;
  case "reply":
    if (pos.length < 3) fail('usage: phonecall reply <job> <question-id> "<answer>"');
    out(await api("POST", `/jobs/${pos[0]}/reply`, { question_id: pos[1], answer: pos.slice(2).join(" ") }));
    break;
  case "report":
    if (!pos[0]) fail("usage: phonecall report <job>");
    console.log(JSON.stringify(await api("GET", `/jobs/${pos[0]}`), null, 2));
    break;
  case "transcript": {
    if (!pos[0]) fail("usage: phonecall transcript <job>");
    const r = await api("GET", `/jobs/${pos[0]}`);
    for (const t of r.transcript) console.log(`[${time(t.at)}] ${t.who === "agent" ? r.job.agentName : "Them"}: ${t.text}`);
    break;
  }
  case "list":
    for (const j of await api("GET", `/jobs?limit=${opt.limit ?? 20}`)) console.log(`${j.id}  ${new Date(j.created_at).toLocaleString()}  ${j.status.padEnd(9)} ${j.to}  ${j.brief.split("\n")[0].slice(0, 60)}`);
    break;
  case "hangup":
    if (!pos[0]) fail("usage: phonecall hangup <job>");
    out(await api("POST", `/jobs/${pos[0]}/hangup`));
    break;
  default:
    console.log(HELP);
    if (cmd && cmd !== "help" && cmd !== "--help" && cmd !== "-h") process.exit(1);
}
