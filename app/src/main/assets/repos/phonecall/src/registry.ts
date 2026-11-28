import { DurableObject } from "cloudflare:workers";
import type { Env, JobStatus } from "./types";

export type JobRow = {
  id: string;
  to: string;
  status: JobStatus;
  created_at: number;
  attached: number;
  brief: string;
};

// One instance ("main") that lists jobs and matches incoming SIP legs to jobs without a header.
export class Registry extends DurableObject<Env> {
  constructor(ctx: DurableObjectState, env: Env) {
    super(ctx, env);
    ctx.storage.sql.exec(`CREATE TABLE IF NOT EXISTS jobs (
      id TEXT PRIMARY KEY, "to" TEXT, status TEXT, created_at INTEGER, attached INTEGER DEFAULT 0, brief TEXT)`);
  }

  add(id: string, to: string, brief: string) {
    this.ctx.storage.sql.exec(`INSERT INTO jobs (id, "to", status, created_at, brief) VALUES (?, ?, 'dialing', ?, ?)`, id, to, Date.now(), brief.slice(0, 200));
  }

  update(id: string, fields: { status?: JobStatus; attached?: boolean }) {
    if (fields.status) this.ctx.storage.sql.exec(`UPDATE jobs SET status = ? WHERE id = ?`, fields.status, id);
    if (fields.attached) this.ctx.storage.sql.exec(`UPDATE jobs SET attached = 1 WHERE id = ?`, id);
  }

  list(limit: number): JobRow[] {
    return this.ctx.storage.sql.exec<JobRow>(`SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?`, limit).toArray();
  }

  // Most recent live job whose voice agent hasn't joined yet.
  unattached(): string | null {
    const row = this.ctx.storage.sql
      .exec<{ id: string }>(`SELECT id FROM jobs WHERE attached = 0 AND status IN ('dialing', 'ringing', 'connected') AND created_at > ? ORDER BY created_at DESC LIMIT 1`, Date.now() - 10 * 60_000)
      .toArray()[0];
    return row?.id ?? null;
  }
}
