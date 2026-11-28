import { Context, Effect, Layer } from "effect"
import { PlaidApiError } from "./errors"

export interface PlaidAccountDto {
  readonly account_id: string
  readonly name: string
  readonly official_name: string | null
  readonly mask: string | null
  readonly type: string
  readonly subtype: string | null
  readonly balances: {
    readonly current: number | null
    readonly available: number | null
    readonly limit: number | null
    readonly iso_currency_code: string | null
  }
}

export interface PlaidTransactionDto {
  readonly transaction_id: string
  readonly account_id: string
  readonly amount: number // Plaid native: + outflow, - inflow
  readonly iso_currency_code: string | null
  readonly unofficial_currency_code?: string | null
  readonly date: string
  readonly authorized_date: string | null
  readonly name: string
  readonly merchant_name: string | null
  readonly merchant_entity_id?: string | null
  readonly pending: boolean
  readonly pending_transaction_id: string | null
  readonly payment_channel: string | null
  readonly personal_finance_category?: {
    readonly primary: string
    readonly detailed: string
    readonly confidence_level?: string | null
  } | null
  readonly counterparties?: ReadonlyArray<{ readonly name: string; readonly type?: string }>
  readonly location?: Record<string, unknown>
}

export interface PlaidSyncResponse {
  readonly added: ReadonlyArray<PlaidTransactionDto>
  readonly modified: ReadonlyArray<PlaidTransactionDto>
  readonly removed: ReadonlyArray<{ readonly transaction_id: string }>
  readonly next_cursor: string
  readonly has_more: boolean
  readonly accounts?: ReadonlyArray<PlaidAccountDto>
}

export interface PlaidClientInterface {
  readonly linkTokenCreate: (input: {
    readonly workspaceId: string
    readonly accessToken?: string
    readonly webhookUrl?: string
  }) => Effect.Effect<{ readonly link_token: string; readonly expiration: string }, PlaidApiError>
  readonly itemPublicTokenExchange: (
    publicToken: string,
  ) => Effect.Effect<{ readonly access_token: string; readonly item_id: string }, PlaidApiError>
  readonly accountsGet: (accessToken: string) => Effect.Effect<{
    readonly accounts: ReadonlyArray<PlaidAccountDto>
    readonly item: {
      readonly item_id: string
      readonly institution_id: string | null
      readonly consent_expiration_time: string | null
      readonly error: { readonly error_code: string; readonly error_message: string } | null
    }
  }, PlaidApiError>
  readonly institutionGetById: (
    institutionId: string,
  ) => Effect.Effect<{ readonly institution_id: string; readonly name: string }, PlaidApiError>
  readonly transactionsSync: (input: {
    readonly accessToken: string
    readonly cursor?: string | null
    readonly count?: number
  }) => Effect.Effect<PlaidSyncResponse, PlaidApiError>
  readonly transactionsRefresh: (accessToken: string) => Effect.Effect<void, PlaidApiError>
  readonly itemRemove: (accessToken: string) => Effect.Effect<void, PlaidApiError>
  readonly webhookVerificationKeyGet: (
    keyId: string,
  ) => Effect.Effect<{ readonly key: Record<string, unknown> }, PlaidApiError>
}

export class PlaidClient extends Context.Service<PlaidClient, PlaidClientInterface>()(
  "@radiant/core/PlaidClient",
) {}

const baseUrlForEnv = (env: string): string => {
  switch (env.toLowerCase()) {
    case "production":
      return "https://production.plaid.com"
    case "development":
      return "https://development.plaid.com"
    default:
      return "https://sandbox.plaid.com"
  }
}

export const makeLivePlaidClient = (config: {
  readonly clientId: string
  readonly secret: string
  readonly environment: string
}): PlaidClientInterface => {
  const baseUrl = baseUrlForEnv(config.environment)

  const post = <T>(path: string, body: Record<string, unknown>): Effect.Effect<T, PlaidApiError> =>
    Effect.tryPromise({
      try: async () => {
        const res = await fetch(`${baseUrl}${path}`, {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({
            client_id: config.clientId,
            secret: config.secret,
            ...body,
          }),
        })
        const json = (await res.json()) as Record<string, unknown>
        if (!res.ok) {
          const code = String(json.error_code ?? `HTTP_${res.status}`)
          const message = String(json.error_message ?? `Plaid request failed (${res.status})`)
          const retryable =
            res.status >= 500 ||
            res.status === 429 ||
            code === "TRANSACTIONS_SYNC_MUTATION_DURING_PAGINATION" ||
            code === "PRODUCT_NOT_READY"
          throw new PlaidApiError({ code, message, retryable, status: res.status })
        }
        return json as T
      },
      catch: (err) =>
        err instanceof PlaidApiError
          ? err
          : new PlaidApiError({
              code: "NETWORK_ERROR",
              message: err instanceof Error ? err.message : String(err),
              retryable: true,
            }),
    })

  return PlaidClient.of({
    linkTokenCreate: (input) =>
      post("/link/token/create", {
        client_name: "Radiant",
        language: "en",
        country_codes: ["US", "CA"],
        user: { client_user_id: input.workspaceId },
        ...(input.accessToken
          ? { access_token: input.accessToken }
          : { products: ["transactions"], transactions: { days_requested: 730 } }),
        ...(input.webhookUrl ? { webhook: input.webhookUrl } : {}),
      }),
    itemPublicTokenExchange: (publicToken) =>
      post("/item/public_token/exchange", { public_token: publicToken }),
    accountsGet: (accessToken) =>
      post("/accounts/get", { access_token: accessToken }),
    institutionGetById: (institutionId) =>
      post<{ institution: { institution_id: string; name: string } }>("/institutions/get_by_id", {
        institution_id: institutionId,
        country_codes: ["US", "CA"],
      }).pipe(Effect.map((r) => r.institution)),
    transactionsSync: (input) =>
      post("/transactions/sync", {
        access_token: input.accessToken,
        ...(input.cursor ? { cursor: input.cursor } : {}),
        count: input.count ?? 500,
        options: { include_personal_finance_category: true },
      }),
    transactionsRefresh: (accessToken) =>
      post("/transactions/refresh", { access_token: accessToken }).pipe(Effect.asVoid),
    itemRemove: (accessToken) =>
      post("/item/remove", { access_token: accessToken }).pipe(Effect.asVoid),
    webhookVerificationKeyGet: (keyId) =>
      post("/webhook_verification_key/get", { key_id: keyId }),
  })
}

export const layerPlaidLive = (config: {
  readonly clientId: string
  readonly secret: string
  readonly environment: string
}) => Layer.succeed(PlaidClient, makeLivePlaidClient(config))
