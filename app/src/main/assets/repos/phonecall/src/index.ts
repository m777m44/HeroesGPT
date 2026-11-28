import { CallJob } from "./call-job";
import { job, registry, startJob } from "./jobs";
import { handleMcp } from "./mcp";
import { Registry } from "./registry";
import type { Env } from "./types";
import { safeEqual, verifyStandardWebhook, verifyTwilio } from "./verify";

export { CallJob, Registry };

const json = (data: unknown, status = 200) => Response.json(data, { status });

export default {
  async fetch(req, env, ctx): Promise<Response> {
    const url = new URL(req.url);
    const [root, a, b] = url.pathname.split("/").filter(Boolean);

    if (root === "twilio" && a === "status" && b && req.method === "POST") {
      const params = new URLSearchParams(await req.text());
      if (!(await verifyTwilio(env.TWILIO_AUTH_TOKEN, url.toString(), params, req.headers.get("x-twilio-signature")))) return new Response("bad signature", { status: 403 });
      await job(env, b).twilioStatus(Object.fromEntries(params));
      return new Response(null, { status: 204 });
    }

    if (root === "xai" && a === "webhook" && req.method === "POST") {
      const body = await req.text();
      if (!(await verifyStandardWebhook(env.XAI_WEBHOOK_SECRET, req.headers, body))) return new Response("bad signature", { status: 403 });
      const event = JSON.parse(body);
      if (event.type !== "realtime.call.incoming") return new Response(null, { status: 204 });
      const headers: { name: string; value: string }[] = event.data?.sip_headers ?? [];
      const header = (name: string) => headers.find((h) => h.name.toLowerCase() === name.toLowerCase())?.value;
      const simJob = header("X-Sim-Job");
      const role = simJob || (env.SIM_NUMBER && header("To")?.includes(env.SIM_NUMBER)) ? "sim" : "agent";
      const jobId = role === "sim" ? simJob : (header("X-Job-Id") ?? (await registry(env).unattached()));
      if (!jobId) return json({ error: "no job for this call" }, 404);
      ctx.waitUntil(job(env, jobId).attach(event.data.call_id, role, headers.map((h) => h.name)));
      return new Response(null, { status: 204 });
    }

    if (root !== "jobs" && root !== "mcp") return new Response("not found", { status: 404 });
    if (!safeEqual(req.headers.get("authorization") ?? "", `Bearer ${env.PHONECALL_TOKEN}`)) return json({ error: "unauthorized" }, 401);
    if (root === "mcp") return handleMcp(req, env, url.origin);

    if (!a && req.method === "GET") return json(await registry(env).list(Number(url.searchParams.get("limit") ?? 20)));
    if (!a && req.method === "POST") {
      const result = await startJob(env, url.origin, await req.json());
      return "error" in result ? json({ error: result.error }, result.status) : json(result, 201);
    }

    const stub = job(env, a);
    if (!b && req.method === "GET") {
      const report = await stub.report();
      return report ? json(report) : json({ error: "unknown job" }, 404);
    }
    if (b === "watch" && req.method === "GET") {
      const after = Number(url.searchParams.get("after") ?? 0);
      const timeout = Math.min(Number(url.searchParams.get("timeout") ?? 25), 50) * 1000;
      const result = await stub.watch(after, timeout);
      return result ? json(result) : json({ error: "unknown job" }, 404);
    }
    if (b === "reply" && req.method === "POST") {
      const { question_id, answer } = await req.json<{ question_id?: string; answer?: string }>();
      if (!question_id || typeof answer !== "string") return json({ error: "question_id and answer are required" }, 400);
      const result = await stub.reply(question_id, answer);
      return json(result, "error" in result ? 400 : 200);
    }
    if (b === "hangup" && req.method === "POST") return json(await stub.hangup());
    return new Response("not found", { status: 404 });
  },
} satisfies ExportedHandler<Env>;
