import { Context, Effect, Layer } from "effect"
import type { SyncTrigger } from "@radiant/database/schema"
import { decryptSecret, encryptSecret, randomToken, sha256Hex } from "./crypto"
import { Database, toBool, toNullableNum, toNum, type DbExecutor, type SqlParam } from "./db"
import { NotFoundError, PlaidApiError, ValidationError } from "./errors"
import { Id } from "./id"
import { rematerializeTransactions } from "./overlay"
import { PlaidClient, type PlaidAccountDto, type PlaidTransactionDto } from "./plaid-client"
import { assertWorkspaceAccess, type Actor } from "./workspace"

export interface CryptoConfigInterface {
  readonly currentVersion: string
  readonly keysByVersion: Readonly<Record<string, string>>
}

export class CryptoConfig extends Context.Service<CryptoConfig, CryptoConfigInterface>()(
  "@radiant/core/CryptoConfig",
) {}

export const layerCryptoConfig = (config: CryptoConfigInterface) => Layer.succeed(CryptoConfig, config)

const toCents = (dollars: number | null | undefined): number | null =>
  dollars === null || dollars === undefined ? null : Math.round(dollars * 100)

export const createConnectHandoffLink = (
  actor: Actor,
  workspaceId: string,
  input: { readonly mode?: "new" | "update"; readonly item_id?: string },
  origin: string,
) =>
  Effect.gen(function* () {
    const ws = yield* assertWorkspaceAccess(actor, workspaceId, "admin")
    const mode = input.mode ?? "new"
    if (mode === "update" && !input.item_id) {
      return yield* new ValidationError({ message: "item_id is required for update mode", field: "item_id" })
    }
    const db = yield* Database
    if (mode === "update") {
      const cred = yield* db.query<{ item_id: string }>(
        "SELECT item_id FROM plaid_credential WHERE workspace_id = ? AND item_id = ? AND revoked_at IS NULL LIMIT 1",
        [ws.id, input.item_id!],
      )
      if (!cred.rows[0]) {
        return yield* new NotFoundError({ entity: "plaid_item", id: input.item_id })
      }
    }

    const rawToken = randomToken("rdl1_", 24)
    const tokenHash = yield* sha256Hex(rawToken)
    const now = new Date()
    const expiresAt = new Date(now.getTime() + 15 * 60_000)

    yield* db.execute(
      `INSERT INTO connect_token (token_hash, workspace_id, user_id, mode, item_id, expires_at, created_at)
       VALUES (?, ?, ?, ?, ?, ?, ?)`,
      [tokenHash, ws.id, actor.userId, mode, input.item_id ?? null, expiresAt, now],
    )

    return {
      connect_url: `${origin.replace(/\/$/, "")}/connect/${rawToken}`,
      workspace_id: ws.id,
      mode,
      item_id: input.item_id ?? null,
      expires_at: expiresAt.toISOString(),
    }
  })

export const resolveConnectHandoffToken = (rawToken: string) =>
  Effect.gen(function* () {
    const db = yield* Database
    const tokenHash = yield* sha256Hex(rawToken)
    const res = yield* db.query<{
      workspace_id: string
      user_id: string
      mode: "new" | "update"
      item_id: string | null
      expires_at: string
      consumed_at: string | null
    }>("SELECT * FROM connect_token WHERE token_hash = ? LIMIT 1", [tokenHash])
    const row = res.rows[0]
    if (!row || row.consumed_at || new Date(row.expires_at).getTime() < Date.now()) {
      return yield* new NotFoundError({ entity: "connect_token", message: "Connect link expired or invalid" })
    }
    return { tokenHash, ...row }
  })

export const createPlaidLinkToken = (
  actor: Actor,
  workspaceId: string,
  input: { readonly mode?: "new" | "update"; readonly item_id?: string; readonly webhookUrl?: string },
) =>
  Effect.gen(function* () {
    const ws = yield* assertWorkspaceAccess(actor, workspaceId, "admin")
    const plaid = yield* PlaidClient
    let accessToken: string | undefined

    if (input.mode === "update") {
      if (!input.item_id) {
        return yield* new ValidationError({ message: "item_id is required for update mode", field: "item_id" })
      }
      const db = yield* Database
      const cryptoCfg = yield* CryptoConfig
      const cred = yield* db.query<{ access_token_enc: string }>(
        "SELECT access_token_enc FROM plaid_credential WHERE workspace_id = ? AND item_id = ? AND revoked_at IS NULL LIMIT 1",
        [ws.id, input.item_id],
      )
      if (!cred.rows[0]) {
        return yield* new NotFoundError({ entity: "plaid_item", id: input.item_id })
      }
      accessToken = yield* decryptSecret(cred.rows[0].access_token_enc, cryptoCfg.keysByVersion)
    }

    return yield* plaid.linkTokenCreate({
      workspaceId: ws.id,
      accessToken,
      webhookUrl: input.webhookUrl,
    })
  })

const upsertAccountsAndSnapshots = (
  tx: DbExecutor,
  workspaceId: string,
  itemId: string,
  institutionId: string,
  institutionName: string,
  accounts: ReadonlyArray<PlaidAccountDto>,
  now: Date,
) =>
  Effect.gen(function* () {
    const plaidToInternal = new Map<string, string>()

    for (const acc of accounts) {
      const existing = yield* tx.query<{ id: string }>(
        "SELECT id FROM raw_account WHERE workspace_id = ? AND plaid_account_id = ? LIMIT 1",
        [workspaceId, acc.account_id],
      )

      let internalId = existing.rows[0]?.id

      // Re-link deduplication: match disconnected/same-institution account by (institution_id, mask, type, subtype, name)
      if (!internalId && acc.mask) {
        const dedup = yield* tx.query<{ id: string }>(
          `SELECT id FROM raw_account
           WHERE workspace_id = ? AND institution_id = ? AND mask = ? AND type = ?
             AND COALESCE(subtype, '') = COALESCE(?, '') AND name = ?
           LIMIT 1`,
          [workspaceId, institutionId, acc.mask, acc.type, acc.subtype, acc.name],
        )
        if (dedup.rows[0]) {
          internalId = dedup.rows[0].id
          yield* tx.execute(
            `UPDATE raw_account
             SET item_id = ?, plaid_account_id = ?, removed_at = NULL, updated_at = ?
             WHERE workspace_id = ? AND id = ?`,
            [itemId, acc.account_id, now, workspaceId, internalId],
          )
        }
      }

      const currentCents = toCents(acc.balances.current)
      const availableCents = toCents(acc.balances.available)
      const limitCents = toCents(acc.balances.limit)
      const currency = (acc.balances.iso_currency_code ?? "USD").toUpperCase()

      if (internalId) {
        yield* tx.execute(
          `UPDATE raw_account
           SET institution_id = ?, institution_name = ?, name = ?, official_name = ?, mask = ?,
               type = ?, subtype = ?, currency = ?, current_cents = ?, available_cents = ?,
               limit_cents = ?, raw_json = ?, removed_at = NULL, updated_at = ?
           WHERE workspace_id = ? AND id = ?`,
          [
            institutionId,
            institutionName,
            acc.name,
            acc.official_name,
            acc.mask,
            acc.type,
            acc.subtype,
            currency,
            currentCents,
            availableCents,
            limitCents,
            JSON.stringify(acc),
            now,
            workspaceId,
            internalId,
          ],
        )
      } else {
        internalId = Id.account()
        yield* tx.execute(
          `INSERT INTO raw_account
            (workspace_id, id, item_id, plaid_account_id, institution_id, institution_name,
             name, official_name, mask, type, subtype, currency,
             current_cents, available_cents, limit_cents, raw_json, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
          [
            workspaceId,
            internalId,
            itemId,
            acc.account_id,
            institutionId,
            institutionName,
            acc.name,
            acc.official_name,
            acc.mask,
            acc.type,
            acc.subtype,
            currency,
            currentCents,
            availableCents,
            limitCents,
            JSON.stringify(acc),
            now,
            now,
          ],
        )
      }

      plaidToInternal.set(acc.account_id, internalId)

      yield* tx.execute(
        `INSERT INTO raw_balance_snapshot
          (workspace_id, id, account_id, captured_at, currency, current_cents, available_cents, limit_cents)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
        [workspaceId, Id.snapshot(), internalId, now, currency, currentCents, availableCents, limitCents],
      )
    }

    return plaidToInternal
  })

export const exchangePublicToken = (
  actor: Actor,
  workspaceId: string,
  input: { readonly public_token: string; readonly connect_token?: string },
) =>
  Effect.gen(function* () {
    const ws = yield* assertWorkspaceAccess(actor, workspaceId, "admin")
    const plaid = yield* PlaidClient
    const cryptoCfg = yield* CryptoConfig
    const db = yield* Database

    const exchanged = yield* plaid.itemPublicTokenExchange(input.public_token)
    const keyB64 = cryptoCfg.keysByVersion[cryptoCfg.currentVersion]
    if (!keyB64) {
      return yield* new ValidationError({ message: "Server encryption key is not configured" })
    }
    const encrypted = yield* encryptSecret(exchanged.access_token, keyB64, cryptoCfg.currentVersion)

    const accResp = yield* plaid.accountsGet(exchanged.access_token)
    const institutionId = accResp.item.institution_id ?? "unknown"
    const institutionName =
      institutionId !== "unknown"
        ? yield* plaid.institutionGetById(institutionId).pipe(
            Effect.map((i) => i.name),
            Effect.catch(() => Effect.succeed(institutionId)),
          )
        : "Connected Institution"

    const now = new Date()
    const connectHash = input.connect_token ? yield* sha256Hex(input.connect_token) : null

    yield* db.transaction((tx) =>
      Effect.gen(function* () {
        yield* tx.execute(
          `DELETE FROM plaid_credential WHERE workspace_id = ? AND item_id = ?`,
          [ws.id, exchanged.item_id],
        )
        yield* tx.execute(
          `INSERT INTO plaid_credential
            (workspace_id, item_id, access_token_enc, key_version, created_by, created_at)
           VALUES (?, ?, ?, ?, ?, ?)`,
          [ws.id, exchanged.item_id, encrypted, cryptoCfg.currentVersion, actor.userId, now],
        )

        const existingItem = yield* tx.query<{ item_id: string }>(
          "SELECT item_id FROM raw_item WHERE workspace_id = ? AND item_id = ? LIMIT 1",
          [ws.id, exchanged.item_id],
        )
        if (existingItem.rows[0]) {
          yield* tx.execute(
            `UPDATE raw_item
             SET institution_id = ?, institution_name = ?, status = 'healthy',
                 error_code = NULL, error_message = NULL, consent_expires_at = ?,
                 raw_json = ?, disconnected_at = NULL, updated_at = ?
             WHERE workspace_id = ? AND item_id = ?`,
            [
              institutionId,
              institutionName,
              accResp.item.consent_expiration_time ? new Date(accResp.item.consent_expiration_time) : null,
              JSON.stringify(accResp.item),
              now,
              ws.id,
              exchanged.item_id,
            ],
          )
        } else {
          yield* tx.execute(
            `INSERT INTO raw_item
              (workspace_id, item_id, institution_id, institution_name, status,
               consent_expires_at, raw_json, created_at, updated_at)
             VALUES (?, ?, ?, ?, 'healthy', ?, ?, ?, ?)`,
            [
              ws.id,
              exchanged.item_id,
              institutionId,
              institutionName,
              accResp.item.consent_expiration_time ? new Date(accResp.item.consent_expiration_time) : null,
              JSON.stringify(accResp.item),
              now,
              now,
            ],
          )
        }

        yield* upsertAccountsAndSnapshots(
          tx,
          ws.id,
          exchanged.item_id,
          institutionId,
          institutionName,
          accResp.accounts,
          now,
        )

        if (connectHash) {
          // Keep connect_token valid for its 15-min TTL so the user can link multiple banks in one session
          yield* tx.execute(
            "UPDATE connect_token SET consumed_at = NULL WHERE token_hash = ? AND expires_at > ?",
            [connectHash, now],
          )
        }
      }),
    )

    const syncResult = yield* syncItemInternal(ws.id, exchanged.item_id, "initial")

    return {
      item_id: exchanged.item_id,
      institution_id: institutionId,
      institution_name: institutionName,
      accounts_count: accResp.accounts.length,
      sync: syncResult,
    }
  })

const fetchAllSyncPages = (
  plaid: import("./plaid-client").PlaidClientInterface,
  accessToken: string,
  initialCursor: string | null,
) =>
  Effect.gen(function* () {
    const maxRestarts = 3
    for (let attempt = 0; attempt < maxRestarts; attempt++) {
      let cursor: string | null = initialCursor
      const added: Array<PlaidTransactionDto> = []
      const modified: Array<PlaidTransactionDto> = []
      const removed: Array<string> = []
      let mutated = false

      while (true) {
        const pageExit = yield* Effect.result(
          plaid.transactionsSync({ accessToken, cursor }),
        )
        if (pageExit._tag === "Failure") {
          const err = pageExit.failure
          if (err.code === "TRANSACTIONS_SYNC_MUTATION_DURING_PAGINATION" && attempt < maxRestarts - 1) {
            mutated = true
            break
          }
          return yield* err
        }
        const page = pageExit.success
        added.push(...page.added)
        modified.push(...page.modified)
        for (const r of page.removed) removed.push(r.transaction_id)
        cursor = page.next_cursor
        if (!page.has_more) {
          return { added, modified, removed, nextCursor: cursor }
        }
      }

      if (!mutated) break
    }
    return yield* new PlaidApiError({
      code: "TRANSACTIONS_SYNC_MUTATION_DURING_PAGINATION",
      message: "Plaid sync cursor mutated repeatedly during pagination",
      retryable: true,
    })
  })

export const syncItemInternal = (
  workspaceId: string,
  itemId: string,
  trigger: SyncTrigger,
  options?: { readonly forceRefresh?: boolean },
) =>
  Effect.gen(function* () {
    const db = yield* Database
    const plaid = yield* PlaidClient
    const cryptoCfg = yield* CryptoConfig

    const credRes = yield* db.query<{ access_token_enc: string }>(
      "SELECT access_token_enc FROM plaid_credential WHERE workspace_id = ? AND item_id = ? AND revoked_at IS NULL LIMIT 1",
      [workspaceId, itemId],
    )
    if (!credRes.rows[0]) {
      return yield* new NotFoundError({ entity: "plaid_item", id: itemId })
    }
    const accessToken = yield* decryptSecret(credRes.rows[0].access_token_enc, cryptoCfg.keysByVersion)

    const itemRes = yield* db.query<{
      institution_id: string
      institution_name: string
      sync_cursor: string | null
    }>(
      "SELECT institution_id, institution_name, sync_cursor FROM raw_item WHERE workspace_id = ? AND item_id = ? LIMIT 1",
      [workspaceId, itemId],
    )
    const item = itemRes.rows[0]
    if (!item) return yield* new NotFoundError({ entity: "raw_item", id: itemId })

    const runId = Id.syncRun()
    const startedAt = new Date()
    yield* db.execute(
      `INSERT INTO sync_run (workspace_id, id, item_id, trigger, status, cursor_before, started_at)
       VALUES (?, ?, ?, ?, 'running', ?, ?)`,
      [workspaceId, runId, itemId, trigger, item.sync_cursor, startedAt],
    )

    if (options?.forceRefresh) {
      yield* plaid.transactionsRefresh(accessToken).pipe(
        Effect.catch(() => Effect.void),
      )
    }

    const syncOutcome = yield* Effect.result(
      Effect.gen(function* () {
        const accResp = yield* plaid.accountsGet(accessToken)
        const pages = yield* fetchAllSyncPages(plaid, accessToken, item.sync_cursor)

        const now = new Date()

        // 1. Update accounts & balance snapshots in a small fast transaction
        const accMap = yield* db.transaction((tx) =>
          Effect.gen(function* () {
            const map = yield* upsertAccountsAndSnapshots(
              tx,
              workspaceId,
              itemId,
              item.institution_id,
              item.institution_name,
              accResp.accounts,
              now,
            )
            const existingAccs = yield* tx.query<{ id: string; plaid_account_id: string }>(
              "SELECT id, plaid_account_id FROM raw_account WHERE workspace_id = ? AND item_id = ?",
              [workspaceId, itemId],
            )
            for (const a of existingAccs.rows) {
              if (!map.has(a.plaid_account_id)) map.set(a.plaid_account_id, a.id)
            }
            return map
          }),
        )

        const impactedTxIds = new Set<string>()
        // Deduplicate by plaid_transaction_id (latest occurrence wins if added+modified in same sync)
        const byPlaidId = new Map<string, PlaidTransactionDto>()
        for (const ptx of [...pages.added, ...pages.modified]) {
          if (accMap.has(ptx.account_id)) byPlaidId.set(ptx.transaction_id, ptx)
        }
        const upserts = Array.from(byPlaidId.values())

        // 2. Bulk upsert raw_transactions in 40-row chunks (avoids Vitess 20s tx killer timeout!)
        const chunkOf = <T>(arr: ReadonlyArray<T>, size: number): Array<Array<T>> => {
          const out: Array<Array<T>> = []
          for (let i = 0; i < arr.length; i += size) out.push(arr.slice(i, i + size))
          return out
        }

        const pendingLinks: Array<{ postedTxId: string; pendingPlaidId: string; rawAmountCents: number }> = []

        for (const batch of chunkOf(upserts, 40)) {
          const pIds = batch.map((b) => b.transaction_id)
          const existingRes = yield* db.query<{ id: string; plaid_transaction_id: string }>(
            `SELECT id, plaid_transaction_id FROM raw_transaction
             WHERE workspace_id = ? AND plaid_transaction_id IN (${pIds.map(() => "?").join(", ")})`,
            [workspaceId, ...pIds],
          )
          const existingMap = new Map(existingRes.rows.map((r) => [r.plaid_transaction_id, r.id]))

          const toInsert: Array<{ txId: string; accountId: string; ptx: PlaidTransactionDto; rawAmountCents: number }> = []
          const toUpdate: Array<{ txId: string; accountId: string; ptx: PlaidTransactionDto; rawAmountCents: number }> = []

          for (const ptx of batch) {
            const accountId = accMap.get(ptx.account_id)!
            const rawAmountCents = Math.round(ptx.amount * 100)
            const existingId = existingMap.get(ptx.transaction_id)
            const txId = existingId ?? Id.tx()
            impactedTxIds.add(txId)
            if (existingId) toUpdate.push({ txId, accountId, ptx, rawAmountCents })
            else toInsert.push({ txId, accountId, ptx, rawAmountCents })

            if (!ptx.pending && ptx.pending_transaction_id) {
              pendingLinks.push({ postedTxId: txId, pendingPlaidId: ptx.pending_transaction_id, rawAmountCents })
            }
          }

          if (toInsert.length > 0) {
            const rowPh = toInsert
              .map(() => "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)")
              .join(", ")
            const insertParams: Array<SqlParam> = []
            for (const { txId, accountId, ptx, rawAmountCents } of toInsert) {
              const currency = (ptx.iso_currency_code ?? ptx.unofficial_currency_code ?? "USD").toUpperCase()
              const counterpartyName = ptx.counterparties?.[0]?.name ?? null
              insertParams.push(
                workspaceId,
                txId,
                accountId,
                itemId,
                ptx.transaction_id,
                ptx.pending_transaction_id ?? null,
                rawAmountCents,
                currency,
                ptx.date,
                ptx.authorized_date ?? null,
                ptx.name,
                ptx.merchant_name ?? null,
                ptx.merchant_entity_id ?? null,
                ptx.personal_finance_category?.primary ?? null,
                ptx.personal_finance_category?.detailed ?? null,
                ptx.personal_finance_category?.confidence_level ?? null,
                ptx.payment_channel ?? null,
                ptx.pending ? 1 : 0,
                counterpartyName,
                JSON.stringify(ptx),
                now,
                now,
              )
            }
            yield* db.execute(
              `INSERT INTO raw_transaction
                (workspace_id, id, account_id, item_id, plaid_transaction_id, pending_transaction_id,
                 raw_amount_cents, currency, date, authorized_date, name, merchant_name,
                 merchant_entity_id, pfc_primary, pfc_detailed, pfc_confidence,
                 payment_channel, pending, counterparty_name, raw_json, created_at, updated_at)
               VALUES ${rowPh}
               ON DUPLICATE KEY UPDATE
                 account_id = VALUES(account_id),
                 pending_transaction_id = VALUES(pending_transaction_id),
                 raw_amount_cents = VALUES(raw_amount_cents),
                 currency = VALUES(currency),
                 date = VALUES(date),
                 authorized_date = VALUES(authorized_date),
                 name = VALUES(name),
                 merchant_name = VALUES(merchant_name),
                 merchant_entity_id = VALUES(merchant_entity_id),
                 pfc_primary = VALUES(pfc_primary),
                 pfc_detailed = VALUES(pfc_detailed),
                 pfc_confidence = VALUES(pfc_confidence),
                 payment_channel = VALUES(payment_channel),
                 pending = VALUES(pending),
                 counterparty_name = VALUES(counterparty_name),
                 raw_json = VALUES(raw_json),
                 removed_at = NULL,
                 updated_at = VALUES(updated_at)`,
              insertParams,
            )
          }

          for (const { txId, accountId, ptx, rawAmountCents } of toUpdate) {
            const currency = (ptx.iso_currency_code ?? ptx.unofficial_currency_code ?? "USD").toUpperCase()
            const counterpartyName = ptx.counterparties?.[0]?.name ?? null
            yield* db.execute(
              `UPDATE raw_transaction
               SET account_id = ?, pending_transaction_id = ?, raw_amount_cents = ?,
                   currency = ?, date = ?, authorized_date = ?, name = ?, merchant_name = ?,
                   merchant_entity_id = ?, pfc_primary = ?, pfc_detailed = ?, pfc_confidence = ?,
                   payment_channel = ?, pending = ?, counterparty_name = ?, raw_json = ?,
                   removed_at = NULL, updated_at = ?
               WHERE workspace_id = ? AND id = ?`,
              [
                accountId,
                ptx.pending_transaction_id ?? null,
                rawAmountCents,
                currency,
                ptx.date,
                ptx.authorized_date ?? null,
                ptx.name,
                ptx.merchant_name ?? null,
                ptx.merchant_entity_id ?? null,
                ptx.personal_finance_category?.primary ?? null,
                ptx.personal_finance_category?.detailed ?? null,
                ptx.personal_finance_category?.confidence_level ?? null,
                ptx.payment_channel ?? null,
                ptx.pending ? 1 : 0,
                counterpartyName,
                JSON.stringify(ptx),
                now,
                workspaceId,
                txId,
              ],
            )
          }
        }

        // 3. Pending -> Posted reconciliation & automatic overlay/split carry-forward
        if (pendingLinks.length > 0) {
          for (const linkChunk of chunkOf(pendingLinks, 50)) {
            const pendingPlaidIds = linkChunk.map((l) => l.pendingPlaidId)
            const pendingRows = yield* db.query<{
              id: string
              plaid_transaction_id: string
              superseded_by: string | null
            }>(
              `SELECT id, plaid_transaction_id, superseded_by FROM raw_transaction
               WHERE workspace_id = ? AND plaid_transaction_id IN (${pendingPlaidIds.map(() => "?").join(", ")})`,
              [workspaceId, ...pendingPlaidIds],
            )
            const pendingByPlaidId = new Map(pendingRows.rows.map((r) => [r.plaid_transaction_id, r]))

            for (const link of linkChunk) {
              const pendingTx = pendingByPlaidId.get(link.pendingPlaidId)
              if (!pendingTx || pendingTx.superseded_by) continue

              yield* db.transaction((tx) =>
                Effect.gen(function* () {
                  yield* tx.execute(
                    "UPDATE raw_transaction SET superseded_by = ?, updated_at = ? WHERE workspace_id = ? AND id = ?",
                    [link.postedTxId, now, workspaceId, pendingTx.id],
                  )
                  impactedTxIds.add(pendingTx.id)

                  const pendingOverlays = yield* tx.query<{ seq: number; patch_json: unknown }>(
                    `SELECT seq, patch_json FROM tx_overlay
                     WHERE workspace_id = ? AND tx_id = ? AND active = 1 ORDER BY seq ASC`,
                    [workspaceId, pendingTx.id],
                  )
                  const pendingSplits = yield* tx.query<{
                    line_index: number
                    amount_cents: number
                    category: string | null
                    merchant_name: string | null
                    description: string | null
                    tags_json: unknown
                    notes: string | null
                    is_excluded: unknown
                  }>(
                    `SELECT line_index, amount_cents, category, merchant_name, description, tags_json, notes, is_excluded
                     FROM tx_split WHERE workspace_id = ? AND tx_id = ? AND active = 1 ORDER BY line_index ASC`,
                    [workspaceId, pendingTx.id],
                  )

                  if (pendingOverlays.rows.length > 0 || pendingSplits.rows.length > 0) {
                    const carryBatchId = Id.batch()
                    for (const ov of pendingOverlays.rows) {
                      yield* tx.execute(
                        `INSERT INTO tx_overlay (workspace_id, id, batch_id, tx_id, seq, patch_json, active, created_at)
                         VALUES (?, ?, ?, ?, ?, ?, 1, ?)`,
                        [
                          workspaceId,
                          Id.overlay(),
                          carryBatchId,
                          link.postedTxId,
                          toNum(ov.seq),
                          typeof ov.patch_json === "string" ? ov.patch_json : JSON.stringify(ov.patch_json),
                          now,
                        ],
                      )
                    }
                    const postedAccountingCents = link.rawAmountCents === 0 ? 0 : -link.rawAmountCents
                    const splitSum = pendingSplits.rows.reduce((acc, s) => acc + toNum(s.amount_cents), 0)
                    if (pendingSplits.rows.length > 0 && splitSum === postedAccountingCents) {
                      for (const sp of pendingSplits.rows) {
                        yield* tx.execute(
                          `INSERT INTO tx_split
                            (workspace_id, id, batch_id, tx_id, line_index, amount_cents, category,
                             merchant_name, description, tags_json, notes, is_excluded, active, created_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)`,
                          [
                            workspaceId,
                            Id.split(),
                            carryBatchId,
                            link.postedTxId,
                            toNum(sp.line_index),
                            toNum(sp.amount_cents),
                            sp.category,
                            sp.merchant_name,
                            sp.description,
                            typeof sp.tags_json === "string" ? sp.tags_json : JSON.stringify(sp.tags_json),
                            sp.notes,
                            toBool(sp.is_excluded) ? 1 : 0,
                            now,
                          ],
                        )
                      }
                    }
                    yield* tx.execute(
                      `INSERT INTO overlay_batch
                        (workspace_id, id, kind, actor_type, actor_id, client_name, reason, payload_json, affected_count, created_at)
                       VALUES (?, ?, 'pending_carry_forward', 'system', 'system', 'Plaid Sync', ?, ?, 1, ?)`,
                      [
                        workspaceId,
                        carryBatchId,
                        `Carried overlays forward from pending tx ${pendingTx.id} to posted tx ${link.postedTxId}`,
                        JSON.stringify({ from_tx_id: pendingTx.id, to_tx_id: link.postedTxId }),
                        now,
                      ],
                    )
                  }
                }),
              )
            }
          }
        }

        // 4. Bulk soft-delete removed Plaid transactions
        if (pages.removed.length > 0) {
          for (const remChunk of chunkOf(pages.removed, 100)) {
            const foundRes = yield* db.query<{ id: string }>(
              `SELECT id FROM raw_transaction
               WHERE workspace_id = ? AND plaid_transaction_id IN (${remChunk.map(() => "?").join(", ")})`,
              [workspaceId, ...remChunk],
            )
            const foundIds = foundRes.rows.map((r) => r.id)
            if (foundIds.length > 0) {
              yield* db.execute(
                `UPDATE raw_transaction SET removed_at = ?, updated_at = ?
                 WHERE workspace_id = ? AND id IN (${foundIds.map(() => "?").join(", ")})`,
                [now, now, workspaceId, ...foundIds],
              )
              for (const fid of foundIds) impactedTxIds.add(fid)
            }
          }
        }

        // 5. Chunked bulk materialization (50 rows / 4 queries per chunk)
        const mat = yield* rematerializeTransactions(db, workspaceId, Array.from(impactedTxIds))

        // 6. Commit sync_cursor & sync_run completion ONLY once all data is safely persisted
        yield* db.transaction((tx) =>
          Effect.gen(function* () {
            yield* tx.execute(
              `UPDATE raw_item
               SET status = 'healthy', error_code = NULL, error_message = NULL,
                   sync_cursor = ?, last_synced_at = ?, updated_at = ?
               WHERE workspace_id = ? AND item_id = ?`,
              [pages.nextCursor, now, now, workspaceId, itemId],
            )
            yield* tx.execute(
              `UPDATE sync_run
               SET status = 'succeeded', added_count = ?, modified_count = ?, removed_count = ?,
                   rules_applied_count = ?, cursor_after = ?, finished_at = ?
               WHERE workspace_id = ? AND id = ?`,
              [
                pages.added.length,
                pages.modified.length,
                pages.removed.length,
                mat.rulesApplied,
                pages.nextCursor,
                now,
                workspaceId,
                runId,
              ],
            )
          }),
        )

        return {
          sync_run_id: runId,
          item_id: itemId,
          added: pages.added.length,
          modified: pages.modified.length,
          removed: pages.removed.length,
          rules_applied: mat.rulesApplied,
          cursor: pages.nextCursor,
        }
      }),
    )

    if (syncOutcome._tag === "Failure") {
      const err = syncOutcome.failure
      const now = new Date()
      const errCode = err._tag === "PlaidApiError" ? err.code : err._tag
      const errMsg = err.message
      const nextStatus =
        errCode === "ITEM_LOGIN_REQUIRED" || errCode === "PENDING_EXPIRATION"
          ? "needs_reauth"
          : "error"

      yield* db.execute(
        `UPDATE raw_item SET status = ?, error_code = ?, error_message = ?, updated_at = ?
         WHERE workspace_id = ? AND item_id = ?`,
        [nextStatus, errCode, errMsg, now, workspaceId, itemId],
      )
      yield* db.execute(
        `UPDATE sync_run SET status = 'failed', error_code = ?, error_message = ?, finished_at = ?
         WHERE workspace_id = ? AND id = ?`,
        [errCode, errMsg, now, workspaceId, runId],
      )
      return yield* err
    }

    return syncOutcome.success
  })

export const triggerPlaidSync = (
  actor: Actor,
  workspaceId: string,
  input?: { readonly item_id?: string; readonly force_refresh?: boolean },
) =>
  Effect.gen(function* () {
    const ws = yield* assertWorkspaceAccess(actor, workspaceId, "member")
    const db = yield* Database

    if (input?.item_id) {
      const res = yield* syncItemInternal(ws.id, input.item_id, "manual", {
        forceRefresh: input.force_refresh,
      })
      return { results: [res] }
    }

    const items = yield* db.query<{ item_id: string }>(
      "SELECT item_id FROM raw_item WHERE workspace_id = ? AND disconnected_at IS NULL",
      [ws.id],
    )
    const results = []
    for (const item of items.rows) {
      results.push(
        yield* syncItemInternal(ws.id, item.item_id, "manual", {
          forceRefresh: input?.force_refresh,
        }),
      )
    }
    return { results }
  })

export const listPlaidItems = (actor: Actor, workspaceId: string) =>
  Effect.gen(function* () {
    const ws = yield* assertWorkspaceAccess(actor, workspaceId, "viewer")
    const db = yield* Database
    const res = yield* db.query<{
      item_id: string
      institution_id: string
      institution_name: string
      status: string
      error_code: string | null
      error_message: string | null
      last_synced_at: string | null
      consent_expires_at: string | null
      created_at: string
      disconnected_at: string | null
    }>(
      `SELECT item_id, institution_id, institution_name, status, error_code, error_message,
              last_synced_at, consent_expires_at, created_at, disconnected_at
       FROM raw_item
       WHERE workspace_id = ? AND disconnected_at IS NULL
       ORDER BY created_at DESC`,
      [ws.id],
    )
    return res.rows
  })

export const getPlaidItem = (actor: Actor, workspaceId: string, itemId: string) =>
  Effect.gen(function* () {
    const ws = yield* assertWorkspaceAccess(actor, workspaceId, "viewer")
    const db = yield* Database
    const res = yield* db.query<Record<string, unknown>>(
      `SELECT item_id, institution_id, institution_name, status, error_code, error_message,
              sync_cursor, last_synced_at, consent_expires_at, created_at, disconnected_at
       FROM raw_item
       WHERE workspace_id = ? AND item_id = ? LIMIT 1`,
      [ws.id, itemId],
    )
    if (!res.rows[0]) return yield* new NotFoundError({ entity: "plaid_item", id: itemId })
    return res.rows[0]
  })

export const removePlaidItem = (actor: Actor, workspaceId: string, itemId: string) =>
  Effect.gen(function* () {
    const ws = yield* assertWorkspaceAccess(actor, workspaceId, "admin")
    const db = yield* Database
    const plaid = yield* PlaidClient
    const cryptoCfg = yield* CryptoConfig

    const cred = yield* db.query<{ access_token_enc: string }>(
      "SELECT access_token_enc FROM plaid_credential WHERE workspace_id = ? AND item_id = ? AND revoked_at IS NULL LIMIT 1",
      [ws.id, itemId],
    )
    if (!cred.rows[0]) return yield* new NotFoundError({ entity: "plaid_item", id: itemId })

    const accessToken = yield* decryptSecret(cred.rows[0].access_token_enc, cryptoCfg.keysByVersion)
    yield* plaid.itemRemove(accessToken).pipe(Effect.catch(() => Effect.void))

    const now = new Date()
    yield* db.transaction((tx) =>
      Effect.gen(function* () {
        yield* tx.execute(
          "UPDATE plaid_credential SET revoked_at = ? WHERE workspace_id = ? AND item_id = ?",
          [now, ws.id, itemId],
        )
        yield* tx.execute(
          "UPDATE raw_item SET status = 'disconnected', disconnected_at = ?, updated_at = ? WHERE workspace_id = ? AND item_id = ?",
          [now, now, ws.id, itemId],
        )
        yield* tx.execute(
          "UPDATE raw_account SET removed_at = ?, updated_at = ? WHERE workspace_id = ? AND item_id = ?",
          [now, now, ws.id, itemId],
        )
      }),
    )
    return { item_id: itemId, removed: true }
  })

export const listSyncRuns = (
  actor: Actor,
  workspaceId: string,
  input?: { readonly item_id?: string; readonly limit?: number },
) =>
  Effect.gen(function* () {
    const ws = yield* assertWorkspaceAccess(actor, workspaceId, "viewer")
    const db = yield* Database
    const limit = Math.max(1, Math.min(input?.limit ?? 30, 100))
    const filter = input?.item_id ? "AND item_id = ?" : ""
    const params = input?.item_id ? [ws.id, input.item_id] : [ws.id]
    const res = yield* db.query<Record<string, unknown>>(
      `SELECT id, item_id, trigger, status, added_count, modified_count, removed_count,
              rules_applied_count, error_code, error_message, started_at, finished_at
       FROM sync_run
       WHERE workspace_id = ? ${filter}
       ORDER BY started_at DESC
       LIMIT ${limit}`,
      params,
    )
    return res.rows.map((r) => ({
      ...r,
      added_count: toNullableNum(r.added_count) ?? 0,
      modified_count: toNullableNum(r.modified_count) ?? 0,
      removed_count: toNullableNum(r.removed_count) ?? 0,
      rules_applied_count: toNullableNum(r.rules_applied_count) ?? 0,
    }))
  })

export const resolvePlaidWebhookJob = (payload: Record<string, unknown>) =>
  Effect.gen(function* () {
    const itemId = typeof payload.item_id === "string" ? payload.item_id : null
    const webhookType = typeof payload.webhook_type === "string" ? payload.webhook_type : ""
    const webhookCode = typeof payload.webhook_code === "string" ? payload.webhook_code : ""
    if (!itemId) return { action: "ignored" as const }

    const db = yield* Database
    const cred = yield* db.query<{ workspace_id: string }>(
      "SELECT workspace_id FROM plaid_credential WHERE item_id = ? AND revoked_at IS NULL LIMIT 1",
      [itemId],
    )
    const workspaceId = cred.rows[0]?.workspace_id
    if (!workspaceId) return { action: "ignored" as const }

    if (
      webhookType === "ITEM" &&
      (webhookCode === "ERROR" ||
        webhookCode === "PENDING_EXPIRATION" ||
        webhookCode === "USER_PERMISSION_REVOKED")
    ) {
      const errObj = (payload.error ?? {}) as Record<string, unknown>
      const errCode = String(errObj.error_code ?? webhookCode)
      const errMsg = String(errObj.error_message ?? `Plaid item webhook: ${webhookCode}`)
      yield* db.execute(
        `UPDATE raw_item SET status = 'needs_reauth', error_code = ?, error_message = ?, updated_at = ?
         WHERE workspace_id = ? AND item_id = ?`,
        [errCode, errMsg, new Date(), workspaceId, itemId],
      )
      return { action: "item_status_updated" as const, workspaceId, itemId, status: "needs_reauth" }
    }

    if (
      webhookType === "TRANSACTIONS" &&
      (webhookCode === "SYNC_UPDATES_AVAILABLE" ||
        webhookCode === "INITIAL_UPDATE" ||
        webhookCode === "HISTORICAL_UPDATE" ||
        webhookCode === "DEFAULT_UPDATE" ||
        webhookCode === "TRANSACTIONS_REMOVED")
    ) {
      return { action: "sync" as const, workspaceId, itemId }
    }

    return { action: "ignored" as const, workspaceId, itemId }
  })

export const listAllActiveItemsForCron = () =>
  Effect.gen(function* () {
    const db = yield* Database
    const res = yield* db.query<{ workspace_id: string; item_id: string }>(
      `SELECT ri.workspace_id, ri.item_id
       FROM raw_item ri
       INNER JOIN workspace w ON w.id = ri.workspace_id AND w.deleted_at IS NULL
       WHERE ri.disconnected_at IS NULL AND ri.status = 'healthy'`,
    )
    return res.rows
  })
