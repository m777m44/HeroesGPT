import { DurableObject } from "cloudflare:workers";
import { callerInstructions, callerTools, simulatedCalleeInstructions, summaryPrompt } from "./prompt";
import type { Env, Job, JobEvent, JobStatus, Question, Report } from "./types";

const TERMINAL = new Set(["completed", "busy", "no-answer", "failed", "canceled"]);
// Rough speaking rate, used to wait for the goodbye to finish playing before hanging up.
const MS_PER_CHAR = 70;

export interface StartInput {
  id: string;
  to: string;
  brief: string;
  origin: string;
  principal?: string;
  agentName?: string;
  voice?: string;
  maxMinutes?: number;
  answerTimeoutSec?: number;
  simulate?: string;
}

type Answer = { question: string; answer: string | null; note?: string };

const clamp = (n: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, Math.round(n)));
const xml = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
const send = (ws: WebSocket | null, msg: unknown) => ws?.send(JSON.stringify(msg));

// One phone call: dials through Twilio, runs the Grok voice session, collects questions and the transcript.
export class CallJob extends DurableObject<Env> {
  job: Job | null = null;
  agent: WebSocket | null = null;
  sim: WebSocket | null = null;
  responseActive = false;
  userSpeaking = false;
  responseStartedAt = 0;
  audioEndsAt = 0;
  hangupPending = false;
  openerTimer: ReturnType<typeof setTimeout> | null = null;
  queue: Answer[] = [];
  waiters = new Set<() => void>();
  seenTypes = new Set<string>();
  finalizing: Promise<void> | null = null;

  constructor(ctx: DurableObjectState, env: Env) {
    super(ctx, env);
    ctx.storage.sql.exec(`CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY AUTOINCREMENT, at INTEGER, type TEXT, data TEXT)`);
    ctx.storage.sql.exec(`CREATE TABLE IF NOT EXISTS questions (id TEXT PRIMARY KEY, question TEXT, status TEXT, answer TEXT, asked_at INTEGER, answered_at INTEGER)`);
    ctx.blockConcurrencyWhile(async () => {
      this.job = (await ctx.storage.get<Job>("job")) ?? null;
    });
  }

  private registry() {
    return this.env.REGISTRY.get(this.env.REGISTRY.idFromName("main"));
  }

  private async save() {
    await this.ctx.storage.put("job", this.job);
  }

  private emit(type: string, data: Record<string, unknown> = {}) {
    this.ctx.storage.sql.exec(`INSERT INTO events (at, type, data) VALUES (?, ?, ?)`, Date.now(), type, JSON.stringify(data));
    for (const wake of this.waiters) wake();
    this.waiters.clear();
  }

  private setStatus(status: JobStatus, extra: Record<string, unknown> = {}) {
    if (!this.job || this.job.status === status) return;
    this.job.status = status;
    this.emit("status", { status, ...extra });
    this.ctx.waitUntil(this.registry().update(this.job.id, { status }));
  }

  private events(after: number): JobEvent[] {
    return this.ctx.storage.sql
      .exec<{ seq: number; at: number; type: string; data: string }>(`SELECT * FROM events WHERE seq > ? ORDER BY seq`, after)
      .toArray()
      .map((r) => ({ seq: r.seq, at: r.at, type: r.type, data: JSON.parse(r.data) }));
  }

  private questions(status?: Question["status"]): Question[] {
    const rows = status
      ? this.ctx.storage.sql.exec(`SELECT * FROM questions WHERE status = ? ORDER BY asked_at`, status)
      : this.ctx.storage.sql.exec(`SELECT * FROM questions ORDER BY asked_at`);
    return rows.toArray().map((r) => ({
      id: r.id as string,
      question: r.question as string,
      status: r.status as Question["status"],
      answer: r.answer as string | null,
      askedAt: r.asked_at as number,
      answeredAt: r.answered_at as number | null,
    }));
  }

  // ---- API ----

  async start(input: StartInput): Promise<{ ok: true } | { error: string }> {
    if (this.job) return { error: "job already exists" };
    const env = this.env;
    this.job = {
      id: input.id,
      to: input.to,
      brief: input.brief,
      principal: input.principal || env.PRINCIPAL_NAME || "",
      agentName: input.agentName || env.AGENT_NAME || "Sam",
      voice: input.voice || env.VOICE || "eve",
      maxMinutes: clamp(input.maxMinutes ?? 10, 1, 30),
      answerTimeoutSec: clamp(input.answerTimeoutSec ?? 60, 10, 300),
      simulate: input.simulate,
      origin: input.origin,
      status: "dialing",
      createdAt: Date.now(),
    };
    await this.save();
    await this.registry().add(this.job.id, this.job.to, this.job.brief);
    this.emit("status", { status: "dialing", to: this.job.to, simulated: !!this.job.simulate });
    // Backstop in case Twilio's final status callback never arrives.
    await this.ctx.storage.setAlarm(Date.now() + (this.job.maxMinutes + 5) * 60_000);

    // When the callee answers, Twilio bridges them to our xAI SIP number; the header tells the webhook which job it is.
    const agentUri = `sip:${env.TWILIO_PHONE_NUMBER}@sip.voice.x.ai;transport=tls?X-Job-Id=${this.job.id}`;
    const params = new URLSearchParams({
      From: env.TWILIO_PHONE_NUMBER,
      To: this.job.simulate ? `sip:${env.SIM_NUMBER}@sip.voice.x.ai;transport=tls?X-Sim-Job=${this.job.id}` : this.job.to,
      Twiml: `<Response><Dial><Sip username="${xml(env.SIP_USERNAME)}" password="${xml(env.SIP_PASSWORD)}">${xml(agentUri)}</Sip></Dial></Response>`,
      StatusCallback: `${this.job.origin}/twilio/status/${this.job.id}`,
      StatusCallbackMethod: "POST",
      Timeout: "30",
      TimeLimit: String(this.job.maxMinutes * 60),
    });
    for (const e of ["initiated", "ringing", "answered", "completed"]) params.append("StatusCallbackEvent", e);
    if (this.job.simulate) {
      params.set("SipAuthUsername", env.SIP_USERNAME);
      params.set("SipAuthPassword", env.SIP_PASSWORD);
    }
    const res = await this.twilio("Calls.json", params);
    const body = await res.json<{ sid?: string; message?: string }>();
    if (!res.ok || !body.sid) {
      this.emit("error", { message: `Twilio refused the call: ${body.message ?? res.status}` });
      await this.finalize("failed");
      return { error: body.message ?? `twilio ${res.status}` };
    }
    this.job.twilioCallSid = body.sid;
    await this.save();
    return { ok: true };
  }

  async twilioStatus(p: Record<string, string>) {
    if (!this.job || this.job.status === "done") return;
    const s = p.CallStatus;
    this.job.twilioStatus = s;
    if (s === "ringing") this.setStatus("ringing");
    else if (s === "in-progress") {
      this.job.answeredAt = Date.now();
      this.setStatus("connected");
    } else if (TERMINAL.has(s)) {
      this.job.durationSec = Number(p.CallDuration ?? 0);
      await this.save();
      await this.finalize(s);
      return;
    }
    await this.save();
  }

  async attach(callId: string, role: "agent" | "sim", sipHeaders: string[]): Promise<{ ok: true } | { error: string }> {
    if (!this.job || this.job.status === "done" || this.job.status === "ended") return { error: "no live job" };
    if (role === "agent" ? this.agent : this.sim) return { error: "already attached" };
    this.emit("debug", { sip_leg: role, sip_headers: sipHeaders });
    if (role === "agent") this.job.xaiCallId = callId;
    else this.job.simCallId = callId;
    await this.save();

    const res = await fetch(`https://api.x.ai/v1/realtime?call_id=${encodeURIComponent(callId)}`, {
      headers: { Upgrade: "websocket", Authorization: `Bearer ${this.env.XAI_API_KEY}` },
    });
    const ws = res.webSocket;
    if (!ws) {
      this.emit("error", { message: `xAI realtime connect failed (${role}): ${res.status} ${(await res.text()).slice(0, 200)}` });
      return { error: "xai connect failed" };
    }
    ws.accept();
    if (role === "agent") {
      this.agent = ws;
      await this.registry().update(this.job.id, { attached: true });
      this.setupAgent(ws);
    } else {
      this.sim = ws;
      this.setupSim(ws);
    }
    return { ok: true };
  }

  async watch(after: number, timeoutMs: number) {
    if (!this.job) return null;
    let events = this.events(after);
    if (!events.length && this.job.status !== "done" && !this.questions("pending").length) {
      await new Promise<void>((resolve) => {
        this.waiters.add(resolve);
        setTimeout(resolve, timeoutMs);
      });
      events = this.events(after);
    }
    return {
      status: this.job.status,
      cursor: events.at(-1)?.seq ?? after,
      events,
      pending: this.questions("pending"),
      report: this.job.report ?? null,
    };
  }

  async reply(questionId: string, answer: string): Promise<{ ok: true; delivered: boolean } | { error: string }> {
    const q = this.questions().find((x) => x.id === questionId);
    if (!q) return { error: `unknown question ${questionId}` };
    if (q.status === "answered") return { error: `${questionId} is already answered` };
    this.ctx.storage.sql.exec(`UPDATE questions SET status = 'answered', answer = ?, answered_at = ? WHERE id = ?`, answer, Date.now(), questionId);
    this.emit("answer", { id: questionId, answer, late: q.status === "timed_out" });
    if (!this.agent) return { ok: true, delivered: false };
    this.queue.push({ question: q.question, answer });
    this.flush();
    return { ok: true, delivered: true };
  }

  async hangup() {
    if (!this.job) return { error: "unknown job" };
    this.emit("status", { status: "hangup_requested" });
    await this.endCall();
    return { ok: true };
  }

  async report() {
    if (!this.job) return null;
    const { origin: _origin, ...job } = this.job;
    return {
      job,
      questions: this.questions(),
      transcript: this.events(0)
        .filter((e) => e.type === "said")
        .map((e) => ({ at: e.at, who: e.data.who, text: e.data.text })),
    };
  }

  async alarm() {
    if (this.job && this.job.status !== "done") {
      await this.endCall();
      await this.finalize("timeout");
    }
  }

  // ---- Voice session ----

  private setupAgent(ws: WebSocket) {
    const job = this.job!;
    ws.addEventListener("message", (m) => {
      if (typeof m.data === "string") this.onAgentEvent(JSON.parse(m.data));
    });
    ws.addEventListener("close", (e) => {
      this.agent = null;
      this.emit("status", { status: "voice_session_closed", code: e.code });
    });
    send(ws, {
      type: "session.update",
      session: {
        instructions: callerInstructions(job),
        voice: job.voice,
        turn_detection: { type: "server_vad" },
        tools: callerTools(job.principal),
      },
    });
    // The callee usually said "hello" before the bridge connected; open if they don't speak again.
    this.openerTimer = setTimeout(() => {
      if (!this.responseActive && !this.userSpeaking) this.respond();
    }, 1500);
  }

  // The transcript records what our agent heard, so a simulated call exercises the same path as a real one.
  private setupSim(ws: WebSocket) {
    ws.addEventListener("close", () => {
      this.sim = null;
    });
    send(ws, {
      type: "session.update",
      session: { instructions: simulatedCalleeInstructions(this.job!.simulate!), voice: "rex", turn_detection: { type: "server_vad" } },
    });
    send(ws, { type: "response.create" });
  }

  private onAgentEvent(e: any) {
    // Events still buffered after the call ended were never heard by anyone.
    if (!this.job || this.job.status === "ended" || this.job.status === "done") return;
    switch (e.type) {
      case "response.created":
        this.responseActive = true;
        this.responseStartedAt = Date.now();
        break;
      case "response.output_audio.delta":
      case "response.output_audio_transcript.delta":
      case "response.function_call_arguments.delta":
      case "input_audio_buffer.append":
      case "ping":
        break;
      case "response.output_audio_transcript.done": {
        const text = e.transcript?.trim();
        if (!text) break;
        this.emit("said", { who: "agent", text });
        this.audioEndsAt = Math.max(this.audioEndsAt, this.responseStartedAt + text.length * MS_PER_CHAR);
        break;
      }
      case "conversation.item.added": {
        // xAI puts the caller's transcript on the committed user item; there is no separate transcription event.
        const item = e.item ?? {};
        if (item.role !== "user" || item.type !== "message") break;
        const text = (item.content ?? [])
          .filter((c: any) => c.type === "input_audio")
          .map((c: any) => c.transcript ?? "")
          .join(" ")
          .trim();
        if (text) this.emit("said", { who: "them", text });
        break;
      }
      case "input_audio_buffer.speech_started":
        this.userSpeaking = true;
        if (this.openerTimer) clearTimeout(this.openerTimer);
        break;
      case "input_audio_buffer.speech_stopped":
        this.userSpeaking = false;
        setTimeout(() => this.flush(), 400);
        break;
      case "response.function_call_arguments.done":
        this.onTool(e.name, e.call_id, e.arguments);
        break;
      case "response.done":
        this.responseActive = false;
        if (this.hangupPending) this.scheduleHangup();
        else this.flush();
        break;
      case "error":
        this.emit("error", { message: e.error?.message ?? JSON.stringify(e).slice(0, 300) });
        break;
      default:
        if (!this.seenTypes.has(e.type)) {
          this.seenTypes.add(e.type);
          this.emit("debug", { xai_event: e.type, sample: JSON.stringify(e).slice(0, 300) });
        }
    }
  }

  private onTool(name: string, callId: string, argsJson: string) {
    const job = this.job!;
    let args: Record<string, string> = {};
    try {
      args = JSON.parse(argsJson || "{}");
    } catch {}
    switch (name) {
      case "send_dtmf":
        // xAI sends the tones itself and expects no reply.
        this.emit("dtmf", args);
        return;
      case "request_input": {
        const id = `q${this.questions().length + 1}`;
        this.ctx.storage.sql.exec(`INSERT INTO questions (id, question, status, asked_at) VALUES (?, ?, 'pending', ?)`, id, args.question ?? "", Date.now());
        this.emit("input_request", { id, question: args.question });
        this.output(callId, { status: "sent", note: `${job.principal} has your question. Don't say anything else about it unless they talk to you.` }, false);
        setTimeout(() => this.expireQuestion(id), job.answerTimeoutSec * 1000);
        return;
      }
      case "check_messages": {
        const answers = this.queue.splice(0);
        // With nothing to report, stay quiet instead of prompting a turn ("Still nothing...").
        if (answers.length) this.output(callId, { answers }, true);
        else this.output(callId, { answers: [], note: `${job.principal} is still checking. Don't comment on it; carry on only if they talk to you.` }, false);
        return;
      }
      case "end_call":
        job.endCall = { outcome: args.outcome ?? "done", notes: args.notes };
        this.ctx.waitUntil(this.save());
        this.emit("end_call", job.endCall);
        this.output(callId, { ok: true }, false);
        this.hangupPending = true;
        if (!this.responseActive) this.scheduleHangup();
        return;
      default:
        this.output(callId, { error: `unknown tool ${name}` }, true);
    }
  }

  private output(callId: string, result: unknown, respond: boolean) {
    send(this.agent, { type: "conversation.item.create", item: { type: "function_call_output", call_id: callId, output: JSON.stringify(result) } });
    if (respond) this.respond();
  }

  private respond() {
    if (!this.agent) return;
    send(this.agent, { type: "response.create" });
    this.responseActive = true;
  }

  // Deliver answers as a check_messages tool result. A plain system message gets ignored by the model.
  private flush() {
    if (!this.agent || this.responseActive || this.userSpeaking || this.hangupPending || !this.queue.length) return;
    const answers = this.queue.splice(0);
    const callId = `call-msg-${Date.now()}`;
    send(this.agent, { type: "conversation.item.create", item: { type: "function_call", call_id: callId, name: "check_messages", arguments: "{}" } });
    send(this.agent, { type: "conversation.item.create", item: { type: "function_call_output", call_id: callId, output: JSON.stringify({ answers }) } });
    this.respond();
  }

  private expireQuestion(id: string) {
    const q = this.questions("pending").find((x) => x.id === id);
    if (!q || !this.job) return;
    this.ctx.storage.sql.exec(`UPDATE questions SET status = 'timed_out' WHERE id = ?`, id);
    this.emit("input_timeout", { id });
    this.queue.push({ question: q.question, answer: null, note: `${this.job.principal} didn't answer in time. Say you'll have to get back to them on that part and keep going.` });
    this.flush();
  }

  private scheduleHangup() {
    const wait = Math.max(this.audioEndsAt - Date.now(), 0) + 1200;
    setTimeout(() => this.ctx.waitUntil(this.endCall()), wait);
  }

  private async endCall() {
    const job = this.job;
    if (!job) return;
    if (job.xaiCallId) {
      const res = await fetch(`https://api.x.ai/v1/realtime/calls/${job.xaiCallId}/hangup`, {
        method: "POST",
        headers: { Authorization: `Bearer ${this.env.XAI_API_KEY}` },
      });
      if (res.ok) return;
    }
    if (job.twilioCallSid) {
      const status = job.status === "connected" ? "completed" : "canceled";
      await this.twilio(`Calls/${job.twilioCallSid}.json`, new URLSearchParams({ Status: status }));
    }
  }

  private twilio(path: string, body: URLSearchParams) {
    const { TWILIO_ACCOUNT_SID: sid, TWILIO_AUTH_TOKEN: token } = this.env;
    return fetch(`https://api.twilio.com/2010-04-01/Accounts/${sid}/${path}`, {
      method: "POST",
      headers: { Authorization: `Basic ${btoa(`${sid}:${token}`)}`, "Content-Type": "application/x-www-form-urlencoded" },
      body,
    });
  }

  // ---- Wrap-up ----

  private finalize(reason: string): Promise<void> {
    if (!this.job || this.job.status === "done") return Promise.resolve();
    this.finalizing ??= (async () => {
      const job = this.job!;
      job.endedAt = Date.now();
      this.setStatus("ended", { reason });
      if (this.openerTimer) clearTimeout(this.openerTimer);
      for (const ws of [this.agent, this.sim]) {
        try {
          ws?.close(1000, "call ended");
        } catch {}
      }
      this.agent = this.sim = null;
      this.ctx.storage.sql.exec(`UPDATE questions SET status = 'timed_out' WHERE status = 'pending'`);
      job.report = await this.summarize(reason);
      await this.save();
      this.setStatus("done");
      this.emit("done", { report: job.report });
      await this.ctx.storage.deleteAlarm();
    })();
    return this.finalizing;
  }

  private async summarize(reason: string): Promise<Report> {
    const job = this.job!;
    const lines = this.events(0)
      .filter((e) => e.type === "said")
      .map((e) => `${e.data.who === "agent" ? job.agentName : "Them"}: ${e.data.text}`);
    const empty = (outcome: string, summary: string): Report => ({ outcome, summary, details: {}, commitments: [], follow_ups: [] });
    if (!lines.length) {
      if (reason === "busy") return empty("no_answer", "The line was busy.");
      if (reason === "no-answer") return empty("no_answer", "Nobody picked up.");
      if (reason === "completed") return empty("failed", "The call connected but nothing was said.");
      return empty("failed", `The call ended before anyone talked (${reason}).`);
    }
    const questions = this.questions()
      .map((q) => `- ${q.question} → ${q.answer ?? "(no answer)"}`)
      .join("\n");
    try {
      const res = await fetch("https://api.x.ai/v1/chat/completions", {
        method: "POST",
        headers: { Authorization: `Bearer ${this.env.XAI_API_KEY}`, "Content-Type": "application/json" },
        body: JSON.stringify({
          model: this.env.SUMMARY_MODEL || "grok-4.7",
          messages: [{ role: "user", content: summaryPrompt(job, lines.join("\n"), questions) }],
          response_format: { type: "json_object" },
        }),
      });
      const body = await res.json<any>();
      const parsed = JSON.parse(body.choices[0].message.content);
      return {
        outcome: parsed.outcome ?? job.endCall?.outcome ?? "partial",
        summary: parsed.summary ?? "",
        details: parsed.details ?? {},
        commitments: parsed.commitments ?? [],
        follow_ups: parsed.follow_ups ?? [],
      };
    } catch (err) {
      return empty(job.endCall?.outcome ?? "partial", `Summary failed (${String(err).slice(0, 120)}). Agent note: ${job.endCall?.notes ?? "none"}`);
    }
  }
}
