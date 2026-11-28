import { Effect } from "effect"
import {
  acceptInvite,
  aggregateTransactions,
  applyOverlayByIdsOrFilter,
  assertWorkspaceAccess,
  balancesHistory,
  balancesSummary,
  clearTransactionSplits,
  createApiToken,
  createConnectHandoffLink,
  createInvite,
  createManualTransaction,
  createPlaidLinkToken,
  createRule,
  createWorkspace,
  deleteRule,
  deleteWorkspace,
  exchangePublicToken,
  executeWorkspaceSql,
  getOverlayBatch,
  getTransactionDetail,
  getWorkspaceSqlSchema,
  listAccounts,
  listApiTokens,
  listInvites,
  listMembers,
  listOverlayBatches,
  listPlaidItems,
  listRules,
  listSyncRuns,
  listWorkspaces,
  previewRule,
  queryTransactions,
  redoOverlayBatch,
  removeMember,
  removePlaidItem,
  reorderRules,
  resetTransactions,
  resolveConnectHandoffToken,
  resolvePlaidWebhookJob,
  revokeApiToken,
  revokeInvite,
  setAccountOverlay,
  setTransactionSplits,
  syncItemInternal,
  triggerPlaidSync,
  undoOverlayBatch,
  updateMemberRole,
  updateRule,
  updateWorkspace,
  verifyBearerToken,
  verifyPlaidWebhook,
  type Actor,
  type AggregateInput,
  type SplitLineInput,
  type SqlParam,
  type TransactionFilter,
  type TransactionQueryInput,
} from "@radiant/core"
import type { TxPatch, WorkspaceRole } from "@radiant/database/schema"
import { markdownResponse, prefersMarkdown, renderAgentMarkdown } from "./agent-doc"
import { htmlResponse, jsonResponse, type AppServices, type Env, type RouteContext } from "./env"
import { resolveBrowserActor } from "./oauth-routes"
import {
  renderConnectHandoffPage,
  renderEmptyWorkspacesPage,
  renderLandingPage,
  renderWorkspaceDashboard,
} from "./ui"

const resolveApiActor = (
  request: Request,
): Effect.Effect<Actor | null, import("@radiant/core").DatabaseError, AppServices> =>
  Effect.gen(function* () {
    const authHeader = request.headers.get("authorization") ?? ""
    if (authHeader.startsWith("Bearer ")) {
      const token = authHeader.slice(7).trim()
      if (token) return yield* verifyBearerToken(token)
    }
    return yield* resolveBrowserActor(request)
  })

const readJsonBody = (request: Request): Effect.Effect<Record<string, unknown>, never> =>
  Effect.promise(() =>
    request
      .json()
      .then((d) => (d && typeof d === "object" ? (d as Record<string, unknown>) : {}))
      .catch(() => ({})),
  )

export const handleAppRoutes = (
  request: Request,
  route: RouteContext,
  env: Env,
): Effect.Effect<Response, unknown, AppServices> =>
  Effect.gen(function* () {
    const { url, path, basePath, baseUrl } = route
    const method = request.method

    // Health check (does not touch DB)
    if (method === "GET" && path === "/health") {
      return jsonResponse({ ok: true, service: "radiant", version: "0.1.0", stage: env.STAGE })
    }

    // Plaid Webhook Receiver
    if (method === "POST" && path === "/webhooks/plaid") {
      const rawBody = yield* Effect.promise(() => request.text())
      const payload = yield* verifyPlaidWebhook(rawBody, request.headers.get("plaid-verification"))
      const job = yield* resolvePlaidWebhookJob(payload)
      if (job.action === "sync") {
        if (env.PLAID_SYNC_QUEUE) {
          yield* Effect.promise(() =>
            env.PLAID_SYNC_QUEUE!.send({
              workspaceId: job.workspaceId,
              itemId: job.itemId,
              trigger: "webhook",
            }),
          )
        } else {
          yield* syncItemInternal(job.workspaceId, job.itemId, "webhook")
        }
      }
      return jsonResponse({ received: true, action: job.action })
    }

    // ── Agent-First Markdown & Minimal SSR Web UI Routes ────────────────────

    if (method === "GET" && (path === "/index.md" || path === "/llms.txt")) {
      return markdownResponse(renderAgentMarkdown(baseUrl))
    }

    if (method === "GET" && path === "/") {
      if (prefersMarkdown(request.headers.get("accept"))) {
        return markdownResponse(renderAgentMarkdown(baseUrl))
      }
      const actor = yield* resolveBrowserActor(request)
      if (!actor) return htmlResponse(renderLandingPage(baseUrl, basePath), 200, { vary: "Accept" })
      const workspaces = yield* listWorkspaces(actor)
      if (workspaces.length === 0) return htmlResponse(renderEmptyWorkspacesPage(actor.email, basePath), 200, { vary: "Accept" })
      return Response.redirect(`${baseUrl}/w/${workspaces[0]!.slug}`, 302)
    }

    if (method === "POST" && path === "/ui/workspaces") {
      const actor = yield* resolveBrowserActor(request)
      if (!actor) return Response.redirect(`${baseUrl}/auth/login`, 302)
      const form = yield* Effect.promise(async () => new URLSearchParams(await request.text()))
      const created = yield* createWorkspace(actor, {
        name: form.get("name") ?? "Personal",
        currency: form.get("currency") ?? "USD",
      })
      return Response.redirect(`${baseUrl}/w/${created.slug}`, 302)
    }

    if (method === "GET" && path.startsWith("/w/")) {
      const slug = decodeURIComponent(path.slice(3).split("/")[0] ?? "")
      const actor = yield* resolveBrowserActor(request)
      if (!actor) {
        return Response.redirect(`${baseUrl}/auth/login?return_to=${encodeURIComponent(url.pathname)}`, 302)
      }
      const workspaces = yield* listWorkspaces(actor)
      const ws = yield* assertWorkspaceAccess(actor, slug, "viewer")
      const [items, accounts, members, batches] = yield* Effect.all([
        listPlaidItems(actor, ws.id),
        listAccounts(actor, ws.id, { include_inactive: true }),
        listMembers(actor, ws.id),
        listOverlayBatches(actor, ws.id, { limit: 25 }),
      ])
      const invites =
        ws.role === "owner" || ws.role === "admin"
          ? yield* listInvites(actor, ws.id)
          : []
      return htmlResponse(
        renderWorkspaceDashboard({
          baseUrl,
          basePath,
          email: actor.email,
          workspace: ws,
          workspaces,
          items,
          accounts,
          members,
          invites,
          batches,
          flash: url.searchParams.get("flash"),
        }),
      )
    }

    // MCP-generated Plaid Link handoff page
    if (method === "GET" && path.startsWith("/connect/")) {
      const rawToken = decodeURIComponent(path.slice("/connect/".length))
      const actor = yield* resolveBrowserActor(request)
      if (!actor) {
        return Response.redirect(`${baseUrl}/auth/login?return_to=${encodeURIComponent(url.pathname)}`, 302)
      }
      const handoff = yield* resolveConnectHandoffToken(rawToken)
      const ws = yield* assertWorkspaceAccess(actor, handoff.workspace_id, "admin")
      return htmlResponse(
        renderConnectHandoffPage({
          basePath,
          workspaceId: ws.id,
          workspaceName: ws.name,
          workspaceSlug: ws.slug,
          connectToken: rawToken,
          mode: handoff.mode,
          itemId: handoff.item_id,
        }),
      )
    }

    // Invite acceptance page
    if (method === "GET" && path.startsWith("/invite/")) {
      const rawToken = decodeURIComponent(path.slice("/invite/".length))
      const actor = yield* resolveBrowserActor(request)
      if (!actor) {
        return Response.redirect(`${baseUrl}/auth/login?return_to=${encodeURIComponent(url.pathname)}`, 302)
      }
      const ws = yield* acceptInvite(actor, rawToken)
      return Response.redirect(`${baseUrl}/w/${ws.slug}?flash=${encodeURIComponent(`Joined ${ws.name}`)}`, 302)
    }

    // ── JSON REST API (/api/v1/*) ───────────────────────────────────────────

    if (!path.startsWith("/api/v1/")) {
      return jsonResponse({ error: "not_found" }, 404)
    }

    const actor = yield* resolveApiActor(request)
    if (!actor) {
      return jsonResponse({ error: "unauthorized" }, 401)
    }

    if (method === "GET" && path === "/api/v1/me") {
      const workspaces = yield* listWorkspaces(actor)
      return jsonResponse({ user: { id: actor.userId, email: actor.email, name: actor.name }, workspaces })
    }

    if (path === "/api/v1/workspaces") {
      if (method === "GET") return jsonResponse({ workspaces: yield* listWorkspaces(actor) })
      if (method === "POST") {
        const body = yield* readJsonBody(request)
        return jsonResponse(
          yield* createWorkspace(actor, {
            name: String(body.name ?? ""),
            slug: typeof body.slug === "string" ? body.slug : undefined,
            currency: typeof body.currency === "string" ? body.currency : undefined,
          }),
          201,
        )
      }
    }

    if (method === "POST" && path === "/api/v1/invites/accept") {
      const body = yield* readJsonBody(request)
      return jsonResponse(yield* acceptInvite(actor, String(body.invite_token ?? "")))
    }

    // Workspace-scoped routes: /api/v1/workspaces/:ws/...
    const wsMatch = /^\/api\/v1\/workspaces\/([^/]+)(\/.*)?$/.exec(path)
    if (!wsMatch) return jsonResponse({ error: "not_found" }, 404)

    const wsParam = decodeURIComponent(wsMatch[1]!)
    const sub = wsMatch[2] ?? ""

    if (sub === "" || sub === "/") {
      if (method === "GET") return jsonResponse(yield* assertWorkspaceAccess(actor, wsParam, "viewer"))
      if (method === "PATCH") {
        const body = yield* readJsonBody(request)
        return jsonResponse(
          yield* updateWorkspace(actor, wsParam, {
            name: typeof body.name === "string" ? body.name : undefined,
            currency: typeof body.currency === "string" ? body.currency : undefined,
          }),
        )
      }
      if (method === "DELETE") return jsonResponse(yield* deleteWorkspace(actor, wsParam))
    }

    if (sub === "/members" && method === "GET") {
      return jsonResponse({ members: yield* listMembers(actor, wsParam) })
    }
    const memberMatch = /^\/members\/([^/]+)$/.exec(sub)
    if (memberMatch) {
      const uid = decodeURIComponent(memberMatch[1]!)
      if (method === "PATCH") {
        const body = yield* readJsonBody(request)
        return jsonResponse(yield* updateMemberRole(actor, wsParam, uid, body.role as WorkspaceRole))
      }
      if (method === "DELETE") return jsonResponse(yield* removeMember(actor, wsParam, uid))
    }

    if (sub === "/invites") {
      if (method === "GET") return jsonResponse({ invites: yield* listInvites(actor, wsParam) })
      if (method === "POST") {
        const body = yield* readJsonBody(request)
        return jsonResponse(
          yield* createInvite(
            actor,
            wsParam,
            {
              email: String(body.email ?? ""),
              role: body.role as WorkspaceRole | undefined,
              expiresInDays: typeof body.expires_in_days === "number" ? body.expires_in_days : undefined,
            },
            baseUrl,
          ),
          201,
        )
      }
    }
    const invMatch = /^\/invites\/([^/]+)$/.exec(sub)
    if (invMatch && method === "DELETE") {
      return jsonResponse(yield* revokeInvite(actor, wsParam, decodeURIComponent(invMatch[1]!)))
    }

    if (sub === "/tokens") {
      if (method === "GET") return jsonResponse({ tokens: yield* listApiTokens(actor, wsParam) })
      if (method === "POST") {
        const body = yield* readJsonBody(request)
        return jsonResponse(
          yield* createApiToken(actor, wsParam, {
            name: String(body.name ?? ""),
            role: body.role as WorkspaceRole | undefined,
            expiresInDays: typeof body.expires_in_days === "number" ? body.expires_in_days : undefined,
          }),
          201,
        )
      }
    }
    const tokMatch = /^\/tokens\/([^/]+)$/.exec(sub)
    if (tokMatch && method === "DELETE") {
      return jsonResponse(yield* revokeApiToken(actor, wsParam, decodeURIComponent(tokMatch[1]!)))
    }

    // Plaid routes
    if (sub === "/plaid/connect-link" && method === "POST") {
      const body = yield* readJsonBody(request)
      return jsonResponse(
        yield* createConnectHandoffLink(
          actor,
          wsParam,
          {
            mode: body.mode === "update" ? "update" : "new",
            item_id: typeof body.item_id === "string" ? body.item_id : undefined,
          },
          baseUrl,
        ),
      )
    }
    if (sub === "/plaid/link-token" && method === "POST") {
      const body = yield* readJsonBody(request)
      return jsonResponse(
        yield* createPlaidLinkToken(actor, wsParam, {
          mode: body.mode === "update" ? "update" : "new",
          item_id: typeof body.item_id === "string" ? body.item_id : undefined,
          webhookUrl: `${baseUrl}/webhooks/plaid`,
        }),
      )
    }
    if (sub === "/plaid/exchange" && method === "POST") {
      const body = yield* readJsonBody(request)
      return jsonResponse(
        yield* exchangePublicToken(actor, wsParam, {
          public_token: String(body.public_token ?? ""),
          connect_token: typeof body.connect_token === "string" ? body.connect_token : undefined,
        }),
      )
    }
    if (sub === "/plaid/sync" && method === "POST") {
      const body = yield* readJsonBody(request)
      return jsonResponse(
        yield* triggerPlaidSync(actor, wsParam, {
          item_id: typeof body.item_id === "string" ? body.item_id : undefined,
          force_refresh: Boolean(body.force_refresh),
        }),
      )
    }
    if (sub === "/plaid/items" && method === "GET") {
      return jsonResponse({ items: yield* listPlaidItems(actor, wsParam) })
    }
    const itemMatch = /^\/plaid\/items\/([^/]+)$/.exec(sub)
    if (itemMatch && method === "DELETE") {
      return jsonResponse(yield* removePlaidItem(actor, wsParam, decodeURIComponent(itemMatch[1]!)))
    }
    if (sub === "/plaid/sync-runs" && method === "GET") {
      return jsonResponse({ runs: yield* listSyncRuns(actor, wsParam) })
    }

    // Accounts & Balances
    if (sub === "/accounts" && method === "GET") {
      const includeInactive = url.searchParams.get("include_inactive") === "1" || url.searchParams.get("include_hidden") === "1"
      return jsonResponse({ accounts: yield* listAccounts(actor, wsParam, { include_inactive: includeInactive }) })
    }
    const accOvMatch = /^\/accounts\/([^/]+)\/overlay$/.exec(sub)
    if (accOvMatch && method === "POST") {
      const body = yield* readJsonBody(request)
      return jsonResponse(
        yield* setAccountOverlay(actor, wsParam, {
          account_id: decodeURIComponent(accOvMatch[1]!),
          ...(body as Record<string, unknown>),
        }),
      )
    }
    if (sub === "/balances" && method === "GET") {
      return jsonResponse(yield* balancesSummary(actor, wsParam))
    }
    if (sub === "/balances/history" && method === "GET") {
      return jsonResponse(
        yield* balancesHistory(actor, wsParam, {
          date_from: url.searchParams.get("date_from") ?? undefined,
          date_to: url.searchParams.get("date_to") ?? undefined,
          bucket: (url.searchParams.get("bucket") as "day" | "week" | "month" | null) ?? undefined,
        }),
      )
    }

    // Transactions, Overlays, Splits, Manual, Query, Aggregate, SQL
    if (sub === "/transactions/query" && method === "POST") {
      const body = yield* readJsonBody(request)
      return jsonResponse(yield* queryTransactions(actor, wsParam, body as TransactionQueryInput))
    }
    if (sub === "/transactions/aggregate" && method === "POST") {
      const body = yield* readJsonBody(request)
      return jsonResponse(yield* aggregateTransactions(actor, wsParam, body as AggregateInput))
    }
    if (sub === "/transactions/overlay" && method === "POST") {
      const body = yield* readJsonBody(request)
      return jsonResponse(
        yield* applyOverlayByIdsOrFilter(actor, wsParam, {
          tx_ids: Array.isArray(body.tx_ids) ? (body.tx_ids as ReadonlyArray<string>) : undefined,
          filter: body.filter as TransactionFilter | undefined,
          patch: (body.patch ?? {}) as TxPatch,
          reason: typeof body.reason === "string" ? body.reason : undefined,
          dry_run: Boolean(body.dry_run),
        }),
      )
    }
    if (sub === "/transactions/manual" && method === "POST") {
      const body = yield* readJsonBody(request)
      return jsonResponse(
        yield* createManualTransaction(actor, wsParam, body as Parameters<typeof createManualTransaction>[2]),
        201,
      )
    }
    if (sub === "/transactions/reset" && method === "POST") {
      const body = yield* readJsonBody(request)
      return jsonResponse(
        yield* resetTransactions(
          actor,
          wsParam,
          Array.isArray(body.tx_ids) ? (body.tx_ids as ReadonlyArray<string>) : [],
          typeof body.reason === "string" ? body.reason : undefined,
        ),
      )
    }
    const txMatch = /^\/transactions\/([^/]+)$/.exec(sub)
    if (txMatch && method === "GET") {
      return jsonResponse(yield* getTransactionDetail(actor, wsParam, decodeURIComponent(txMatch[1]!)))
    }
    const txSplitMatch = /^\/transactions\/([^/]+)\/splits$/.exec(sub)
    if (txSplitMatch) {
      const txId = decodeURIComponent(txSplitMatch[1]!)
      if (method === "PUT") {
        const body = yield* readJsonBody(request)
        return jsonResponse(
          yield* setTransactionSplits(actor, wsParam, {
            tx_id: txId,
            splits: Array.isArray(body.splits) ? (body.splits as ReadonlyArray<SplitLineInput>) : [],
            reason: typeof body.reason === "string" ? body.reason : undefined,
          }),
        )
      }
      if (method === "DELETE") {
        return jsonResponse(yield* clearTransactionSplits(actor, wsParam, txId))
      }
    }

    // Rules
    if (sub === "/rules") {
      if (method === "GET") return jsonResponse({ rules: yield* listRules(actor, wsParam) })
      if (method === "POST") {
        const body = yield* readJsonBody(request)
        return jsonResponse(
          yield* createRule(actor, wsParam, body as Parameters<typeof createRule>[2]),
          201,
        )
      }
    }
    if (sub === "/rules/preview" && method === "POST") {
      const body = yield* readJsonBody(request)
      return jsonResponse(yield* previewRule(actor, wsParam, body as Parameters<typeof previewRule>[2]))
    }
    if (sub === "/rules/reorder" && method === "POST") {
      const body = yield* readJsonBody(request)
      return jsonResponse(
        yield* reorderRules(
          actor,
          wsParam,
          Array.isArray(body.rule_ids) ? (body.rule_ids as ReadonlyArray<string>) : [],
          typeof body.reason === "string" ? body.reason : undefined,
        ),
      )
    }
    const ruleMatch = /^\/rules\/([^/]+)$/.exec(sub)
    if (ruleMatch) {
      const ruleId = decodeURIComponent(ruleMatch[1]!)
      if (method === "PATCH") {
        const body = yield* readJsonBody(request)
        return jsonResponse(yield* updateRule(actor, wsParam, ruleId, body as Parameters<typeof updateRule>[3]))
      }
      if (method === "DELETE") return jsonResponse(yield* deleteRule(actor, wsParam, ruleId))
    }

    // Overlay Batches & Undo/Redo
    if (sub === "/overlays/batches" && method === "GET") {
      return jsonResponse({ batches: yield* listOverlayBatches(actor, wsParam) })
    }
    const batchMatch = /^\/overlays\/batches\/([^/]+)$/.exec(sub)
    if (batchMatch && method === "GET") {
      return jsonResponse(yield* getOverlayBatch(actor, wsParam, decodeURIComponent(batchMatch[1]!)))
    }
    const batchActionMatch = /^\/overlays\/batches\/([^/]+)\/(undo|redo)$/.exec(sub)
    if (batchActionMatch && method === "POST") {
      const batchId = decodeURIComponent(batchActionMatch[1]!)
      return batchActionMatch[2] === "undo"
        ? jsonResponse(yield* undoOverlayBatch(actor, wsParam, batchId))
        : jsonResponse(yield* redoOverlayBatch(actor, wsParam, batchId))
    }

    // Read-only SQL
    if (sub === "/sql/schema" && method === "GET") {
      return jsonResponse(yield* getWorkspaceSqlSchema(actor, wsParam))
    }
    if (sub === "/sql/query" && method === "POST") {
      const body = yield* readJsonBody(request)
      return jsonResponse(
        yield* executeWorkspaceSql(actor, wsParam, {
          sql: String(body.sql ?? ""),
          params: Array.isArray(body.params) ? (body.params as ReadonlyArray<SqlParam>) : undefined,
          limit: typeof body.limit === "number" ? body.limit : undefined,
        }),
      )
    }

    return jsonResponse({ error: "not_found" }, 404)
  })
