import { Effect } from "effect"
import {
  completeUpstreamOidcCallback,
  createBrowserSession,
  decideDeviceFlow,
  exchangeAuthorizationCode,
  getOAuthClient,
  issueAuthorizationCode,
  lookupDeviceFlow,
  pollDeviceFlow,
  refreshOAuthGrant,
  registerOAuthClient,
  revokeBrowserSession,
  revokeOAuthToken,
  startDeviceFlow,
  startUpstreamOidcFlow,
  verifyBrowserSession,
  type Actor,
} from "@radiant/core"
import { formatSetCookie, getCookie, htmlResponse, jsonResponse, type AppServices, type RouteContext } from "./env"
import { renderDeviceApprovePage, renderOAuthConsentPage } from "./ui"

export const SESSION_COOKIE = "radiant_session"
export const FLOW_COOKIE = "radiant_oidc_flow"

const isSecureOrigin = (url: URL): boolean => url.protocol === "https:"

const readFormOrJson = async (request: Request): Promise<Record<string, string>> => {
  const ct = request.headers.get("content-type") ?? ""
  if (ct.includes("application/json")) {
    const obj = (await request.json().catch(() => ({}))) as Record<string, unknown>
    return Object.fromEntries(Object.entries(obj).map(([k, v]) => [k, String(v ?? "")]))
  }
  const text = await request.text()
  const params = new URLSearchParams(text)
  const out: Record<string, string> = {}
  params.forEach((v, k) => {
    out[k] = v
  })
  return out
}

export const resolveBrowserActor = (
  request: Request,
): Effect.Effect<Actor | null, import("@radiant/core").DatabaseError, AppServices> => {
  const cookie = getCookie(request, SESSION_COOKIE)
  return cookie ? verifyBrowserSession(cookie) : Effect.succeed(null)
}

export const handleOAuthRoutes = (
  request: Request,
  route: RouteContext,
): Effect.Effect<Response | null, unknown, AppServices> =>
  Effect.gen(function* () {
    const { url, baseUrl, basePath, path } = route
    const cookiePath = basePath || "/"

    // RFC 9728: OAuth Protected Resource Metadata
    if (
      request.method === "GET" &&
      (path === "/.well-known/oauth-protected-resource" ||
        path === "/.well-known/oauth-protected-resource/mcp")
    ) {
      return jsonResponse({
        resource: `${baseUrl}/mcp`,
        authorization_servers: [baseUrl],
        bearer_methods_supported: ["header"],
        scopes_supported: ["radiant"],
      })
    }

    // RFC 8414: OAuth Authorization Server Metadata
    if (request.method === "GET" && path === "/.well-known/oauth-authorization-server") {
      return jsonResponse({
        issuer: baseUrl,
        authorization_endpoint: `${baseUrl}/oauth/authorize`,
        token_endpoint: `${baseUrl}/oauth/token`,
        registration_endpoint: `${baseUrl}/oauth/register`,
        revocation_endpoint: `${baseUrl}/oauth/revoke`,
        device_authorization_endpoint: `${baseUrl}/api/v1/auth/device`,
        response_types_supported: ["code"],
        grant_types_supported: [
          "authorization_code",
          "refresh_token",
          "urn:ietf:params:oauth:grant-type:device_code",
        ],
        code_challenge_methods_supported: ["S256"],
        token_endpoint_auth_methods_supported: ["none"],
        scopes_supported: ["radiant"],
      })
    }

    // RFC 7591: Dynamic Client Registration
    if (request.method === "POST" && path === "/oauth/register") {
      const body = yield* Effect.tryPromise(() => request.json() as Promise<Record<string, unknown>>)
      const registered = yield* registerOAuthClient({
        client_name: typeof body.client_name === "string" ? body.client_name : undefined,
        redirect_uris: Array.isArray(body.redirect_uris) ? (body.redirect_uris as ReadonlyArray<string>) : [],
      })
      return jsonResponse(registered, 201)
    }

    // Browser sign-in start -> account.anoma.ly OIDC
    if (request.method === "GET" && path === "/auth/login") {
      const returnTo = url.searchParams.get("return_to") ?? `${basePath || "/"}`
      const safeReturn = returnTo.startsWith("/") && !returnTo.startsWith("//") ? returnTo : `${basePath || "/"}`
      const flow = yield* startUpstreamOidcFlow({
        kind: "browser_login",
        origin: baseUrl,
        returnTo: safeReturn,
      })
      return new Response(null, {
        status: 302,
        headers: {
          location: flow.authorizeUrl,
          "set-cookie": formatSetCookie(FLOW_COOKIE, flow.browserToken, {
            maxAge: 600,
            path: cookiePath,
            secure: isSecureOrigin(url),
          }),
        },
      })
    }

    // Browser sign-out
    if (request.method === "POST" && path === "/auth/logout") {
      const token = getCookie(request, SESSION_COOKIE)
      if (token) yield* revokeBrowserSession(token)
      return new Response(null, {
        status: 302,
        headers: {
          location: basePath || "/",
          "set-cookie": formatSetCookie(SESSION_COOKIE, "", {
            maxAge: 0,
            path: cookiePath,
            secure: isSecureOrigin(url),
          }),
        },
      })
    }

    // OIDC callback from account.anoma.ly
    if (request.method === "GET" && path === "/oauth/callback") {
      const code = url.searchParams.get("code")
      const state = url.searchParams.get("state")
      const iss = url.searchParams.get("iss")
      const err = url.searchParams.get("error")
      if (err) {
        return htmlResponse(`<h1>Sign-in error</h1><p>${err}</p>`, 400)
      }
      if (!code || !state) {
        return htmlResponse("<h1>Missing code or state</h1>", 400)
      }
      const browserToken = getCookie(request, FLOW_COOKIE)
      const { flow, user } = yield* completeUpstreamOidcCallback({
        origin: baseUrl,
        state,
        code,
        iss,
        browserToken,
      })
      const sess = yield* createBrowserSession(user.id)
      const dest = flow.return_to && flow.return_to.startsWith("/") ? flow.return_to : basePath || "/"
      const headers = new Headers({ location: dest })
      headers.append(
        "set-cookie",
        formatSetCookie(SESSION_COOKIE, sess.token, {
          maxAge: 30 * 86400,
          path: cookiePath,
          secure: isSecureOrigin(url),
        }),
      )
      headers.append(
        "set-cookie",
        formatSetCookie(FLOW_COOKIE, "", { maxAge: 0, path: cookiePath, secure: isSecureOrigin(url) }),
      )
      return new Response(null, { status: 302, headers })
    }

    // MCP OAuth 2.1 Authorize (GET shows consent; POST issues auth code)
    if (path === "/oauth/authorize" && request.method === "GET") {
      const clientId = url.searchParams.get("client_id") ?? ""
      const redirectUri = url.searchParams.get("redirect_uri") ?? ""
      const codeChallenge = url.searchParams.get("code_challenge") ?? ""
      const method = url.searchParams.get("code_challenge_method") ?? ""
      const state = url.searchParams.get("state") ?? ""
      const scope = url.searchParams.get("scope") ?? "radiant"

      if (!clientId || !redirectUri || !codeChallenge || method !== "S256") {
        return jsonResponse({ error: "invalid_request", error_description: "Missing PKCE S256 or client parameters" }, 400)
      }
      const client = yield* getOAuthClient(clientId)
      if (!client.redirect_uris.includes(redirectUri)) {
        return jsonResponse({ error: "invalid_request", error_description: "redirect_uri not registered" }, 400)
      }

      const actor = yield* resolveBrowserActor(request)
      if (!actor) {
        const returnTo = `${url.pathname}${url.search}`
        return new Response(null, {
          status: 302,
          headers: { location: `${basePath}/auth/login?return_to=${encodeURIComponent(returnTo)}` },
        })
      }

      return htmlResponse(
        renderOAuthConsentPage({
          basePath,
          clientName: client.name,
          redirectUri,
          email: actor.email,
          hiddenFields: {
            client_id: clientId,
            redirect_uri: redirectUri,
            code_challenge: codeChallenge,
            state,
            scope,
          },
        }),
      )
    }

    if (path === "/oauth/authorize" && request.method === "POST") {
      const actor = yield* resolveBrowserActor(request)
      if (!actor) return jsonResponse({ error: "unauthorized" }, 401)

      const form = yield* Effect.tryPromise(() => readFormOrJson(request))
      const clientId = form.client_id ?? ""
      const redirectUri = form.redirect_uri ?? ""
      const codeChallenge = form.code_challenge ?? ""
      const state = form.state ?? ""
      const scope = form.scope ?? "radiant"
      const decision = form.decision ?? "deny"

      const client = yield* getOAuthClient(clientId)
      if (!client.redirect_uris.includes(redirectUri)) {
        return jsonResponse({ error: "invalid_request" }, 400)
      }

      const target = new URL(redirectUri)
      if (state) target.searchParams.set("state", state)
      if (decision !== "approve") {
        target.searchParams.set("error", "access_denied")
        return Response.redirect(target.toString(), 302)
      }

      const code = yield* issueAuthorizationCode({
        clientId: client.id,
        userId: actor.userId,
        redirectUri,
        codeChallenge,
        scope,
      })
      target.searchParams.set("code", code)
      return Response.redirect(target.toString(), 302)
    }

    // OAuth Token endpoint (authorization_code & refresh_token)
    if (request.method === "POST" && path === "/oauth/token") {
      const form = yield* Effect.tryPromise(() => readFormOrJson(request))
      const grantType = form.grant_type

      if (grantType === "authorization_code") {
        const tokens = yield* exchangeAuthorizationCode({
          code: form.code ?? "",
          clientId: form.client_id ?? "",
          redirectUri: form.redirect_uri ?? "",
          codeVerifier: form.code_verifier ?? "",
        })
        return jsonResponse(tokens)
      }

      if (grantType === "refresh_token") {
        const tokens = yield* refreshOAuthGrant({
          refreshToken: form.refresh_token ?? "",
          clientId: form.client_id ?? "",
        })
        return jsonResponse(tokens)
      }

      return jsonResponse({ error: "unsupported_grant_type" }, 400)
    }

    // OAuth Revocation
    if (request.method === "POST" && path === "/oauth/revoke") {
      const form = yield* Effect.tryPromise(() => readFormOrJson(request))
      if (form.token) yield* revokeOAuthToken(form.token)
      return jsonResponse({ revoked: true })
    }

    // Device Flow (RFC 8628)
    if (request.method === "POST" && path === "/api/v1/auth/device") {
      const form = yield* Effect.tryPromise(() => readFormOrJson(request))
      const started = yield* startDeviceFlow(form.client_name || "An agent", baseUrl)
      return jsonResponse(started)
    }

    if (request.method === "POST" && path === "/api/v1/auth/token") {
      const form = yield* Effect.tryPromise(() => readFormOrJson(request))
      const polled = yield* pollDeviceFlow(form.device_code ?? "")
      if ("error" in polled) {
        return jsonResponse({ error: polled.error }, 400)
      }
      return jsonResponse(polled.tokens)
    }

    if (path === "/device" && request.method === "GET") {
      const actor = yield* resolveBrowserActor(request)
      if (!actor) {
        return new Response(null, {
          status: 302,
          headers: { location: `${basePath}/auth/login?return_to=${encodeURIComponent(url.pathname + url.search)}` },
        })
      }
      const code = url.searchParams.get("code") ?? ""
      const pending = code ? yield* lookupDeviceFlow(code) : null
      return htmlResponse(
        renderDeviceApprovePage({
          basePath,
          email: actor.email,
          code,
          clientName: pending?.client_name ?? null,
        }),
      )
    }

    if (path === "/device" && request.method === "POST") {
      const actor = yield* resolveBrowserActor(request)
      if (!actor) return jsonResponse({ error: "unauthorized" }, 401)
      const form = yield* Effect.tryPromise(() => readFormOrJson(request))
      const decided = yield* decideDeviceFlow(form.code ?? "", actor.userId, form.decision === "approve")
      return htmlResponse(
        renderDeviceApprovePage({
          basePath,
          email: actor.email,
          code: decided.user_code,
          message: decided.status === "approved" ? "Approved. You can return to your agent." : "Denied.",
        }),
      )
    }

    return null
  })
