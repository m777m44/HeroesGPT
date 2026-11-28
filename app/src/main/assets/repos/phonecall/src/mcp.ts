import type { CallJob } from "./call-job";
import { job, registry, startJob, waitForTurn } from "./jobs";
import type { Env } from "./types";

// Minimal stateless MCP server (Streamable HTTP, JSON responses only).
const INSTRUCTIONS = `Make phone calls with a voice agent that sounds like a person.
1. phonecall_start with the number and a brief: the goal, facts it may share, limits, and what counts as done.
2. phonecall_watch until it returns. "input_request": the agent is on the line waiting for your answer, so reply within about a minute with phonecall_reply, then watch again. "running": watch again. "done": the report is included.
Use simulate (a persona) for a test call where a second AI plays the other side and nobody is dialed.`;

const TOOLS = [
  {
    name: "phonecall_start",
    description: "Start a phone call. Returns a job_id right away; then call phonecall_watch.",
    inputSchema: {
      type: "object",
      properties: {
        to: { type: "string", description: "Number to call in E.164 form, like +14155550100. Omit when simulating." },
        brief: { type: "string", description: "What to get done: goal, facts the caller may share, limits (what not to agree to), what counts as done." },
        for: { type: "string", description: "Who the call is on behalf of (defaults to the server's PRINCIPAL_NAME)." },
        as: { type: "string", description: "Name the caller gives (default Sam)." },
        voice: { type: "string", enum: ["eve", "ara", "rex", "sal", "leo"] },
        max_minutes: { type: "number", description: "Hard limit on call length, 1-30 (default 10)." },
        answer_timeout: { type: "number", description: "Seconds the caller waits for your reply to a question (default 60)." },
        simulate: { type: "string", description: "Test only: persona for a second AI that plays the person being called. Nobody is dialed." },
      },
      required: ["brief"],
    },
  },
  {
    name: "phonecall_watch",
    description: "Wait for the call's next question or its end (up to ~45s). Returns type input_request (answer with phonecall_reply), running (watch again) or done (with the report). Pass the returned cursor back to only see new progress.",
    inputSchema: {
      type: "object",
      properties: { job_id: { type: "string" }, cursor: { type: "number" }, timeout_seconds: { type: "number", description: "Max wait, up to 50 (default 45)." } },
      required: ["job_id"],
    },
  },
  {
    name: "phonecall_reply",
    description: "Answer the agent's question while the call is live. The agent relays it to the other person right away.",
    inputSchema: {
      type: "object",
      properties: { job_id: { type: "string" }, question_id: { type: "string" }, answer: { type: "string" } },
      required: ["job_id", "question_id", "answer"],
    },
  },
  {
    name: "phonecall_report",
    description: "Get a call's summary, questions and full transcript.",
    inputSchema: { type: "object", properties: { job_id: { type: "string" } }, required: ["job_id"] },
  },
  {
    name: "phonecall_list",
    description: "List recent calls.",
    inputSchema: { type: "object", properties: { limit: { type: "number" } } },
  },
  {
    name: "phonecall_hangup",
    description: "End a call now.",
    inputSchema: { type: "object", properties: { job_id: { type: "string" } }, required: ["job_id"] },
  },
];

type Rpc = { jsonrpc: "2.0"; id?: string | number | null; method: string; params?: any };

export async function handleMcp(req: Request, env: Env, origin: string): Promise<Response> {
  if (req.method !== "POST") return new Response("method not allowed", { status: 405, headers: { Allow: "POST" } });
  let body: Rpc | Rpc[];
  try {
    body = await req.json();
  } catch {
    return Response.json({ jsonrpc: "2.0", id: null, error: { code: -32700, message: "parse error" } }, { status: 400 });
  }
  const batch = Array.isArray(body) ? body : [body];
  const replies = (await Promise.all(batch.map((m) => handle(m, env, origin)))).filter((r) => r !== null);
  if (!replies.length) return new Response(null, { status: 202 });
  return Response.json(Array.isArray(body) ? replies : replies[0]);
}

async function handle(msg: Rpc, env: Env, origin: string) {
  if (msg.id === undefined) return null; // notification
  const ok = (result: unknown) => ({ jsonrpc: "2.0", id: msg.id, result });
  switch (msg.method) {
    case "initialize":
      return ok({
        protocolVersion: msg.params?.protocolVersion ?? "2025-06-18",
        capabilities: { tools: {} },
        serverInfo: { name: "phonecall", version: "0.1.0" },
        instructions: INSTRUCTIONS,
      });
    case "ping":
      return ok({});
    case "tools/list":
      return ok({ tools: TOOLS });
    case "tools/call":
      try {
        const result = await callTool(msg.params?.name, msg.params?.arguments ?? {}, env, origin);
        return ok({ content: [{ type: "text", text: JSON.stringify(result, null, 2) }], isError: !!(result as any)?.error });
      } catch (err) {
        return ok({ content: [{ type: "text", text: `error: ${String(err)}` }], isError: true });
      }
    default:
      return { jsonrpc: "2.0", id: msg.id, error: { code: -32601, message: `unknown method ${msg.method}` } };
  }
}

async function callTool(name: string, a: Record<string, any>, env: Env, origin: string): Promise<unknown> {
  switch (name) {
    case "phonecall_start": {
      const r = await startJob(env, origin, { ...a, principal: a.for, agent_name: a.as });
      return "error" in r ? { error: r.error } : { job_id: r.job_id, next: "Call phonecall_watch with this job_id." };
    }
    case "phonecall_watch": {
      const timeout = Math.min(Math.max(Number(a.timeout_seconds ?? 45), 1), 50) * 1000;
      return (await waitForTurn(env, a.job_id, Number(a.cursor ?? 0), timeout)) ?? { error: "unknown job" };
    }
    case "phonecall_reply":
      return job(env, a.job_id).reply(a.question_id, String(a.answer ?? ""));
    case "phonecall_report": {
      const r = (await job(env, a.job_id).report()) as unknown as Awaited<ReturnType<CallJob["report"]>>;
      if (!r) return { error: "unknown job" };
      return {
        status: r.job.status,
        to: r.job.to,
        report: r.job.report ?? null,
        questions: r.questions.map((q) => ({ id: q.id, question: q.question, answer: q.answer, status: q.status })),
        transcript: r.transcript.map((t) => `${t.who === "agent" ? r.job.agentName : "Them"}: ${t.text}`).join("\n"),
      };
    }
    case "phonecall_list":
      return registry(env).list(Number(a.limit ?? 20));
    case "phonecall_hangup":
      return job(env, a.job_id).hangup();
    default:
      return { error: `unknown tool ${name}` };
  }
}
