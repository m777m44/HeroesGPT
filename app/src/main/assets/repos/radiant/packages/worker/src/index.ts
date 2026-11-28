import { Cause, Effect } from "effect"
import { listAllActiveItemsForCron, syncItemInternal } from "@radiant/core"
import { handleAppRoutes } from "./api"
import { buildAppLayer, buildRouteContext, jsonResponse, type Env, type SyncQueueMessage } from "./env"
import { handleMcpRequest } from "./mcp"
import { handleOAuthRoutes } from "./oauth-routes"

const errorToResponse = (err: unknown): Response => {
  if (err && typeof err === "object" && "_tag" in err) {
    const rec = err as { _tag: string; message?: string; entity?: string; code?: string }
    switch (rec._tag) {
      case "UnauthorizedError":
        return jsonResponse({ error: "unauthorized", message: rec.message }, 401)
      case "ForbiddenError":
        return jsonResponse({ error: "forbidden", message: rec.message }, 403)
      case "NotFoundError":
        return jsonResponse({ error: "not_found", message: rec.message ?? `${rec.entity ?? "Resource"} not found` }, 404)
      case "ValidationError":
      case "SqlGuardError":
        return jsonResponse({ error: rec._tag, message: rec.message }, 400)
      case "ConflictError":
        return jsonResponse({ error: "conflict", message: rec.message }, 409)
      case "PlaidApiError":
        return jsonResponse({ error: rec.code ?? "plaid_error", message: rec.message }, 502)
      default:
        return jsonResponse({ error: rec._tag, message: rec.message ?? "Internal error" }, 500)
    }
  }
  return jsonResponse({ error: "internal_error", message: err instanceof Error ? err.message : "Unexpected error" }, 500)
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url)
    const route = buildRouteContext(url, env.BASE_PATH)
    const layer = buildAppLayer(env)

    const program = Effect.gen(function* () {
      if (route.path === "/mcp") {
        return yield* handleMcpRequest(request, route)
      }
      const oauthRes = yield* handleOAuthRoutes(request, route)
      if (oauthRes) return oauthRes
      return yield* handleAppRoutes(request, route, env)
    })

    const exit = await Effect.runPromiseExit(Effect.provide(program, layer))
    if (exit._tag === "Success") return exit.value

    return errorToResponse(Cause.squash(exit.cause))
  },

  async queue(batch: MessageBatch<SyncQueueMessage>, env: Env): Promise<void> {
    const layer = buildAppLayer(env)
    for (const msg of batch.messages) {
      const exit = await Effect.runPromiseExit(
        Effect.provide(
          syncItemInternal(msg.body.workspaceId, msg.body.itemId, msg.body.trigger),
          layer,
        ),
      )
      if (exit._tag === "Success") {
        msg.ack()
      } else {
        msg.retry()
      }
    }
  },

  async scheduled(_controller: ScheduledController, env: Env): Promise<void> {
    const layer = buildAppLayer(env)
    const items = await Effect.runPromise(Effect.provide(listAllActiveItemsForCron(), layer))
    for (const item of items) {
      if (env.PLAID_SYNC_QUEUE) {
        await env.PLAID_SYNC_QUEUE.send({
          workspaceId: item.workspace_id,
          itemId: item.item_id,
          trigger: "cron",
        })
      } else {
        await Effect.runPromiseExit(
          Effect.provide(syncItemInternal(item.workspace_id, item.item_id, "cron"), layer),
        )
      }
    }
  },
}
