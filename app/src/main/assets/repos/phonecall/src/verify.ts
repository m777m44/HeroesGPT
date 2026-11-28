const enc = new TextEncoder();

function b64(bytes: ArrayBuffer): string {
  let s = "";
  for (const b of new Uint8Array(bytes)) s += String.fromCharCode(b);
  return btoa(s);
}

function fromB64(s: string): Uint8Array {
  return Uint8Array.from(atob(s), (c) => c.charCodeAt(0));
}

export function safeEqual(a: string, b: string): boolean {
  const x = enc.encode(a);
  const y = enc.encode(b);
  if (x.length !== y.length) return false;
  let diff = 0;
  for (let i = 0; i < x.length; i++) diff |= x[i] ^ y[i];
  return diff === 0;
}

async function hmac(hash: "SHA-1" | "SHA-256", key: Uint8Array, data: string): Promise<string> {
  const k = await crypto.subtle.importKey("raw", key, { name: "HMAC", hash }, false, ["sign"]);
  return b64(await crypto.subtle.sign("HMAC", k, enc.encode(data)));
}

// https://www.twilio.com/docs/usage/security#validating-requests
export async function verifyTwilio(authToken: string, url: string, params: URLSearchParams, signature: string | null): Promise<boolean> {
  if (!signature) return false;
  const keys = [...new Set(params.keys())].sort();
  let data = url;
  for (const k of keys) for (const v of params.getAll(k)) data += k + v;
  return safeEqual(await hmac("SHA-1", enc.encode(authToken), data), signature);
}

// Standard Webhooks signatures (webhook-id, webhook-timestamp, webhook-signature).
// `secrets` is comma-separated: xAI creates one webhook, with its own secret, per registered number.
export async function verifyStandardWebhook(secrets: string, headers: Headers, body: string): Promise<boolean> {
  const id = headers.get("webhook-id");
  const ts = headers.get("webhook-timestamp");
  const sigs = headers.get("webhook-signature");
  if (!id || !ts || !sigs) return false;
  if (Math.abs(Date.now() / 1000 - Number(ts)) > 300) return false;
  for (const secret of secrets.split(",")) {
    const key = secret.startsWith("whsec_") ? fromB64(secret.slice(6)) : enc.encode(secret);
    const expected = await hmac("SHA-256", key, `${id}.${ts}.${body}`);
    if (sigs.split(" ").some((s) => safeEqual(s.split(",")[1] ?? "", expected))) return true;
  }
  return false;
}
