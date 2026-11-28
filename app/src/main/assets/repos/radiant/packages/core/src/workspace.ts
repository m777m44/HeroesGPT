import { Effect } from "effect"
import type { WorkspaceRole } from "@radiant/database/schema"
import { randomToken, sha256Hex } from "./crypto"
import { Database, type DbExecutor } from "./db"
import { ConflictError, ForbiddenError, NotFoundError, ValidationError } from "./errors"
import { Id } from "./id"

export interface Actor {
  readonly type: "user" | "agent" | "system"
  readonly userId: string
  readonly email: string
  readonly name: string | null
  readonly clientName: string | null
  /** If authenticated via workspace-scoped API token, restricts access to this single workspace + role cap. */
  readonly scopedWorkspaceId?: string
  readonly scopedRole?: WorkspaceRole
}

export interface WorkspaceRecord {
  readonly id: string
  readonly slug: string
  readonly name: string
  readonly currency: string
  readonly role: WorkspaceRole
  readonly created_at: string
}

export interface MemberRecord {
  readonly user_id: string
  readonly email: string
  readonly name: string | null
  readonly role: WorkspaceRole
  readonly created_at: string
}

export interface InviteRecord {
  readonly id: string
  readonly workspace_id: string
  readonly email: string
  readonly role: WorkspaceRole
  readonly invited_by: string
  readonly expires_at: string
  readonly accepted_at: string | null
  readonly revoked_at: string | null
  readonly created_at: string
}

const ROLE_RANK: Readonly<Record<WorkspaceRole, number>> = {
  viewer: 1,
  member: 2,
  admin: 3,
  owner: 4,
}

export const hasRole = (actual: WorkspaceRole, required: WorkspaceRole): boolean =>
  ROLE_RANK[actual] >= ROLE_RANK[required]

export const slugify = (name: string): string => {
  const base = name
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 48)
  return base.length >= 2 ? base : `ws-${Id.workspace().slice(-6).toLowerCase()}`
}

export const assertWorkspaceAccess = (
  actor: Actor,
  workspaceIdOrSlug: string,
  minRole: WorkspaceRole = "viewer",
): Effect.Effect<WorkspaceRecord, ForbiddenError | NotFoundError | import("./errors").DatabaseError, Database> =>
  Effect.gen(function* () {
    const db = yield* Database
    const res = yield* db.query<{
      id: string
      slug: string
      name: string
      currency: string
      role: WorkspaceRole
      created_at: string
    }>(
      `SELECT w.id, w.slug, w.name, w.currency, m.role, w.created_at
       FROM workspace w
       INNER JOIN workspace_member m ON m.workspace_id = w.id AND m.user_id = ?
       WHERE (w.id = ? OR w.slug = ?) AND w.deleted_at IS NULL
       LIMIT 1`,
      [actor.userId, workspaceIdOrSlug, workspaceIdOrSlug],
    )
    const row = res.rows[0]
    if (!row) {
      return yield* new NotFoundError({ entity: "workspace", id: workspaceIdOrSlug })
    }
    if (actor.scopedWorkspaceId && actor.scopedWorkspaceId !== row.id) {
      return yield* new ForbiddenError({ message: "API token is scoped to a different workspace" })
    }
    const effectiveRole =
      actor.scopedRole && ROLE_RANK[actor.scopedRole] < ROLE_RANK[row.role]
        ? actor.scopedRole
        : row.role
    if (!hasRole(effectiveRole, minRole)) {
      return yield* new ForbiddenError({
        message: `Requires '${minRole}' role in workspace '${row.slug}' (have '${effectiveRole}')`,
      })
    }
    return { ...row, role: effectiveRole }
  })

/** Resolve workspace when workspace_id is omitted (succeeds only if user belongs to exactly one active workspace). */
export const resolveWorkspaceAccess = (
  actor: Actor,
  workspaceIdOrSlug: string | undefined,
  minRole: WorkspaceRole = "viewer",
) =>
  Effect.gen(function* () {
    if (workspaceIdOrSlug) {
      return yield* assertWorkspaceAccess(actor, workspaceIdOrSlug, minRole)
    }
    if (actor.scopedWorkspaceId) {
      return yield* assertWorkspaceAccess(actor, actor.scopedWorkspaceId, minRole)
    }
    const all = yield* listWorkspaces(actor)
    if (all.length === 1) {
      return yield* assertWorkspaceAccess(actor, all[0]!.id, minRole)
    }
    if (all.length === 0) {
      return yield* new NotFoundError({
        entity: "workspace",
        message: "No workspaces found. Create one first with workspace_create.",
      })
    }
    return yield* new ValidationError({
      message: `Multiple workspaces available (${all.map((w) => w.slug).join(", ")}); specify workspace_id`,
      field: "workspace_id",
    })
  })

export const listWorkspaces = (actor: Actor) =>
  Effect.gen(function* () {
    const db = yield* Database
    const res = yield* db.query<WorkspaceRecord>(
      `SELECT w.id, w.slug, w.name, w.currency, m.role, w.created_at
       FROM workspace w
       INNER JOIN workspace_member m ON m.workspace_id = w.id AND m.user_id = ?
       WHERE w.deleted_at IS NULL
       ORDER BY w.created_at ASC`,
      [actor.userId],
    )
    const rows = actor.scopedWorkspaceId
      ? res.rows.filter((r) => r.id === actor.scopedWorkspaceId)
      : res.rows
    return rows
  })

export const createWorkspace = (
  actor: Actor,
  input: { readonly name: string; readonly slug?: string; readonly currency?: string },
) =>
  Effect.gen(function* () {
    const name = input.name.trim()
    if (name.length < 1 || name.length > 120) {
      return yield* new ValidationError({ message: "Workspace name must be 1..120 characters", field: "name" })
    }
    const currency = (input.currency ?? "USD").trim().toUpperCase()
    if (!/^[A-Z]{3}$/.test(currency)) {
      return yield* new ValidationError({ message: "Currency must be a 3-letter ISO code", field: "currency" })
    }
    const slug = input.slug ? slugify(input.slug) : slugify(name)
    const db = yield* Database

    const existing = yield* db.query<{ id: string }>(
      "SELECT id FROM workspace WHERE slug = ? LIMIT 1",
      [slug],
    )
    const finalSlug =
      existing.rows.length === 0
        ? slug
        : input.slug
          ? yield* new ConflictError({ message: `Workspace slug '${slug}' is already taken` })
          : `${slug}-${Id.workspace().slice(-5).toLowerCase()}`

    const id = Id.workspace()
    const now = new Date()

    yield* db.transaction((tx: DbExecutor) =>
      Effect.gen(function* () {
        yield* tx.execute(
          `INSERT INTO workspace (id, slug, name, currency, created_by, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)`,
          [id, finalSlug, name, currency, actor.userId, now, now],
        )
        yield* tx.execute(
          `INSERT INTO workspace_member (workspace_id, user_id, role, created_at, updated_at)
           VALUES (?, ?, 'owner', ?, ?)`,
          [id, actor.userId, now, now],
        )
      }),
    )

    return {
      id,
      slug: finalSlug,
      name,
      currency,
      role: "owner" as const,
      created_at: now.toISOString(),
    }
  })

export const updateWorkspace = (
  actor: Actor,
  workspaceId: string,
  input: { readonly name?: string; readonly currency?: string },
) =>
  Effect.gen(function* () {
    const ws = yield* assertWorkspaceAccess(actor, workspaceId, "admin")
    const name = input.name !== undefined ? input.name.trim() : ws.name
    if (name.length < 1 || name.length > 120) {
      return yield* new ValidationError({ message: "Workspace name must be 1..120 characters", field: "name" })
    }
    const currency = input.currency !== undefined ? input.currency.trim().toUpperCase() : ws.currency
    if (!/^[A-Z]{3}$/.test(currency)) {
      return yield* new ValidationError({ message: "Currency must be a 3-letter ISO code", field: "currency" })
    }
    const db = yield* Database
    yield* db.execute(
      "UPDATE workspace SET name = ?, currency = ?, updated_at = ? WHERE id = ?",
      [name, currency, new Date(), ws.id],
    )
    return { ...ws, name, currency }
  })

export const deleteWorkspace = (actor: Actor, workspaceId: string) =>
  Effect.gen(function* () {
    const ws = yield* assertWorkspaceAccess(actor, workspaceId, "owner")
    const db = yield* Database
    const now = new Date()
    yield* db.execute(
      "UPDATE workspace SET deleted_at = ?, updated_at = ? WHERE id = ?",
      [now, now, ws.id],
    )
    return { id: ws.id, deleted: true }
  })

export const listMembers = (actor: Actor, workspaceId: string) =>
  Effect.gen(function* () {
    const ws = yield* assertWorkspaceAccess(actor, workspaceId, "viewer")
    const db = yield* Database
    const res = yield* db.query<MemberRecord>(
      `SELECT m.user_id, u.email, u.name, m.role, m.created_at
       FROM workspace_member m
       INNER JOIN user u ON u.id = m.user_id
       WHERE m.workspace_id = ?
       ORDER BY m.created_at ASC`,
      [ws.id],
    )
    return res.rows
  })

export const updateMemberRole = (
  actor: Actor,
  workspaceId: string,
  targetUserId: string,
  role: WorkspaceRole,
) =>
  Effect.gen(function* () {
    const ws = yield* assertWorkspaceAccess(actor, workspaceId, "admin")
    if (role === "owner" && ws.role !== "owner") {
      return yield* new ForbiddenError({ message: "Only an owner can promote someone to owner" })
    }
    const db = yield* Database
    const current = yield* db.query<{ role: WorkspaceRole }>(
      "SELECT role FROM workspace_member WHERE workspace_id = ? AND user_id = ? LIMIT 1",
      [ws.id, targetUserId],
    )
    if (!current.rows[0]) {
      return yield* new NotFoundError({ entity: "workspace_member", id: targetUserId })
    }
    if (current.rows[0].role === "owner" && role !== "owner") {
      if (ws.role !== "owner") {
        return yield* new ForbiddenError({ message: "Only an owner can change another owner's role" })
      }
      const owners = yield* db.query<{ cnt: number }>(
        "SELECT COUNT(*) AS cnt FROM workspace_member WHERE workspace_id = ? AND role = 'owner'",
        [ws.id],
      )
      if (Number(owners.rows[0]?.cnt ?? 0) <= 1) {
        return yield* new ConflictError({ message: "Cannot demote the last owner of a workspace" })
      }
    }
    yield* db.execute(
      "UPDATE workspace_member SET role = ?, updated_at = ? WHERE workspace_id = ? AND user_id = ?",
      [role, new Date(), ws.id, targetUserId],
    )
    return { workspace_id: ws.id, user_id: targetUserId, role }
  })

export const removeMember = (actor: Actor, workspaceId: string, targetUserId: string) =>
  Effect.gen(function* () {
    const isSelf = actor.userId === targetUserId
    const ws = yield* assertWorkspaceAccess(actor, workspaceId, isSelf ? "viewer" : "admin")
    const db = yield* Database
    const current = yield* db.query<{ role: WorkspaceRole }>(
      "SELECT role FROM workspace_member WHERE workspace_id = ? AND user_id = ? LIMIT 1",
      [ws.id, targetUserId],
    )
    if (!current.rows[0]) {
      return yield* new NotFoundError({ entity: "workspace_member", id: targetUserId })
    }
    if (current.rows[0].role === "owner") {
      if (!isSelf && ws.role !== "owner") {
        return yield* new ForbiddenError({ message: "Only an owner can remove an owner" })
      }
      const owners = yield* db.query<{ cnt: number }>(
        "SELECT COUNT(*) AS cnt FROM workspace_member WHERE workspace_id = ? AND role = 'owner'",
        [ws.id],
      )
      if (Number(owners.rows[0]?.cnt ?? 0) <= 1) {
        return yield* new ConflictError({ message: "Cannot remove the last owner of a workspace" })
      }
    }
    yield* db.execute(
      "DELETE FROM workspace_member WHERE workspace_id = ? AND user_id = ?",
      [ws.id, targetUserId],
    )
    return { workspace_id: ws.id, user_id: targetUserId, removed: true }
  })

export const createInvite = (
  actor: Actor,
  workspaceId: string,
  input: { readonly email: string; readonly role?: WorkspaceRole; readonly expiresInDays?: number },
  origin: string,
) =>
  Effect.gen(function* () {
    const ws = yield* assertWorkspaceAccess(actor, workspaceId, "admin")
    const email = input.email.trim().toLowerCase()
    if (!email.includes("@") || email.length > 320) {
      return yield* new ValidationError({ message: "Valid email address is required", field: "email" })
    }
    const role: WorkspaceRole = input.role ?? "member"
    if (role === "owner" && ws.role !== "owner") {
      return yield* new ForbiddenError({ message: "Only an owner can invite another owner" })
    }
    const ttlDays = Math.max(1, Math.min(input.expiresInDays ?? 7, 30))
    const rawToken = randomToken("rdi1_", 24)
    const tokenHash = yield* sha256Hex(rawToken)
    const id = Id.invite()
    const now = new Date()
    const expiresAt = new Date(now.getTime() + ttlDays * 86_400_000)

    const db = yield* Database
    yield* db.execute(
      `INSERT INTO workspace_invite
        (workspace_id, id, email, role, token_hash, invited_by, expires_at, created_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
      [ws.id, id, email, role, tokenHash, actor.userId, expiresAt, now],
    )

    return {
      id,
      workspace_id: ws.id,
      email,
      role,
      invite_token: rawToken,
      invite_url: `${origin.replace(/\/$/, "")}/invite/${rawToken}`,
      expires_at: expiresAt.toISOString(),
    }
  })

export const listInvites = (actor: Actor, workspaceId: string) =>
  Effect.gen(function* () {
    const ws = yield* assertWorkspaceAccess(actor, workspaceId, "admin")
    const db = yield* Database
    const res = yield* db.query<InviteRecord>(
      `SELECT id, workspace_id, email, role, invited_by, expires_at, accepted_at, revoked_at, created_at
       FROM workspace_invite
       WHERE workspace_id = ?
       ORDER BY created_at DESC`,
      [ws.id],
    )
    return res.rows
  })

export const revokeInvite = (actor: Actor, workspaceId: string, inviteId: string) =>
  Effect.gen(function* () {
    const ws = yield* assertWorkspaceAccess(actor, workspaceId, "admin")
    const db = yield* Database
    const res = yield* db.execute(
      `UPDATE workspace_invite SET revoked_at = ?
       WHERE workspace_id = ? AND id = ? AND accepted_at IS NULL AND revoked_at IS NULL`,
      [new Date(), ws.id, inviteId],
    )
    if (res.rowsAffected === 0) {
      return yield* new NotFoundError({ entity: "workspace_invite", id: inviteId })
    }
    return { id: inviteId, revoked: true }
  })

export const acceptInvite = (actor: Actor, inviteToken: string) =>
  Effect.gen(function* () {
    const tokenHash = yield* sha256Hex(inviteToken.trim())
    const db = yield* Database
    const res = yield* db.query<{
      workspace_id: string
      id: string
      email: string
      role: WorkspaceRole
      expires_at: string
      accepted_at: string | null
      revoked_at: string | null
    }>(
      `SELECT workspace_id, id, email, role, expires_at, accepted_at, revoked_at
       FROM workspace_invite
       WHERE token_hash = ?
       LIMIT 1`,
      [tokenHash],
    )
    const inv = res.rows[0]
    if (!inv) {
      return yield* new NotFoundError({ entity: "workspace_invite", message: "Invalid invite token" })
    }
    if (inv.revoked_at) {
      return yield* new ForbiddenError({ message: "Invite has been revoked" })
    }
    if (inv.accepted_at) {
      return yield* new ConflictError({ message: "Invite has already been accepted" })
    }
    if (new Date(inv.expires_at).getTime() < Date.now()) {
      return yield* new ForbiddenError({ message: "Invite has expired" })
    }

    const now = new Date()
    yield* db.transaction((tx: DbExecutor) =>
      Effect.gen(function* () {
        yield* tx.execute(
          `UPDATE workspace_invite SET accepted_at = ?, accepted_by = ?
           WHERE workspace_id = ? AND id = ? AND accepted_at IS NULL`,
          [now, actor.userId, inv.workspace_id, inv.id],
        )
        const existingMember = yield* tx.query<{ role: WorkspaceRole }>(
          "SELECT role FROM workspace_member WHERE workspace_id = ? AND user_id = ? LIMIT 1",
          [inv.workspace_id, actor.userId],
        )
        if (existingMember.rows.length === 0) {
          yield* tx.execute(
            `INSERT INTO workspace_member (workspace_id, user_id, role, created_at, updated_at)
             VALUES (?, ?, ?, ?, ?)`,
            [inv.workspace_id, actor.userId, inv.role, now, now],
          )
        }
      }),
    )

    return yield* assertWorkspaceAccess(actor, inv.workspace_id, "viewer")
  })
