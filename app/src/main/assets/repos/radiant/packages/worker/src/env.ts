import { Layer } from "effect"
import {
  layerAuthConfig,
  layerCryptoConfig,
  layerPlanetscale,
  layerPlaidLive,
  type AuthConfig,
  type CryptoConfig,
  type Database,
  type PlaidClient,
} from "@radiant/core"

export interface SyncQueueMessage {
  readonly workspaceId: string
  readonly itemId: string
  readonly trigger: "webhook" | "cron" | "manual"
}

export interface RouteContext {
  /** Base path prefix without trailing slash, e.g. "/labs/radiant" or "" */
  readonly basePath: string
  /** Origin + basePath without trailing slash, e.g. "https://anoma.ly/labs/radiant" */
  readonly baseUrl: string
  /** Request origin, e.g. "https://anoma.ly" */
  readonly origin: string
  /** Normalized internal route path starting with "/", with basePath stripped */
  readonly path: string
  /** Original request URL */
  readonly url: URL
}

export const buildRouteContext = (url: URL, configuredBasePath?: string): RouteContext => {
  const cleanBase = (configuredBasePath ?? "").replace(/\/+$/, "")
  const rawPath = url.pathname

  // RFC 9728 / RFC 8414 path-inserted well-known routes at host root
  if (cleanBase && rawPath.startsWith(`/.well-known/oauth-protected-resource${cleanBase}`)) {
    const suffix = rawPath.slice(`/.well-known/oauth-protected-resource${cleanBase}`.length) || ""
    return {
      basePath: cleanBase,
      baseUrl: `${url.origin}${cleanBase}`,
      origin: url.origin,
      path: `/.well-known/oauth-protected-resource${suffix}`,
      url,
    }
  }
  if (cleanBase && rawPath === `/.well-known/oauth-authorization-server${cleanBase}`) {
    return {
      basePath: cleanBase,
      baseUrl: `${url.origin}${cleanBase}`,
      origin: url.origin,
      path: "/.well-known/oauth-authorization-server",
      url,
    }
  }

  if (cleanBase && (rawPath === cleanBase || rawPath.startsWith(`${cleanBase}/`))) {
    const stripped = rawPath.slice(cleanBase.length) || "/"
    return {
      basePath: cleanBase,
      baseUrl: `${url.origin}${cleanBase}`,
      origin: url.origin,
      path: stripped,
      url,
    }
  }

  return {
    basePath: "",
    baseUrl: url.origin,
    origin: url.origin,
    path: rawPath || "/",
    url,
  }
}

export interface Env {
  readonly STAGE: string
  readonly BASE_PATH?: string
  readonly ACCOUNT_ISSUER: string
  readonly ACCOUNT_CLIENT_ID: string
  readonly PLAID_ENV: string
  readonly ENCRYPTION_KEY_VERSION: string
  readonly DATABASE_URL: string
  readonly DATABASE_READ_URL?: string
  readonly ENCRYPTION_KEY: string
  readonly ENCRYPTION_KEY_PREVIOUS?: string
  readonly SESSION_SECRET: string
  readonly PLAID_CLIENT_ID?: string
  readonly PLAID_SECRET?: string
  readonly PLAID_SYNC_QUEUE?: Queue<SyncQueueMessage>
}

export type AppServices = Database | AuthConfig | CryptoConfig | PlaidClient

export const buildAppLayer = (env: Env): Layer.Layer<AppServices> => {
  const keysByVersion: Record<string, string> = {
    [env.ENCRYPTION_KEY_VERSION || "v1"]: env.ENCRYPTION_KEY,
  }
  if (env.ENCRYPTION_KEY_PREVIOUS) {
    keysByVersion.prev = env.ENCRYPTION_KEY_PREVIOUS
  }

  return Layer.mergeAll(
    layerPlanetscale({
      url: env.DATABASE_URL,
      readUrl: env.DATABASE_READ_URL || env.DATABASE_URL,
    }),
    layerAuthConfig({
      accountIssuer: env.ACCOUNT_ISSUER,
      accountClientId: env.ACCOUNT_CLIENT_ID,
      sessionSecret: env.SESSION_SECRET,
    }),
    layerCryptoConfig({
      currentVersion: env.ENCRYPTION_KEY_VERSION || "v1",
      keysByVersion,
    }),
    layerPlaidLive({
      clientId: env.PLAID_CLIENT_ID ?? "",
      secret: env.PLAID_SECRET ?? "",
      environment: env.PLAID_ENV || "sandbox",
    }),
  )
}

export const getCookie = (request: Request, name: string): string | null => {
  const raw = request.headers.get("cookie")
  if (!raw) return null
  for (const part of raw.split(";")) {
    const idx = part.indexOf("=")
    if (idx === -1) continue
    if (part.slice(0, idx).trim() === name) {
      return decodeURIComponent(part.slice(idx + 1).trim())
    }
  }
  return null
}

export const formatSetCookie = (
  name: string,
  value: string,
  options: { readonly maxAge?: number; readonly secure?: boolean; readonly path?: string; readonly sameSite?: "Lax" | "Strict" } = {},
): string => {
  const parts = [
    `${name}=${encodeURIComponent(value)}`,
    `Path=${options.path ?? "/"}`,
    "HttpOnly",
    `SameSite=${options.sameSite ?? "Lax"}`,
  ]
  if (options.maxAge !== undefined) parts.push(`Max-Age=${options.maxAge}`)
  if (options.secure !== false) parts.push("Secure")
  return parts.join("; ")
}

export const escapeHtml = (input: string): string =>
  input
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;")

export const jsonResponse = (
  body: unknown,
  status = 200,
  extraHeaders?: Record<string, string>,
): Response =>
  new Response(JSON.stringify(body), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
      ...extraHeaders,
    },
  })

export const htmlResponse = (
  html: string,
  status = 200,
  extraHeaders?: Record<string, string>,
): Response =>
  new Response(html, {
    status,
    headers: {
      "content-type": "text/html; charset=utf-8",
      "cache-control": "no-store",
      "x-frame-options": "DENY",
      "content-security-policy":
        "default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.plaid.com; style-src 'self' 'unsafe-inline'; frame-src https://cdn.plaid.com https://*.plaid.com; connect-src 'self' https://*.plaid.com; frame-ancestors 'none'",
      ...extraHeaders,
    },
  })
