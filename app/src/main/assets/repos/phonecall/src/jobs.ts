import type { Env, JobEvent } from "./types";

const E164 = /^\+[1-9]\d{7,14}$/;

export function job(env: Env, id: string) {
  return env.CALL_JOB.get(env.CALL_JOB.idFromName(id));
}

export function registry(env: Env) {
  return env.REGISTRY.get(env.REGISTRY.idFromName("main"));
}

export interface StartRequest {
  to?: string;
  brief?: string;
  principal?: string;
  agent_name?: string;
  voice?: string;
  max_minutes?: number;
  answer_timeout?: number;
  simulate?: string;
}

export async function startJob(env: Env, origin: string, input: StartRequest): Promise<{ job_id: string } | { error: string; status: number }> {
  const simulate = typeof input.simulate === "string" && input.simulate.trim() ? input.simulate.trim() : undefined;
  if (!simulate && !E164.test(input.to ?? "")) return { error: "to must be an E.164 number like +14155550100", status: 400 };
  if (simulate && !env.SIM_NUMBER) return { error: "simulated calls need a SIM_NUMBER; run npm run setup again with simulation on", status: 400 };
  if (!input.principal && !env.PRINCIPAL_NAME) return { error: "say who the call is for: pass `for`, or set the PRINCIPAL_NAME secret", status: 400 };
  if (typeof input.brief !== "string" || !input.brief.trim()) return { error: "brief is required", status: 400 };
  if (input.brief.length > 8000) return { error: "brief is too long (8000 chars max)", status: 400 };
  const id = `job_${crypto.randomUUID().replaceAll("-", "").slice(0, 12)}`;
  const result = await job(env, id).start({
    id,
    to: simulate ? "simulated" : input.to!,
    brief: input.brief,
    origin,
    principal: input.principal,
    agentName: input.agent_name,
    voice: input.voice,
    maxMinutes: input.max_minutes,
    answerTimeoutSec: input.answer_timeout,
    simulate,
  });
  return "error" in result ? { error: result.error, status: 502 } : { job_id: id };
}

// Waits until the agent has a question, the call is over, or the deadline passes.
export async function waitForTurn(env: Env, jobId: string, after: number, timeoutMs: number) {
  const stub = job(env, jobId);
  const deadline = Date.now() + timeoutMs;
  const lines: string[] = [];
  let cursor = after;
  for (;;) {
    const r = await stub.watch(cursor, Math.max(0, Math.min(deadline - Date.now(), 25_000)));
    if (!r) return null;
    for (const e of r.events as unknown as JobEvent[]) {
      const line = describe(e);
      if (line) lines.push(line);
    }
    cursor = r.cursor;
    if (r.pending.length) return { type: "input_request", job_id: jobId, question_id: r.pending[0].id, question: r.pending[0].question, cursor, progress: lines };
    if (r.status === "done") return { type: "done", job_id: jobId, report: r.report, cursor, progress: lines };
    if (Date.now() >= deadline) return { type: "running", job_id: jobId, status: r.status, cursor, progress: lines };
  }
}

export function describe(e: JobEvent): string | null {
  const d = e.data as Record<string, any>;
  switch (e.type) {
    case "status":
      return `· ${d.status}${d.reason ? ` (${d.reason})` : ""}`;
    case "said":
      return `${d.who === "agent" ? "agent" : "them"}: ${d.text}`;
    case "input_request":
      return `? ${d.id}: ${d.question}`;
    case "answer":
      return `↳ ${d.id}: ${d.answer}${d.late ? " (late)" : ""}`;
    case "input_timeout":
      return `! ${d.id} timed out without an answer`;
    case "end_call":
      return `· agent hung up: ${d.outcome}`;
    case "error":
      return `! ${d.message}`;
    default:
      return null;
  }
}
