import { Effect } from "effect"
import { decodeProtectedHeader, importJWK, jwtVerify } from "jose"
import { constantTimeEqual, sha256Hex } from "./crypto"
import { UnauthorizedError } from "./errors"
import { PlaidClient } from "./plaid-client"

const keyCache = new Map<string, { key: Record<string, unknown>; fetchedAt: number }>()

export const verifyPlaidWebhook = (
  rawBody: string,
  plaidVerificationHeader: string | null,
): Effect.Effect<Record<string, unknown>, UnauthorizedError, PlaidClient> =>
  Effect.gen(function* () {
    if (!plaidVerificationHeader) {
      return yield* new UnauthorizedError({ message: "Missing Plaid-Verification header" })
    }

    const header = yield* Effect.try({
      try: () => decodeProtectedHeader(plaidVerificationHeader),
      catch: () => new UnauthorizedError({ message: "Malformed Plaid-Verification JWT header" }),
    })

    if (header.alg !== "ES256" || typeof header.kid !== "string") {
      return yield* new UnauthorizedError({ message: "Unsupported Plaid webhook JWT algorithm or missing kid" })
    }

    const cached = keyCache.get(header.kid)
    let jwk = cached && Date.now() - cached.fetchedAt < 3_600_000 ? cached.key : null
    if (!jwk) {
      const plaid = yield* PlaidClient
      const fetched = yield* plaid.webhookVerificationKeyGet(header.kid).pipe(
        Effect.mapError((e) => new UnauthorizedError({ message: `Failed to fetch Plaid JWK: ${e.message}` })),
      )
      jwk = fetched.key
      keyCache.set(header.kid, { key: jwk, fetchedAt: Date.now() })
    }

    const payload = yield* Effect.tryPromise({
      try: async () => {
        const key = await importJWK(jwk!, "ES256")
        const res = await jwtVerify(plaidVerificationHeader, key, {
          algorithms: ["ES256"],
          maxTokenAge: "5 minutes",
        })
        return res.payload
      },
      catch: (e) =>
        new UnauthorizedError({
          message: `Plaid webhook signature invalid: ${e instanceof Error ? e.message : String(e)}`,
        }),
    })

    const claimedHash = payload.request_body_sha256
    if (typeof claimedHash !== "string") {
      return yield* new UnauthorizedError({ message: "Plaid webhook JWT missing request_body_sha256" })
    }
    const computedHash = yield* sha256Hex(rawBody)
    if (!constantTimeEqual(claimedHash.toLowerCase(), computedHash.toLowerCase())) {
      return yield* new UnauthorizedError({ message: "Plaid webhook body hash mismatch" })
    }

    return yield* Effect.try({
      try: () => JSON.parse(rawBody) as Record<string, unknown>,
      catch: () => new UnauthorizedError({ message: "Invalid JSON webhook payload" }),
    })
  })
