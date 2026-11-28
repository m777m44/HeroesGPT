import { Context, Effect, Layer } from "effect"
import { createRemoteJWKSet, jwtVerify } from "jose"
import type { WorkspaceRole } from "@radiant/database/schema"
import { pkceS256Challenge, randomToken, randomUserCode, sha256Hex } from "./crypto"
import { Database, parseJsonColumn } from "./db"
import { ConflictError, ForbiddenError, NotFoundError, UnauthorizedError, ValidationError } from "./errors"
import { Id } from "./id"
import { assertWorkspaceAccess, createWorkspace, listWorkspaces, type Actor } from "./workspace"

export interface AuthConfigInterface {
  readonly accountIssuer: string
  readonly accountClientId: string
  readonly sessionSecret: string
}

export class AuthConfig extends Context.Service<AuthConfig, AuthConfigInterface>()(
  "@radiant/core/AuthConfig",
) {}

export const layerAuthConfig = (config: AuthConfigInterface) => Layer.succeed(AuthConfig, config)

const jwksCache = new Map<string, ReturnType<typeof createRemoteJWKSet>>()

const getRemoteJwks = (jwksUri: string) => {
  let set = jwksCache.get(jwksUri)
  if (!set) {
    set = createRemoteJWKSet(new URL(jwksUri))
    jwksCache.set(jwksUri, set)
  }
  return set
}

interface OidcDiscovery {
  readonly issuer: string
  readonly authorization_endpoint: string
  readonly token_endpoint: string
  readonly jwks_uri: string
}

const discoveryCache = new Map<string, { doc: OidcDiscovery; fetchedAt: number }>()

const fetchDiscovery = (issuer: string): Effect.Effect<OidcDiscovery, UnauthorizedError> =>
  Effect.tryPromise({
    try: async () => {
      const cached = discoveryCache.get(issuer)
      if (cached && Date.now() - cached.fetchedAt < 600_000) return cached.doc
      const url = `${issuer.replace(/\/$/, "")}/.well-known/openid-configuration`
      const res = await fetch(url)
      if (!res.ok) throw new Error(`OIDC discovery failed (${res.status})`)
      const doc = (await res.json()) as OidcDiscovery
      discoveryCache.set(issuer, { doc, fetchedAt: Date.now() })
      return doc
    },
    catch: (e) =>
      new UnauthorizedError({
        message: `Failed to reach account issuer: ${e instanceof Error ? e.message : String(e)}`,
      }),
  })

export const upsertOidcUser = (input: {
  readonly issuer: string
  readonly sub: string
  readonly email: string
  readonly name: string | null
}) =>
  Effect.gen(function* () {
    const db = yield* Database
    const existing = yield* db.query<{
      id: string
      email: string
      name: string | null
      disabled_at: string | null
    }>(
      "SELECT id, email, name, disabled_at FROM user WHERE issuer = ? AND external_sub = ? LIMIT 1",
      [input.issuer, input.sub],
    )
    if (existing.rows[0]) {
      if (existing.rows[0].disabled_at) {
        return yield* new ForbiddenError({ message: "Account is disabled" })
      }
      yield* db.execute(
        "UPDATE user SET email = ?, name = ?, updated_at = ? WHERE id = ?",
        [input.email, input.name, new Date(), existing.rows[0].id],
      )
      return { id: existing.rows[0].id, email: input.email, name: input.name }
    }

    const id = Id.user()
    const now = new Date()
    yield* db.execute(
      `INSERT INTO user (id, external_sub, issuer, email, name, created_at, updated_at)
       VALUES (?, ?, ?, ?, ?, ?, ?)`,
      [id, input.sub, input.issuer, input.email, input.name, now, now],
    )
    return { id, email: input.email, name: input.name }
  })

export const startUpstreamOidcFlow = (input: {
  readonly kind: "browser_login" | "mcp_oauth" | "device"
  readonly origin: string
  readonly returnTo?: string
  readonly oauthParams?: {
    readonly clientId: string
    readonly redirectUri: string
    readonly state?: string
    readonly codeChallenge: string
    readonly scope: string
  }
}) =>
  Effect.gen(function* () {
    const cfg = yield* AuthConfig
    const db = yield* Database
    const doc = yield* fetchDiscovery(cfg.accountIssuer)

    const flowId = Id.oauthFlow()
    const verifier = randomToken("", 32)
    const challenge = yield* pkceS256Challenge(verifier)
    const nonce = randomToken("", 16)
    const browserToken = randomToken("rdb_", 24)
    const browserHash = yield* sha256Hex(browserToken)
    const expiresAt = new Date(Date.now() + 600_000)

    yield* db.execute(
      `INSERT INTO oauth_flow
        (id, kind, client_id, redirect_uri, state, code_challenge, code_challenge_method, scope,
         upstream_verifier, upstream_nonce, browser_binding_hash, return_to, expires_at, created_at)
       VALUES (?, ?, ?, ?, ?, ?, 'S256', ?, ?, ?, ?, ?, ?, ?)`,
      [
        flowId,
        input.kind,
        input.oauthParams?.clientId ?? null,
        input.oauthParams?.redirectUri ?? null,
        input.oauthParams?.state ?? null,
        input.oauthParams?.codeChallenge ?? null,
        input.oauthParams?.scope ?? "radiant",
        verifier,
        nonce,
        browserHash,
        input.returnTo ?? "/",
        expiresAt,
        new Date(),
      ],
    )

    const callbackUrl = `${input.origin.replace(/\/$/, "")}/oauth/callback`
    const authorizeUrl = new URL(doc.authorization_endpoint)
    authorizeUrl.searchParams.set("response_type", "code")
    authorizeUrl.searchParams.set("client_id", cfg.accountClientId)
    authorizeUrl.searchParams.set("redirect_uri", callbackUrl)
    authorizeUrl.searchParams.set("scope", "openid email profile")
    authorizeUrl.searchParams.set("state", flowId)
    authorizeUrl.searchParams.set("nonce", nonce)
    authorizeUrl.searchParams.set("code_challenge", challenge)
    authorizeUrl.searchParams.set("code_challenge_method", "S256")

    return { flowId, browserToken, authorizeUrl: authorizeUrl.toString() }
  })

export const completeUpstreamOidcCallback = (input: {
  readonly origin: string
  readonly state: string
  readonly code: string
  readonly iss?: string | null
  readonly browserToken?: string | null
}) =>
  Effect.gen(function* () {
    const cfg = yield* AuthConfig
    const db = yield* Database
    const doc = yield* fetchDiscovery(cfg.accountIssuer)

    if (input.iss && input.iss.replace(/\/$/, "") !== doc.issuer.replace(/\/$/, "")) {
      return yield* new UnauthorizedError({ message: "OIDC issuer mismatch (RFC 9207)" })
    }

    const flowRes = yield* db.query<{
      id: string
      kind: "browser_login" | "mcp_oauth" | "device"
      client_id: string | null
      redirect_uri: string | null
      state: string | null
      code_challenge: string | null
      scope: string | null
      upstream_verifier: string
      upstream_nonce: string
      browser_binding_hash: string | null
      return_to: string | null
      expires_at: string
      consumed_at: string | null
    }>("SELECT * FROM oauth_flow WHERE id = ? LIMIT 1", [input.state])

    const flow = flowRes.rows[0]
    if (!flow || flow.consumed_at || new Date(flow.expires_at).getTime() < Date.now()) {
      return yield* new UnauthorizedError({ message: "Login flow expired or invalid" })
    }
    if (flow.browser_binding_hash) {
      if (!input.browserToken) {
        return yield* new UnauthorizedError({ message: "Missing browser binding cookie" })
      }
      const actualHash = yield* sha256Hex(input.browserToken)
      if (actualHash !== flow.browser_binding_hash) {
        return yield* new UnauthorizedError({ message: "Browser binding mismatch" })
      }
    }

    const callbackUrl = `${input.origin.replace(/\/$/, "")}/oauth/callback`
    const tokenResp = yield* Effect.tryPromise({
      try: async () => {
        const body = new URLSearchParams({
          grant_type: "authorization_code",
          code: input.code,
          redirect_uri: callbackUrl,
          client_id: cfg.accountClientId,
          code_verifier: flow.upstream_verifier,
        })
        const res = await fetch(doc.token_endpoint, {
          method: "POST",
          headers: { "content-type": "application/x-www-form-urlencoded" },
          body: body.toString(),
        })
        if (!res.ok) {
          const text = await res.text()
          throw new Error(`Token exchange failed (${res.status}): ${text}`)
        }
        return (await res.json()) as { id_token?: string }
      },
      catch: (e) =>
        new UnauthorizedError({
          message: e instanceof Error ? e.message : "Failed to exchange OIDC code",
        }),
    })

    if (!tokenResp.id_token) {
      return yield* new UnauthorizedError({ message: "Missing id_token from account service" })
    }

    const claims = yield* Effect.tryPromise({
      try: async () => {
        const { payload } = await jwtVerify(tokenResp.id_token!, getRemoteJwks(doc.jwks_uri), {
          issuer: doc.issuer,
          audience: cfg.accountClientId,
          clockTolerance: 60,
        })
        if (payload.nonce !== flow.upstream_nonce) {
          throw new Error("ID token nonce mismatch")
        }
        if (typeof payload.sub !== "string" || payload.sub.length === 0) {
          throw new Error("Missing sub claim")
        }
        return payload
      },
      catch: (e) =>
        new UnauthorizedError({
          message: `Invalid ID token: ${e instanceof Error ? e.message : String(e)}`,
        }),
    })

    const email =
      typeof claims.email === "string" && claims.email.length > 0
        ? claims.email.toLowerCase()
        : `${claims.sub}@account.anoma.ly`
    const name = typeof claims.name === "string" ? claims.name : null

    const user = yield* upsertOidcUser({
      issuer: doc.issuer,
      sub: claims.sub!,
      email,
      name,
    })

    // Ensure every user has a default workspace immediately on sign-in (for seamless MCP & web onboarding)
    const signInActor: Actor = {
      type: "user",
      userId: user.id,
      email: user.email,
      name: user.name,
      clientName: "Radiant Sign-In",
    }
    const existingWorkspaces = yield* listWorkspaces(signInActor)
    if (existingWorkspaces.length === 0) {
      yield* createWorkspace(signInActor, { name: "Personal", currency: "USD" }).pipe(
        Effect.catch(() => Effect.void),
      )
    }

    yield* db.execute("UPDATE oauth_flow SET consumed_at = ?, approved_user_id = ? WHERE id = ?", [
      new Date(),
      user.id,
      flow.id,
    ])

    return { flow, user }
  })

export const createBrowserSession = (userId: string) =>
  Effect.gen(function* () {
    const db = yield* Database
    const rawToken = randomToken("rds1_", 32)
    const tokenHash = yield* sha256Hex(rawToken)
    const id = Id.session()
    const now = new Date()
    const expiresAt = new Date(now.getTime() + 30 * 86_400_000)
    yield* db.execute(
      `INSERT INTO session (id, user_id, token_hash, expires_at, created_at)
       VALUES (?, ?, ?, ?, ?)`,
      [id, userId, tokenHash, expiresAt, now],
    )
    return { id, token: rawToken, expiresAt }
  })

export const verifyBrowserSession = (rawToken: string): Effect.Effect<Actor | null, import("./errors").DatabaseError, Database> =>
  Effect.gen(function* () {
    if (!rawToken.startsWith("rds1_")) return null
    const db = yield* Database
    const tokenHash = yield* sha256Hex(rawToken)
    const res = yield* db.query<{
      user_id: string
      email: string
      name: string | null
      expires_at: string
      revoked_at: string | null
      disabled_at: string | null
    }>(
      `SELECT s.user_id, u.email, u.name, s.expires_at, s.revoked_at, u.disabled_at
       FROM session s
       INNER JOIN user u ON u.id = s.user_id
       WHERE s.token_hash = ?
       LIMIT 1`,
      [tokenHash],
    )
    const row = res.rows[0]
    if (!row || row.revoked_at || row.disabled_at) return null
    if (new Date(row.expires_at).getTime() < Date.now()) return null
    return {
      type: "user",
      userId: row.user_id,
      email: row.email,
      name: row.name,
      clientName: "Radiant Web",
    }
  })

export const revokeBrowserSession = (rawToken: string) =>
  Effect.gen(function* () {
    const db = yield* Database
    const tokenHash = yield* sha256Hex(rawToken)
    yield* db.execute("UPDATE session SET revoked_at = ? WHERE token_hash = ?", [
      new Date(),
      tokenHash,
    ])
  })

// ── MCP OAuth 2.1 Authorization Server ──────────────────────────────────────

export const registerOAuthClient = (input: {
  readonly client_name?: string
  readonly redirect_uris: ReadonlyArray<string>
}) =>
  Effect.gen(function* () {
    if (!Array.isArray(input.redirect_uris) || input.redirect_uris.length === 0) {
      return yield* new ValidationError({ message: "redirect_uris must be a non-empty array", field: "redirect_uris" })
    }
    for (const uri of input.redirect_uris) {
      try {
        const u = new URL(uri)
        const isLoopback =
          u.hostname === "127.0.0.1" || u.hostname === "localhost" || u.hostname === "[::1]"
        if (u.protocol !== "https:" && !(u.protocol === "http:" && isLoopback)) {
          return yield* new ValidationError({
            message: `Invalid redirect_uri '${uri}': must be https or loopback http`,
            field: "redirect_uris",
          })
        }
      } catch {
        return yield* new ValidationError({ message: `Malformed redirect_uri: ${uri}`, field: "redirect_uris" })
      }
    }
    const id = Id.oauthClient()
    const name = (input.client_name ?? "MCP Client").trim().slice(0, 200) || "MCP Client"
    const db = yield* Database
    yield* db.execute(
      "INSERT INTO oauth_client (id, name, redirect_uris, created_at) VALUES (?, ?, ?, ?)",
      [id, name, JSON.stringify(input.redirect_uris), new Date()],
    )
    return {
      client_id: id,
      client_name: name,
      redirect_uris: input.redirect_uris,
      token_endpoint_auth_method: "none",
      grant_types: ["authorization_code", "refresh_token"],
      response_types: ["code"],
    }
  })

export const getOAuthClient = (clientId: string) =>
  Effect.gen(function* () {
    const db = yield* Database
    const res = yield* db.query<{ id: string; name: string; redirect_uris: unknown }>(
      "SELECT id, name, redirect_uris FROM oauth_client WHERE id = ? LIMIT 1",
      [clientId],
    )
    const row = res.rows[0]
    if (!row) return yield* new NotFoundError({ entity: "oauth_client", id: clientId })
    return {
      id: row.id,
      name: row.name,
      redirect_uris: parseJsonColumn<ReadonlyArray<string>>(row.redirect_uris, []),
    }
  })

export const issueAuthorizationCode = (input: {
  readonly clientId: string
  readonly userId: string
  readonly redirectUri: string
  readonly codeChallenge: string
  readonly scope: string
}) =>
  Effect.gen(function* () {
    const db = yield* Database
    const rawCode = randomToken("rdc1_", 24)
    const codeHash = yield* sha256Hex(rawCode)
    const expiresAt = new Date(Date.now() + 120_000)
    yield* db.execute(
      `INSERT INTO oauth_code (code_hash, client_id, user_id, redirect_uri, code_challenge, scope, expires_at, created_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
      [codeHash, input.clientId, input.userId, input.redirectUri, input.codeChallenge, input.scope, expiresAt, new Date()],
    )
    return rawCode
  })

const mintGrant = (input: {
  readonly clientId: string
  readonly clientName: string
  readonly userId: string
  readonly scope: string
}) =>
  Effect.gen(function* () {
    const db = yield* Database
    const grantId = Id.grant()
    const accessToken = randomToken(`rdm1.${grantId}.`, 24)
    const refreshToken = randomToken(`rdr1.${grantId}.`, 32)
    const accessHash = yield* sha256Hex(accessToken)
    const refreshHash = yield* sha256Hex(refreshToken)
    const now = new Date()
    const accessExpiresAt = new Date(now.getTime() + 3_600_000)
    const refreshExpiresAt = new Date(now.getTime() + 30 * 86_400_000)

    yield* db.execute(
      `INSERT INTO oauth_grant
        (id, client_id, client_name, user_id, scope, access_token_hash, access_expires_at,
         refresh_token_hash, refresh_expires_at, created_at, updated_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
      [
        grantId,
        input.clientId,
        input.clientName,
        input.userId,
        input.scope,
        accessHash,
        accessExpiresAt,
        refreshHash,
        refreshExpiresAt,
        now,
        now,
      ],
    )

    return {
      access_token: accessToken,
      token_type: "Bearer" as const,
      expires_in: 3600,
      refresh_token: refreshToken,
      scope: input.scope,
      client_id: input.clientId,
    }
  })

export const exchangeAuthorizationCode = (input: {
  readonly code: string
  readonly clientId: string
  readonly redirectUri: string
  readonly codeVerifier: string
}) =>
  Effect.gen(function* () {
    const db = yield* Database
    const codeHash = yield* sha256Hex(input.code)
    const res = yield* db.query<{
      client_id: string
      user_id: string
      redirect_uri: string
      code_challenge: string
      scope: string
      expires_at: string
      consumed_at: string | null
    }>("SELECT * FROM oauth_code WHERE code_hash = ? LIMIT 1", [codeHash])

    const row = res.rows[0]
    if (!row || row.consumed_at || new Date(row.expires_at).getTime() < Date.now()) {
      return yield* new UnauthorizedError({ message: "Authorization code is invalid or expired" })
    }
    if (row.client_id !== input.clientId || row.redirect_uri !== input.redirectUri) {
      return yield* new UnauthorizedError({ message: "Client or redirect_uri mismatch" })
    }
    const expectedChallenge = yield* pkceS256Challenge(input.codeVerifier)
    if (expectedChallenge !== row.code_challenge) {
      return yield* new UnauthorizedError({ message: "Invalid PKCE code_verifier" })
    }

    const updated = yield* db.execute(
      "UPDATE oauth_code SET consumed_at = ? WHERE code_hash = ? AND consumed_at IS NULL",
      [new Date(), codeHash],
    )
    if (updated.rowsAffected === 0) {
      return yield* new UnauthorizedError({ message: "Authorization code already used" })
    }

    const client = yield* getOAuthClient(row.client_id)
    return yield* mintGrant({
      clientId: client.id,
      clientName: client.name,
      userId: row.user_id,
      scope: row.scope,
    })
  })

export const refreshOAuthGrant = (input: {
  readonly refreshToken: string
  readonly clientId: string
}) =>
  Effect.gen(function* () {
    const db = yield* Database
    const hash = yield* sha256Hex(input.refreshToken)

    // Detect refresh token reuse -> revoke entire grant immediately
    const reused = yield* db.query<{ id: string }>(
      "SELECT id FROM oauth_grant WHERE previous_refresh_hash = ? LIMIT 1",
      [hash],
    )
    if (reused.rows[0]) {
      yield* db.execute("UPDATE oauth_grant SET revoked_at = ? WHERE id = ?", [
        new Date(),
        reused.rows[0].id,
      ])
      return yield* new UnauthorizedError({ message: "Refresh token reuse detected; grant revoked" })
    }

    const res = yield* db.query<{
      id: string
      client_id: string
      client_name: string
      user_id: string
      scope: string
      refresh_expires_at: string
      revoked_at: string | null
    }>("SELECT * FROM oauth_grant WHERE refresh_token_hash = ? LIMIT 1", [hash])

    const grant = res.rows[0]
    if (!grant || grant.revoked_at || grant.client_id !== input.clientId) {
      return yield* new UnauthorizedError({ message: "Invalid refresh token" })
    }
    if (new Date(grant.refresh_expires_at).getTime() < Date.now()) {
      return yield* new UnauthorizedError({ message: "Refresh token expired" })
    }

    const userRes = yield* db.query<{ disabled_at: string | null }>(
      "SELECT disabled_at FROM user WHERE id = ? LIMIT 1",
      [grant.user_id],
    )
    if (!userRes.rows[0] || userRes.rows[0].disabled_at) {
      return yield* new UnauthorizedError({ message: "User disabled" })
    }

    const nextAccess = randomToken(`rdm1.${grant.id}.`, 24)
    const nextRefresh = randomToken(`rdr1.${grant.id}.`, 32)
    const nextAccessHash = yield* sha256Hex(nextAccess)
    const nextRefreshHash = yield* sha256Hex(nextRefresh)
    const now = new Date()
    const nextAccessExp = new Date(now.getTime() + 3_600_000)

    yield* db.execute(
      `UPDATE oauth_grant
       SET access_token_hash = ?, access_expires_at = ?,
           previous_refresh_hash = ?, refresh_token_hash = ?, updated_at = ?
       WHERE id = ? AND refresh_token_hash = ?`,
      [nextAccessHash, nextAccessExp, hash, nextRefreshHash, now, grant.id, hash],
    )

    return {
      access_token: nextAccess,
      token_type: "Bearer" as const,
      expires_in: 3600,
      refresh_token: nextRefresh,
      scope: grant.scope,
      client_id: grant.client_id,
    }
  })

export const revokeOAuthToken = (rawToken: string) =>
  Effect.gen(function* () {
    const db = yield* Database
    const hash = yield* sha256Hex(rawToken)
    yield* db.execute(
      `UPDATE oauth_grant SET revoked_at = ?
       WHERE access_token_hash = ? OR refresh_token_hash = ?`,
      [new Date(), hash, hash],
    )
  })

export const verifyBearerToken = (rawToken: string): Effect.Effect<Actor | null, import("./errors").DatabaseError, Database> =>
  Effect.gen(function* () {
    const db = yield* Database
    const hash = yield* sha256Hex(rawToken)

    if (rawToken.startsWith("rdm1.")) {
      const res = yield* db.query<{
        user_id: string
        email: string
        name: string | null
        client_name: string
        access_expires_at: string
        revoked_at: string | null
        disabled_at: string | null
      }>(
        `SELECT g.user_id, u.email, u.name, g.client_name, g.access_expires_at, g.revoked_at, u.disabled_at
         FROM oauth_grant g
         INNER JOIN user u ON u.id = g.user_id
         WHERE g.access_token_hash = ?
         LIMIT 1`,
        [hash],
      )
      const row = res.rows[0]
      if (!row || row.revoked_at || row.disabled_at) return null
      if (new Date(row.access_expires_at).getTime() < Date.now()) return null
      return {
        type: "agent",
        userId: row.user_id,
        email: row.email,
        name: row.name,
        clientName: row.client_name,
      }
    }

    if (rawToken.startsWith("rdt1_")) {
      const res = yield* db.query<{
        id: string
        workspace_id: string
        user_id: string
        name: string
        role: WorkspaceRole
        email: string
        user_name: string | null
        expires_at: string | null
        revoked_at: string | null
        disabled_at: string | null
      }>(
        `SELECT t.id, t.workspace_id, t.user_id, t.name, t.role, u.email, u.name AS user_name,
                t.expires_at, t.revoked_at, u.disabled_at
         FROM api_token t
         INNER JOIN user u ON u.id = t.user_id
         WHERE t.token_hash = ?
         LIMIT 1`,
        [hash],
      )
      const row = res.rows[0]
      if (!row || row.revoked_at || row.disabled_at) return null
      if (row.expires_at && new Date(row.expires_at).getTime() < Date.now()) return null
      yield* db.execute("UPDATE api_token SET last_used_at = ? WHERE id = ?", [new Date(), row.id])
      return {
        type: "agent",
        userId: row.user_id,
        email: row.email,
        name: row.user_name,
        clientName: `API Token: ${row.name}`,
        scopedWorkspaceId: row.workspace_id,
        scopedRole: row.role,
      }
    }

    return null
  })

// ── Device Authorization Grant (RFC 8628) ───────────────────────────────────

export const startDeviceFlow = (clientName: string, origin: string) =>
  Effect.gen(function* () {
    const db = yield* Database
    const id = Id.device()
    const rawDeviceCode = randomToken("rdd1.", 28)
    const deviceHash = yield* sha256Hex(rawDeviceCode)
    const userCode = randomUserCode()
    const now = new Date()
    const expiresAt = new Date(now.getTime() + 600_000)

    yield* db.execute(
      `INSERT INTO device_code (id, device_code_hash, user_code, client_name, status, interval_seconds, expires_at, created_at)
       VALUES (?, ?, ?, ?, 'pending', 5, ?, ?)`,
      [id, deviceHash, userCode, clientName.trim().slice(0, 100) || "An agent", expiresAt, now],
    )

    const base = origin.replace(/\/$/, "")
    return {
      device_code: rawDeviceCode,
      user_code: userCode,
      verification_uri: `${base}/device`,
      verification_uri_complete: `${base}/device?code=${encodeURIComponent(userCode)}`,
      expires_in: 600,
      interval: 5,
    }
  })

export const lookupDeviceFlow = (userCode: string) =>
  Effect.gen(function* () {
    const clean = userCode.trim().toUpperCase()
    if (!clean) return null
    const db = yield* Database
    const res = yield* db.query<{
      user_code: string
      client_name: string
      status: string
      expires_at: string
    }>(
      "SELECT user_code, client_name, status, expires_at FROM device_code WHERE user_code = ? LIMIT 1",
      [clean],
    )
    const row = res.rows[0]
    if (!row || row.status !== "pending" || new Date(row.expires_at).getTime() < Date.now()) return null
    return { user_code: row.user_code, client_name: row.client_name }
  })

export const decideDeviceFlow = (userCode: string, userId: string, approve: boolean) =>
  Effect.gen(function* () {
    const db = yield* Database
    const clean = userCode.trim().toUpperCase()
    const res = yield* db.execute(
      `UPDATE device_code SET status = ?, user_id = ?
       WHERE user_code = ? AND status = 'pending' AND expires_at > ?`,
      [approve ? "approved" : "denied", userId, clean, new Date()],
    )
    if (res.rowsAffected === 0) {
      return yield* new NotFoundError({ entity: "device_code", message: "Device code invalid or expired" })
    }
    return { user_code: clean, status: approve ? "approved" : "denied" }
  })

export const pollDeviceFlow = (rawDeviceCode: string) =>
  Effect.gen(function* () {
    const db = yield* Database
    const hash = yield* sha256Hex(rawDeviceCode)
    const res = yield* db.query<{
      id: string
      client_name: string
      status: string
      user_id: string | null
      expires_at: string
    }>("SELECT id, client_name, status, user_id, expires_at FROM device_code WHERE device_code_hash = ? LIMIT 1", [
      hash,
    ])
    const row = res.rows[0]
    if (!row) return { error: "invalid_grant" as const }
    if (new Date(row.expires_at).getTime() < Date.now()) return { error: "expired_token" as const }
    if (row.status === "pending") return { error: "authorization_pending" as const }
    if (row.status === "denied") return { error: "access_denied" as const }
    if (row.status === "consumed" || !row.user_id) return { error: "invalid_grant" as const }

    const updated = yield* db.execute(
      "UPDATE device_code SET status = 'consumed' WHERE id = ? AND status = 'approved'",
      [row.id],
    )
    if (updated.rowsAffected === 0) return { error: "invalid_grant" as const }

    const tokens = yield* mintGrant({
      clientId: "device_flow",
      clientName: row.client_name,
      userId: row.user_id,
      scope: "radiant",
    })
    return { ok: true as const, tokens }
  })

// ── Workspace API Tokens ────────────────────────────────────────────────────

export const createApiToken = (
  actor: Actor,
  workspaceId: string,
  input: { readonly name: string; readonly role?: WorkspaceRole; readonly expiresInDays?: number },
) =>
  Effect.gen(function* () {
    const ws = yield* assertWorkspaceAccess(actor, workspaceId, "admin")
    const name = input.name.trim()
    if (name.length < 1 || name.length > 120) {
      return yield* new ValidationError({ message: "Token name must be 1..120 characters", field: "name" })
    }
    const role: WorkspaceRole = input.role ?? "member"
    if (role === "owner" && ws.role !== "owner") {
      return yield* new ForbiddenError({ message: "Only an owner can mint an owner-scoped token" })
    }
    const rawToken = randomToken("rdt1_", 32)
    const tokenHash = yield* sha256Hex(rawToken)
    const id = Id.apiToken()
    const now = new Date()
    const expiresAt = input.expiresInDays
      ? new Date(now.getTime() + Math.max(1, Math.min(input.expiresInDays, 365)) * 86_400_000)
      : null

    const db = yield* Database
    yield* db.execute(
      `INSERT INTO api_token (id, workspace_id, user_id, name, role, token_hash, expires_at, created_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
      [id, ws.id, actor.userId, name, role, tokenHash, expiresAt, now],
    )
    return {
      id,
      workspace_id: ws.id,
      name,
      role,
      token: rawToken,
      expires_at: expiresAt?.toISOString() ?? null,
    }
  })

export const listApiTokens = (actor: Actor, workspaceId: string) =>
  Effect.gen(function* () {
    const ws = yield* assertWorkspaceAccess(actor, workspaceId, "admin")
    const db = yield* Database
    const res = yield* db.query<{
      id: string
      name: string
      role: WorkspaceRole
      last_used_at: string | null
      expires_at: string | null
      revoked_at: string | null
      created_at: string
    }>(
      `SELECT id, name, role, last_used_at, expires_at, revoked_at, created_at
       FROM api_token
       WHERE workspace_id = ?
       ORDER BY created_at DESC`,
      [ws.id],
    )
    return res.rows
  })

export const revokeApiToken = (actor: Actor, workspaceId: string, tokenId: string) =>
  Effect.gen(function* () {
    const ws = yield* assertWorkspaceAccess(actor, workspaceId, "admin")
    const db = yield* Database
    const res = yield* db.execute(
      "UPDATE api_token SET revoked_at = ? WHERE workspace_id = ? AND id = ? AND revoked_at IS NULL",
      [new Date(), ws.id, tokenId],
    )
    if (res.rowsAffected === 0) {
      return yield* new NotFoundError({ entity: "api_token", id: tokenId })
    }
    return { id: tokenId, revoked: true }
  })
