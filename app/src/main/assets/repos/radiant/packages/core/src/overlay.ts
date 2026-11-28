import { Effect } from "effect"
import type {
  BatchKind,
  ProvenanceMap,
  RuleActionPatch,
  RuleMatchNode,
  TxPatch,
} from "@radiant/database/schema"
import {
  Database,
  parseJsonColumn,
  toBool,
  toNum,
  type DbExecutor,
  type SqlParam,
} from "./db"
import { ConflictError, NotFoundError, ValidationError } from "./errors"
import { Id } from "./id"
import {
  materializeTransaction,
  type ActiveOverlayInput,
  type ActiveRuleInput,
  type EffectiveTxOutput,
  type RawTxInput,
} from "./materializer"
import { validateRuleActions, validateRuleMatch } from "./rule-ast"
import { assertWorkspaceAccess, type Actor } from "./workspace"

export interface SplitLineInput {
  readonly amount_cents: number
  readonly category?: string | null
  readonly merchant_name?: string | null
  readonly description?: string | null
  readonly tags?: ReadonlyArray<string>
  readonly notes?: string | null
  readonly is_excluded?: boolean
}

export interface RuleRecord {
  readonly id: string
  readonly workspace_id: string
  readonly name: string
  readonly description: string | null
  readonly priority: number
  readonly enabled: boolean
  readonly stop_on_match: boolean
  readonly match_json: RuleMatchNode
  readonly actions_json: RuleActionPatch
  readonly version: number
  readonly created_at: string
  readonly updated_at: string
}

let lastSeq = 0
const nextSeq = (): number => {
  lastSeq = Math.max(Date.now() * 1000, lastSeq + 1)
  return lastSeq
}

const placeholders = (n: number): string => Array.from({ length: n }, () => "?").join(", ")

const loadActiveRules = (tx: DbExecutor, workspaceId: string) =>
  Effect.gen(function* () {
    const res = yield* tx.query<{
      id: string
      priority: number
      stop_on_match: unknown
      match_json: unknown
      actions_json: unknown
      created_at: string
    }>(
      `SELECT id, priority, stop_on_match, match_json, actions_json, created_at
       FROM rule
       WHERE workspace_id = ? AND enabled = 1 AND deleted_at IS NULL
       ORDER BY priority ASC, created_at ASC, id ASC`,
      [workspaceId],
    )
    return res.rows.map(
      (r): ActiveRuleInput => ({
        id: r.id,
        priority: toNum(r.priority),
        stop_on_match: toBool(r.stop_on_match),
        match_json: parseJsonColumn<RuleMatchNode>(r.match_json, { all: [] }),
        actions_json: parseJsonColumn<RuleActionPatch>(r.actions_json, {}),
        created_at: String(r.created_at),
      }),
    )
  })

const loadRawTxInputs = (
  tx: DbExecutor,
  workspaceId: string,
  txIds?: ReadonlyArray<string>,
) =>
  Effect.gen(function* () {
    const filterSql = txIds && txIds.length > 0 ? `AND rt.id IN (${placeholders(txIds.length)})` : ""
    const params: Array<SqlParam> = txIds && txIds.length > 0 ? [workspaceId, ...txIds] : [workspaceId]

    const plaidRes = yield* tx.query<{
      id: string
      account_id: string
      account_type: string | null
      account_subtype: string | null
      institution_id: string | null
      raw_amount_cents: number
      currency: string
      date: string
      name: string
      merchant_name: string | null
      pfc_primary: string | null
      pfc_detailed: string | null
      payment_channel: string | null
      pending: unknown
      counterparty_name: string | null
    }>(
      `SELECT
         rt.id, rt.account_id, ra.type AS account_type, ra.subtype AS account_subtype,
         ra.institution_id, rt.raw_amount_cents, rt.currency, rt.date, rt.name,
         rt.merchant_name, rt.pfc_primary, rt.pfc_detailed, rt.payment_channel,
         rt.pending, rt.counterparty_name
       FROM raw_transaction rt
       LEFT JOIN raw_account ra ON ra.workspace_id = rt.workspace_id AND ra.id = rt.account_id
       WHERE rt.workspace_id = ? AND rt.removed_at IS NULL AND rt.superseded_by IS NULL ${filterSql}`,
      params,
    )

    const manualFilterSql = txIds && txIds.length > 0 ? `AND mt.id IN (${placeholders(txIds.length)})` : ""
    const manualRes = yield* tx.query<{
      id: string
      account_id: string | null
      account_type: string | null
      account_subtype: string | null
      institution_id: string | null
      amount_cents: number
      currency: string
      date: string
      merchant_name: string | null
      description: string
      category: string | null
      tags_json: unknown
      notes: string | null
      is_transfer: unknown
      is_excluded: unknown
      custom_fields_json: unknown
    }>(
      `SELECT
         mt.id, mt.account_id, ra.type AS account_type, ra.subtype AS account_subtype,
         ra.institution_id, mt.amount_cents, mt.currency, mt.date, mt.merchant_name,
         mt.description, mt.category, mt.tags_json, mt.notes, mt.is_transfer,
         mt.is_excluded, mt.custom_fields_json
       FROM manual_transaction mt
       LEFT JOIN raw_account ra ON ra.workspace_id = mt.workspace_id AND ra.id = mt.account_id
       WHERE mt.workspace_id = ? AND mt.active = 1 ${manualFilterSql}`,
      params,
    )

    const out = new Map<string, RawTxInput>()
    for (const r of plaidRes.rows) {
      out.set(r.id, {
        id: r.id,
        source: "plaid",
        account_id: r.account_id,
        account_type: r.account_type,
        account_subtype: r.account_subtype,
        institution_id: r.institution_id,
        raw_amount_cents: toNum(r.raw_amount_cents),
        currency: r.currency,
        date: r.date,
        name: r.name,
        merchant_name: r.merchant_name,
        pfc_primary: r.pfc_primary,
        pfc_detailed: r.pfc_detailed,
        payment_channel: r.payment_channel,
        pending: toBool(r.pending),
        counterparty_name: r.counterparty_name,
      })
    }
    for (const m of manualRes.rows) {
      out.set(m.id, {
        id: m.id,
        source: "manual",
        account_id: m.account_id,
        account_type: m.account_type,
        account_subtype: m.account_subtype,
        institution_id: m.institution_id,
        raw_amount_cents: toNum(m.amount_cents),
        currency: m.currency,
        date: m.date,
        name: m.description,
        merchant_name: m.merchant_name,
        pfc_primary: null,
        pfc_detailed: null,
        payment_channel: "manual",
        pending: false,
        counterparty_name: m.merchant_name,
        manual_category: m.category,
        manual_tags: parseJsonColumn<ReadonlyArray<string>>(m.tags_json, []),
        manual_notes: m.notes,
        manual_is_transfer: toBool(m.is_transfer),
        manual_is_excluded: toBool(m.is_excluded),
        manual_custom_fields: parseJsonColumn<Record<string, unknown> | null>(m.custom_fields_json, null),
      })
    }
    return out
  })

const chunkArray = <T>(items: ReadonlyArray<T>, size: number): Array<Array<T>> => {
  const chunks: Array<Array<T>> = []
  for (let i = 0; i < items.length; i += size) chunks.push(items.slice(i, i + size))
  return chunks
}

/**
 * Re-materialize ONLY the specified txIds in O(|txIds|) using chunked bulk SQL
 * (4 round-trips per 50 transactions instead of N*3 sequential round-trips).
 */
export const rematerializeTransactions = (
  tx: DbExecutor,
  workspaceId: string,
  txIds: ReadonlyArray<string>,
) =>
  Effect.gen(function* () {
    const uniqueIds = Array.from(new Set(txIds))
    if (uniqueIds.length === 0) return { rematerialized: 0, rulesApplied: 0 }

    const activeRules = yield* loadActiveRules(tx, workspaceId)
    const now = new Date()
    let rematerialized = 0
    let rulesApplied = 0

    for (const chunk of chunkArray(uniqueIds, 50)) {
      const rawMap = yield* loadRawTxInputs(tx, workspaceId, chunk)
      const inSql = placeholders(chunk.length)

      const overlaysRes = yield* tx.query<{
        id: string
        batch_id: string
        tx_id: string
        seq: number
        patch_json: unknown
      }>(
        `SELECT id, batch_id, tx_id, seq, patch_json
         FROM tx_overlay
         WHERE workspace_id = ? AND active = 1 AND tx_id IN (${inSql})
         ORDER BY seq ASC, id ASC`,
        [workspaceId, ...chunk],
      )
      const overlaysByTx = new Map<string, Array<ActiveOverlayInput>>()
      for (const o of overlaysRes.rows) {
        const list = overlaysByTx.get(o.tx_id) ?? []
        list.push({
          id: o.id,
          batch_id: o.batch_id,
          seq: toNum(o.seq),
          patch_json: parseJsonColumn<TxPatch>(o.patch_json, {}),
        })
        overlaysByTx.set(o.tx_id, list)
      }

      const splitsRes = yield* tx.query<{ tx_id: string }>(
        `SELECT DISTINCT tx_id FROM tx_split
         WHERE workspace_id = ? AND active = 1 AND tx_id IN (${inSql})`,
        [workspaceId, ...chunk],
      )
      const splitTxSet = new Set(splitsRes.rows.map((r) => r.tx_id))

      const effRows: Array<EffectiveTxOutput> = []
      const ruleApps: Array<{ ruleId: string; txId: string }> = []

      for (const txId of chunk) {
        const raw = rawMap.get(txId)
        if (!raw) continue
        const eff = materializeTransaction(
          raw,
          activeRules,
          overlaysByTx.get(txId) ?? [],
          splitTxSet.has(txId),
        )
        effRows.push(eff)
        for (const ruleId of eff.applied_rule_ids_json) {
          ruleApps.push({ ruleId, txId })
        }
      }

      yield* tx.execute(
        `DELETE FROM rule_application WHERE workspace_id = ? AND tx_id IN (${inSql})`,
        [workspaceId, ...chunk],
      )
      yield* tx.execute(
        `DELETE FROM effective_transaction WHERE workspace_id = ? AND id IN (${inSql})`,
        [workspaceId, ...chunk],
      )

      if (effRows.length > 0) {
        const rowPlaceholders = effRows
          .map(() => "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)")
          .join(", ")
        const insertParams: Array<SqlParam> = []
        for (const eff of effRows) {
          insertParams.push(
            workspaceId,
            eff.id,
            eff.source,
            eff.account_id,
            eff.institution_id,
            eff.date,
            eff.raw_date,
            eff.amount_cents,
            eff.raw_amount_cents,
            eff.currency,
            eff.merchant_name,
            eff.description,
            eff.raw_name,
            eff.category,
            eff.category_top,
            eff.raw_category,
            eff.payment_channel,
            eff.pending ? 1 : 0,
            eff.is_transfer ? 1 : 0,
            eff.transfer_pair_id,
            eff.is_excluded ? 1 : 0,
            eff.has_splits ? 1 : 0,
            eff.has_overlay ? 1 : 0,
            eff.recurring_group,
            JSON.stringify(eff.tags_json),
            eff.tags_text,
            eff.notes,
            eff.custom_fields_json ? JSON.stringify(eff.custom_fields_json) : null,
            JSON.stringify(eff.provenance_json),
            JSON.stringify(eff.applied_rule_ids_json),
            now,
          )
        }
        yield* tx.execute(
          `INSERT INTO effective_transaction (
            workspace_id, id, source, account_id, institution_id, date, raw_date,
            amount_cents, raw_amount_cents, currency, merchant_name, description, raw_name,
            category, category_top, raw_category, payment_channel, pending,
            is_transfer, transfer_pair_id, is_excluded, has_splits, has_overlay,
            recurring_group, tags_json, tags_text, notes, custom_fields_json,
            provenance_json, applied_rule_ids_json, updated_at
          ) VALUES ${rowPlaceholders}`,
          insertParams,
        )
        rematerialized += effRows.length
      }

      if (ruleApps.length > 0) {
        for (const appChunk of chunkArray(ruleApps, 100)) {
          const appPlaceholders = appChunk.map(() => "(?, ?, ?, ?)").join(", ")
          const appParams: Array<SqlParam> = []
          for (const a of appChunk) appParams.push(workspaceId, a.ruleId, a.txId, now)
          yield* tx.execute(
            `INSERT INTO rule_application (workspace_id, rule_id, tx_id, applied_at) VALUES ${appPlaceholders}`,
            appParams,
          )
          rulesApplied += appChunk.length
        }
      }
    }

    return { rematerialized, rulesApplied }
  })

const insertBatch = (
  tx: DbExecutor,
  input: {
    readonly workspaceId: string
    readonly id: string
    readonly kind: BatchKind
    readonly actor: Actor
    readonly reason?: string
    readonly payload?: Record<string, unknown>
    readonly affectedCount: number
  },
) =>
  tx.execute(
    `INSERT INTO overlay_batch
      (workspace_id, id, kind, actor_type, actor_id, client_name, reason, payload_json, affected_count, created_at)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
    [
      input.workspaceId,
      input.id,
      input.kind,
      input.actor.type,
      input.actor.userId,
      input.actor.clientName,
      input.reason ?? null,
      input.payload ? JSON.stringify(input.payload) : null,
      input.affectedCount,
      new Date(),
    ],
  )

// ── Transaction Overlays, Splits, Manual Entries & Reset ────────────────────

export const applyTransactionOverlay = (
  actor: Actor,
  workspaceId: string,
  input: {
    readonly tx_ids: ReadonlyArray<string>
    readonly patch: TxPatch
    readonly reason?: string
    readonly dry_run?: boolean
  },
) =>
  Effect.gen(function* () {
    const ws = yield* assertWorkspaceAccess(actor, workspaceId, "member")
    const uniqueIds = Array.from(new Set(input.tx_ids))
    if (uniqueIds.length === 0) {
      return yield* new ValidationError({ message: "At least one transaction ID is required", field: "tx_ids" })
    }
    if (uniqueIds.length > 2000) {
      return yield* new ValidationError({ message: "Maximum 2,000 transactions per overlay batch", field: "tx_ids" })
    }

    const db = yield* Database

    if (input.dry_run) {
      const existing = yield* db.query<{ id: string; merchant_name: string | null; category: string | null; amount_cents: number }>(
        `SELECT id, merchant_name, category, amount_cents FROM effective_transaction
         WHERE workspace_id = ? AND id IN (${placeholders(uniqueIds.length)})`,
        [ws.id, ...uniqueIds],
      )
      return {
        dry_run: true as const,
        matched_count: existing.rows.length,
        sample: existing.rows.slice(0, 20),
        patch: input.patch,
      }
    }

    const batchId = Id.batch()
    const seq = nextSeq()

    const result = yield* db.transaction((tx) =>
      Effect.gen(function* () {
        const existing = yield* tx.query<{ id: string }>(
          `SELECT id FROM effective_transaction
           WHERE workspace_id = ? AND id IN (${placeholders(uniqueIds.length)})`,
          [ws.id, ...uniqueIds],
        )
        const foundIds = existing.rows.map((r) => r.id)
        if (foundIds.length === 0) {
          return yield* new NotFoundError({ entity: "transaction", message: "None of the specified transactions exist" })
        }

        const now = new Date()
        for (const txId of foundIds) {
          yield* tx.execute(
            `INSERT INTO tx_overlay (workspace_id, id, batch_id, tx_id, seq, patch_json, active, created_at)
             VALUES (?, ?, ?, ?, ?, ?, 1, ?)`,
            [ws.id, Id.overlay(), batchId, txId, seq, JSON.stringify(input.patch), now],
          )
        }

        yield* insertBatch(tx, {
          workspaceId: ws.id,
          id: batchId,
          kind: "tx_overlay",
          actor,
          reason: input.reason,
          payload: { tx_ids: foundIds, patch: input.patch },
          affectedCount: foundIds.length,
        })

        yield* rematerializeTransactions(tx, ws.id, foundIds)
        return { dry_run: false as const, batch_id: batchId, affected_count: foundIds.length, tx_ids: foundIds }
      }),
    )

    return result
  })

export const setTransactionSplits = (
  actor: Actor,
  workspaceId: string,
  input: {
    readonly tx_id: string
    readonly splits: ReadonlyArray<SplitLineInput>
    readonly reason?: string
  },
) =>
  Effect.gen(function* () {
    const ws = yield* assertWorkspaceAccess(actor, workspaceId, "member")
    if (input.splits.length < 2) {
      return yield* new ValidationError({ message: "Splits must contain at least 2 lines", field: "splits" })
    }

    const db = yield* Database
    const batchId = Id.batch()

    return yield* db.transaction((tx) =>
      Effect.gen(function* () {
        const parentRes = yield* tx.query<{ id: string; amount_cents: number }>(
          "SELECT id, amount_cents FROM effective_transaction WHERE workspace_id = ? AND id = ? LIMIT 1",
          [ws.id, input.tx_id],
        )
        const parent = parentRes.rows[0]
        if (!parent) return yield* new NotFoundError({ entity: "transaction", id: input.tx_id })

        const parentCents = toNum(parent.amount_cents)
        const splitSum = input.splits.reduce((acc, s) => acc + Math.trunc(s.amount_cents), 0)
        if (splitSum !== parentCents) {
          return yield* new ValidationError({
            message: `Split amounts sum to ${splitSum} cents, which must equal parent amount ${parentCents} cents`,
            field: "splits",
          })
        }

        const prevSplits = yield* tx.query<{ id: string }>(
          "SELECT id FROM tx_split WHERE workspace_id = ? AND tx_id = ? AND active = 1",
          [ws.id, input.tx_id],
        )
        const replacedIds = prevSplits.rows.map((r) => r.id)
        if (replacedIds.length > 0) {
          yield* tx.execute(
            "UPDATE tx_split SET active = 0 WHERE workspace_id = ? AND tx_id = ? AND active = 1",
            [ws.id, input.tx_id],
          )
        }

        const now = new Date()
        const createdIds: Array<string> = []
        for (let i = 0; i < input.splits.length; i++) {
          const line = input.splits[i]!
          const sid = Id.split()
          createdIds.push(sid)
          yield* tx.execute(
            `INSERT INTO tx_split
              (workspace_id, id, batch_id, tx_id, line_index, amount_cents, category,
               merchant_name, description, tags_json, notes, is_excluded, active, created_at)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)`,
            [
              ws.id,
              sid,
              batchId,
              input.tx_id,
              i,
              Math.trunc(line.amount_cents),
              line.category ?? null,
              line.merchant_name ?? null,
              line.description ?? null,
              JSON.stringify(line.tags ?? []),
              line.notes ?? null,
              line.is_excluded ? 1 : 0,
              now,
            ],
          )
        }

        yield* insertBatch(tx, {
          workspaceId: ws.id,
          id: batchId,
          kind: "tx_split",
          actor,
          reason: input.reason,
          payload: { tx_id: input.tx_id, created_split_ids: createdIds, replaced_split_ids: replacedIds },
          affectedCount: 1,
        })

        yield* rematerializeTransactions(tx, ws.id, [input.tx_id])
        return { batch_id: batchId, tx_id: input.tx_id, split_ids: createdIds }
      }),
    )
  })

export const clearTransactionSplits = (
  actor: Actor,
  workspaceId: string,
  txId: string,
  reason?: string,
) =>
  Effect.gen(function* () {
    const ws = yield* assertWorkspaceAccess(actor, workspaceId, "member")
    const db = yield* Database
    const batchId = Id.batch()

    return yield* db.transaction((tx) =>
      Effect.gen(function* () {
        const prev = yield* tx.query<{ id: string }>(
          "SELECT id FROM tx_split WHERE workspace_id = ? AND tx_id = ? AND active = 1",
          [ws.id, txId],
        )
        const clearedIds = prev.rows.map((r) => r.id)
        if (clearedIds.length === 0) {
          return { batch_id: null, tx_id: txId, cleared_count: 0 }
        }
        yield* tx.execute(
          "UPDATE tx_split SET active = 0 WHERE workspace_id = ? AND tx_id = ? AND active = 1",
          [ws.id, txId],
        )
        yield* insertBatch(tx, {
          workspaceId: ws.id,
          id: batchId,
          kind: "tx_split",
          actor,
          reason: reason ?? "Cleared splits",
          payload: { tx_id: txId, created_split_ids: [], replaced_split_ids: clearedIds },
          affectedCount: 1,
        })
        yield* rematerializeTransactions(tx, ws.id, [txId])
        return { batch_id: batchId, tx_id: txId, cleared_count: clearedIds.length }
      }),
    )
  })

export const resetTransactions = (
  actor: Actor,
  workspaceId: string,
  txIds: ReadonlyArray<string>,
  reason?: string,
) =>
  Effect.gen(function* () {
    const ws = yield* assertWorkspaceAccess(actor, workspaceId, "member")
    const uniqueIds = Array.from(new Set(txIds))
    if (uniqueIds.length === 0) {
      return yield* new ValidationError({ message: "At least one transaction ID is required", field: "tx_ids" })
    }
    const db = yield* Database
    const batchId = Id.batch()

    return yield* db.transaction((tx) =>
      Effect.gen(function* () {
        const inSql = placeholders(uniqueIds.length)
        const activeOverlays = yield* tx.query<{ id: string; tx_id: string }>(
          `SELECT id, tx_id FROM tx_overlay WHERE workspace_id = ? AND active = 1 AND tx_id IN (${inSql})`,
          [ws.id, ...uniqueIds],
        )
        const activeSplits = yield* tx.query<{ id: string; tx_id: string }>(
          `SELECT id, tx_id FROM tx_split WHERE workspace_id = ? AND active = 1 AND tx_id IN (${inSql})`,
          [ws.id, ...uniqueIds],
        )
        const overlayIds = activeOverlays.rows.map((r) => r.id)
        const splitIds = activeSplits.rows.map((r) => r.id)
        const touchedTxIds = Array.from(
          new Set([...activeOverlays.rows.map((r) => r.tx_id), ...activeSplits.rows.map((r) => r.tx_id)]),
        )

        if (overlayIds.length > 0) {
          yield* tx.execute(
            `UPDATE tx_overlay SET active = 0 WHERE workspace_id = ? AND id IN (${placeholders(overlayIds.length)})`,
            [ws.id, ...overlayIds],
          )
        }
        if (splitIds.length > 0) {
          yield* tx.execute(
            `UPDATE tx_split SET active = 0 WHERE workspace_id = ? AND id IN (${placeholders(splitIds.length)})`,
            [ws.id, ...splitIds],
          )
        }

        yield* insertBatch(tx, {
          workspaceId: ws.id,
          id: batchId,
          kind: "tx_reset",
          actor,
          reason: reason ?? "Reset manual overlays",
          payload: { tx_ids: touchedTxIds, deactivated_overlay_ids: overlayIds, deactivated_split_ids: splitIds },
          affectedCount: touchedTxIds.length,
        })

        yield* rematerializeTransactions(tx, ws.id, touchedTxIds)
        return { batch_id: batchId, affected_count: touchedTxIds.length }
      }),
    )
  })

export const createManualTransaction = (
  actor: Actor,
  workspaceId: string,
  input: {
    readonly date: string
    readonly amount_cents: number
    readonly description: string
    readonly account_id?: string | null
    readonly currency?: string
    readonly merchant_name?: string | null
    readonly category?: string | null
    readonly tags?: ReadonlyArray<string>
    readonly notes?: string | null
    readonly is_transfer?: boolean
    readonly is_excluded?: boolean
    readonly custom_fields?: Record<string, unknown> | null
    readonly reason?: string
  },
) =>
  Effect.gen(function* () {
    const ws = yield* assertWorkspaceAccess(actor, workspaceId, "member")
    if (!/^\d{4}-\d{2}-\d{2}$/.test(input.date)) {
      return yield* new ValidationError({ message: "date must be YYYY-MM-DD", field: "date" })
    }
    const db = yield* Database
    const txId = Id.tx()
    const batchId = Id.batch()
    const now = new Date()

    return yield* db.transaction((tx) =>
      Effect.gen(function* () {
        yield* tx.execute(
          `INSERT INTO manual_transaction
            (workspace_id, id, batch_id, account_id, date, amount_cents, currency, merchant_name,
             description, category, tags_json, notes, is_transfer, is_excluded, custom_fields_json, active, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)`,
          [
            ws.id,
            txId,
            batchId,
            input.account_id ?? null,
            input.date,
            Math.trunc(input.amount_cents),
            (input.currency ?? ws.currency).toUpperCase(),
            input.merchant_name ?? null,
            input.description.trim(),
            input.category ?? null,
            JSON.stringify(input.tags ?? []),
            input.notes ?? null,
            input.is_transfer ? 1 : 0,
            input.is_excluded ? 1 : 0,
            input.custom_fields ? JSON.stringify(input.custom_fields) : null,
            now,
          ],
        )
        yield* insertBatch(tx, {
          workspaceId: ws.id,
          id: batchId,
          kind: "tx_manual",
          actor,
          reason: input.reason ?? `Manual transaction: ${input.description}`,
          payload: { tx_id: txId },
          affectedCount: 1,
        })
        yield* rematerializeTransactions(tx, ws.id, [txId])
        return { batch_id: batchId, tx_id: txId }
      }),
    )
  })

export const setAccountOverlay = (
  actor: Actor,
  workspaceId: string,
  input: {
    readonly account_id: string
    readonly nickname?: string | null
    readonly account_group?: string | null
    readonly owner_label?: string | null
    readonly is_active?: boolean | null
    readonly is_hidden?: boolean | null
    readonly is_excluded_from_net_worth?: boolean | null
    readonly notes?: string | null
    readonly reason?: string
  },
) =>
  Effect.gen(function* () {
    const ws = yield* assertWorkspaceAccess(actor, workspaceId, "member")
    const db = yield* Database
    const batchId = Id.batch()
    const overlayId = Id.overlay()

    return yield* db.transaction((tx) =>
      Effect.gen(function* () {
        const acc = yield* tx.query<{ id: string }>(
          "SELECT id FROM raw_account WHERE workspace_id = ? AND id = ? LIMIT 1",
          [ws.id, input.account_id],
        )
        if (!acc.rows[0]) {
          return yield* new NotFoundError({ entity: "account", id: input.account_id })
        }

        const resolvedHidden =
          input.is_active !== undefined && input.is_active !== null
            ? !input.is_active
            : input.is_hidden

        yield* tx.execute(
          `INSERT INTO account_overlay
            (workspace_id, id, batch_id, account_id, seq, nickname, account_group, owner_label,
             is_hidden, is_excluded_from_net_worth, notes, active, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)`,
          [
            ws.id,
            overlayId,
            batchId,
            input.account_id,
            nextSeq(),
            input.nickname ?? null,
            input.account_group ?? null,
            input.owner_label ?? null,
            resolvedHidden === undefined || resolvedHidden === null ? null : resolvedHidden ? 1 : 0,
            input.is_excluded_from_net_worth === undefined || input.is_excluded_from_net_worth === null
              ? null
              : input.is_excluded_from_net_worth
                ? 1
                : 0,
            input.notes ?? null,
            new Date(),
          ],
        )

        yield* insertBatch(tx, {
          workspaceId: ws.id,
          id: batchId,
          kind: "account_overlay",
          actor,
          reason: input.reason ?? "Updated account overlay",
          payload: { account_id: input.account_id, overlay_id: overlayId },
          affectedCount: 1,
        })

        return { batch_id: batchId, account_id: input.account_id, overlay_id: overlayId }
      }),
    )
  })

// ── Rules Engine CRUD, Preview & Retroactive Application ────────────────────

const rowToRule = (r: Record<string, unknown>): RuleRecord => ({
  id: String(r.id),
  workspace_id: String(r.workspace_id),
  name: String(r.name),
  description: r.description ? String(r.description) : null,
  priority: toNum(r.priority),
  enabled: toBool(r.enabled),
  stop_on_match: toBool(r.stop_on_match),
  match_json: parseJsonColumn<RuleMatchNode>(r.match_json, { all: [] }),
  actions_json: parseJsonColumn<RuleActionPatch>(r.actions_json, {}),
  version: toNum(r.version),
  created_at: String(r.created_at),
  updated_at: String(r.updated_at),
})

export const listRules = (actor: Actor, workspaceId: string) =>
  Effect.gen(function* () {
    const ws = yield* assertWorkspaceAccess(actor, workspaceId, "viewer")
    const db = yield* Database
    const res = yield* db.query<Record<string, unknown>>(
      `SELECT r.*, (SELECT COUNT(*) FROM rule_application ra WHERE ra.workspace_id = r.workspace_id AND ra.rule_id = r.id) AS match_count
       FROM rule r
       WHERE r.workspace_id = ? AND r.deleted_at IS NULL
       ORDER BY r.priority ASC, r.created_at ASC`,
      [ws.id],
    )
    return res.rows.map((r) => ({ ...rowToRule(r), match_count: toNum(r.match_count) }))
  })

export const getRule = (actor: Actor, workspaceId: string, ruleId: string) =>
  Effect.gen(function* () {
    const ws = yield* assertWorkspaceAccess(actor, workspaceId, "viewer")
    const db = yield* Database
    const res = yield* db.query<Record<string, unknown>>(
      "SELECT * FROM rule WHERE workspace_id = ? AND id = ? AND deleted_at IS NULL LIMIT 1",
      [ws.id, ruleId],
    )
    if (!res.rows[0]) return yield* new NotFoundError({ entity: "rule", id: ruleId })
    return rowToRule(res.rows[0])
  })

export const previewRule = (
  actor: Actor,
  workspaceId: string,
  input: {
    readonly match: unknown
    readonly actions: unknown
    readonly priority?: number
    readonly stop_on_match?: boolean
    readonly sample_limit?: number
  },
) =>
  Effect.gen(function* () {
    const ws = yield* assertWorkspaceAccess(actor, workspaceId, "viewer")
    const match = yield* validateRuleMatch(input.match)
    const actions = yield* validateRuleActions(input.actions)
    const db = yield* Database

    const existingRules = yield* loadActiveRules(db, ws.id)
    const rawMap = yield* loadRawTxInputs(db, ws.id)
    const candidateRule: ActiveRuleInput = {
      id: "rul_preview",
      priority: input.priority ?? 100,
      stop_on_match: input.stop_on_match ?? false,
      match_json: match,
      actions_json: actions,
      created_at: new Date().toISOString(),
    }

    const withCandidate = [...existingRules, candidateRule]
    const sampleLimit = Math.max(1, Math.min(input.sample_limit ?? 20, 100))
    let matchedCount = 0
    const samples: Array<{
      readonly id: string
      readonly date: string
      readonly raw_name: string
      readonly amount_cents: number
      readonly before: { readonly category: string | null; readonly merchant_name: string | null; readonly tags: ReadonlyArray<string>; readonly is_transfer: boolean; readonly is_excluded: boolean }
      readonly after: { readonly category: string | null; readonly merchant_name: string | null; readonly tags: ReadonlyArray<string>; readonly is_transfer: boolean; readonly is_excluded: boolean }
    }> = []

    for (const raw of rawMap.values()) {
      const after = materializeTransaction(raw, withCandidate, [], false)
      if (!after.applied_rule_ids_json.includes("rul_preview")) continue
      matchedCount++
      if (samples.length < sampleLimit) {
        const before = materializeTransaction(raw, existingRules, [], false)
        samples.push({
          id: raw.id,
          date: raw.date,
          raw_name: raw.name,
          amount_cents: after.amount_cents,
          before: {
            category: before.category,
            merchant_name: before.merchant_name,
            tags: before.tags_json,
            is_transfer: before.is_transfer,
            is_excluded: before.is_excluded,
          },
          after: {
            category: after.category,
            merchant_name: after.merchant_name,
            tags: after.tags_json,
            is_transfer: after.is_transfer,
            is_excluded: after.is_excluded,
          },
        })
      }
    }

    return { matched_count: matchedCount, total_scanned: rawMap.size, samples }
  })

const findMatchingTxIdsForRule = (
  tx: DbExecutor,
  workspaceId: string,
  candidate: ActiveRuleInput,
) =>
  Effect.gen(function* () {
    const rawMap = yield* loadRawTxInputs(tx, workspaceId)
    const matched: Array<string> = []
    for (const raw of rawMap.values()) {
      const eff = materializeTransaction(raw, [candidate], [], false)
      if (eff.applied_rule_ids_json.includes(candidate.id)) matched.push(raw.id)
    }
    return matched
  })

export const createRule = (
  actor: Actor,
  workspaceId: string,
  input: {
    readonly name: string
    readonly description?: string | null
    readonly priority?: number
    readonly enabled?: boolean
    readonly stop_on_match?: boolean
    readonly match: unknown
    readonly actions: unknown
    readonly apply_retroactively?: boolean
    readonly reason?: string
  },
) =>
  Effect.gen(function* () {
    const ws = yield* assertWorkspaceAccess(actor, workspaceId, "member")
    const name = input.name.trim()
    if (name.length < 1 || name.length > 160) {
      return yield* new ValidationError({ message: "Rule name must be 1..160 characters", field: "name" })
    }
    const match = yield* validateRuleMatch(input.match)
    const actions = yield* validateRuleActions(input.actions)
    const enabled = input.enabled ?? true
    const priority = Math.trunc(input.priority ?? 100)
    const stopOnMatch = input.stop_on_match ?? false
    const applyRetro = input.apply_retroactively ?? true

    const db = yield* Database
    const ruleId = Id.rule()
    const batchId = Id.batch()
    const now = new Date()

    return yield* db.transaction((tx) =>
      Effect.gen(function* () {
        yield* tx.execute(
          `INSERT INTO rule
            (workspace_id, id, name, description, priority, enabled, stop_on_match,
             match_json, actions_json, version, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)`,
          [
            ws.id,
            ruleId,
            name,
            input.description ?? null,
            priority,
            enabled ? 1 : 0,
            stopOnMatch ? 1 : 0,
            JSON.stringify(match),
            JSON.stringify(actions),
            now,
            now,
          ],
        )

        const affectedTxIds =
          enabled && applyRetro
            ? yield* findMatchingTxIdsForRule(tx, ws.id, {
                id: ruleId,
                priority,
                stop_on_match: stopOnMatch,
                match_json: match,
                actions_json: actions,
                created_at: now.toISOString(),
              })
            : []

        if (affectedTxIds.length > 0) {
          yield* rematerializeTransactions(tx, ws.id, affectedTxIds)
        }

        yield* insertBatch(tx, {
          workspaceId: ws.id,
          id: batchId,
          kind: "rule_create",
          actor,
          reason: input.reason ?? `Created rule '${name}'`,
          payload: { rule_id: ruleId, after: { name, priority, enabled, stop_on_match: stopOnMatch, match, actions } },
          affectedCount: affectedTxIds.length,
        })

        return { batch_id: batchId, rule_id: ruleId, affected_count: affectedTxIds.length }
      }),
    )
  })

export const updateRule = (
  actor: Actor,
  workspaceId: string,
  ruleId: string,
  input: {
    readonly name?: string
    readonly description?: string | null
    readonly priority?: number
    readonly enabled?: boolean
    readonly stop_on_match?: boolean
    readonly match?: unknown
    readonly actions?: unknown
    readonly reason?: string
  },
) =>
  Effect.gen(function* () {
    const ws = yield* assertWorkspaceAccess(actor, workspaceId, "member")
    const nextMatch = input.match !== undefined ? yield* validateRuleMatch(input.match) : undefined
    const nextActions = input.actions !== undefined ? yield* validateRuleActions(input.actions) : undefined

    const db = yield* Database
    const batchId = Id.batch()

    return yield* db.transaction((tx) =>
      Effect.gen(function* () {
        const curRes = yield* tx.query<Record<string, unknown>>(
          "SELECT * FROM rule WHERE workspace_id = ? AND id = ? AND deleted_at IS NULL LIMIT 1",
          [ws.id, ruleId],
        )
        if (!curRes.rows[0]) return yield* new NotFoundError({ entity: "rule", id: ruleId })
        const before = rowToRule(curRes.rows[0])

        const prevApps = yield* tx.query<{ tx_id: string }>(
          "SELECT tx_id FROM rule_application WHERE workspace_id = ? AND rule_id = ?",
          [ws.id, ruleId],
        )
        const prevTxIds = prevApps.rows.map((r) => r.tx_id)

        const after = {
          name: input.name !== undefined ? input.name.trim() : before.name,
          description: input.description !== undefined ? input.description : before.description,
          priority: input.priority !== undefined ? Math.trunc(input.priority) : before.priority,
          enabled: input.enabled !== undefined ? input.enabled : before.enabled,
          stop_on_match: input.stop_on_match !== undefined ? input.stop_on_match : before.stop_on_match,
          match_json: nextMatch ?? before.match_json,
          actions_json: nextActions ?? before.actions_json,
          version: before.version + 1,
        }

        const now = new Date()
        yield* tx.execute(
          `UPDATE rule
           SET name = ?, description = ?, priority = ?, enabled = ?, stop_on_match = ?,
               match_json = ?, actions_json = ?, version = ?, updated_at = ?
           WHERE workspace_id = ? AND id = ?`,
          [
            after.name,
            after.description,
            after.priority,
            after.enabled ? 1 : 0,
            after.stop_on_match ? 1 : 0,
            JSON.stringify(after.match_json),
            JSON.stringify(after.actions_json),
            after.version,
            now,
            ws.id,
            ruleId,
          ],
        )

        const newTxIds = after.enabled
          ? yield* findMatchingTxIdsForRule(tx, ws.id, {
              id: ruleId,
              priority: after.priority,
              stop_on_match: after.stop_on_match,
              match_json: after.match_json,
              actions_json: after.actions_json,
              created_at: before.created_at,
            })
          : []

        const impacted = Array.from(new Set([...prevTxIds, ...newTxIds]))
        if (impacted.length > 0) {
          yield* rematerializeTransactions(tx, ws.id, impacted)
        }

        yield* insertBatch(tx, {
          workspaceId: ws.id,
          id: batchId,
          kind: "rule_update",
          actor,
          reason: input.reason ?? `Updated rule '${after.name}'`,
          payload: { rule_id: ruleId, before, after },
          affectedCount: impacted.length,
        })

        return { batch_id: batchId, rule_id: ruleId, version: after.version, affected_count: impacted.length }
      }),
    )
  })

export const deleteRule = (
  actor: Actor,
  workspaceId: string,
  ruleId: string,
  reason?: string,
) =>
  Effect.gen(function* () {
    const ws = yield* assertWorkspaceAccess(actor, workspaceId, "member")
    const db = yield* Database
    const batchId = Id.batch()

    return yield* db.transaction((tx) =>
      Effect.gen(function* () {
        const curRes = yield* tx.query<Record<string, unknown>>(
          "SELECT * FROM rule WHERE workspace_id = ? AND id = ? AND deleted_at IS NULL LIMIT 1",
          [ws.id, ruleId],
        )
        if (!curRes.rows[0]) return yield* new NotFoundError({ entity: "rule", id: ruleId })
        const before = rowToRule(curRes.rows[0])

        const prevApps = yield* tx.query<{ tx_id: string }>(
          "SELECT tx_id FROM rule_application WHERE workspace_id = ? AND rule_id = ?",
          [ws.id, ruleId],
        )
        const impacted = prevApps.rows.map((r) => r.tx_id)

        const now = new Date()
        yield* tx.execute(
          "UPDATE rule SET deleted_at = ?, enabled = 0, updated_at = ? WHERE workspace_id = ? AND id = ?",
          [now, now, ws.id, ruleId],
        )

        if (impacted.length > 0) {
          yield* rematerializeTransactions(tx, ws.id, impacted)
        }

        yield* insertBatch(tx, {
          workspaceId: ws.id,
          id: batchId,
          kind: "rule_delete",
          actor,
          reason: reason ?? `Deleted rule '${before.name}'`,
          payload: { rule_id: ruleId, before },
          affectedCount: impacted.length,
        })

        return { batch_id: batchId, rule_id: ruleId, affected_count: impacted.length }
      }),
    )
  })

export const reorderRules = (
  actor: Actor,
  workspaceId: string,
  orderedRuleIds: ReadonlyArray<string>,
  reason?: string,
) =>
  Effect.gen(function* () {
    const ws = yield* assertWorkspaceAccess(actor, workspaceId, "member")
    const db = yield* Database
    const batchId = Id.batch()

    return yield* db.transaction((tx) =>
      Effect.gen(function* () {
        const current = yield* tx.query<{ id: string; priority: number }>(
          "SELECT id, priority FROM rule WHERE workspace_id = ? AND deleted_at IS NULL",
          [ws.id],
        )
        const beforePriorities = Object.fromEntries(current.rows.map((r) => [r.id, toNum(r.priority)]))
        const afterPriorities: Record<string, number> = {}
        const now = new Date()

        for (let i = 0; i < orderedRuleIds.length; i++) {
          const id = orderedRuleIds[i]!
          const prio = (i + 1) * 10
          afterPriorities[id] = prio
          yield* tx.execute(
            "UPDATE rule SET priority = ?, updated_at = ? WHERE workspace_id = ? AND id = ?",
            [prio, now, ws.id, id],
          )
        }

        const apps = yield* tx.query<{ tx_id: string }>(
          "SELECT DISTINCT tx_id FROM rule_application WHERE workspace_id = ?",
          [ws.id],
        )
        const impacted = apps.rows.map((r) => r.tx_id)
        if (impacted.length > 0) {
          yield* rematerializeTransactions(tx, ws.id, impacted)
        }

        yield* insertBatch(tx, {
          workspaceId: ws.id,
          id: batchId,
          kind: "rule_reorder",
          actor,
          reason: reason ?? "Reordered rules",
          payload: { before: beforePriorities, after: afterPriorities },
          affectedCount: impacted.length,
        })

        return { batch_id: batchId, affected_count: impacted.length }
      }),
    )
  })

export const reapplyAllRules = (actor: Actor, workspaceId: string) =>
  Effect.gen(function* () {
    const ws = yield* assertWorkspaceAccess(actor, workspaceId, "admin")
    const db = yield* Database
    return yield* db.transaction((tx) =>
      Effect.gen(function* () {
        const rawMap = yield* loadRawTxInputs(tx, ws.id)
        const allIds = Array.from(rawMap.keys())
        return yield* rematerializeTransactions(tx, ws.id, allIds)
      }),
    )
  })

// ── Audit History & Non-LIFO O(affected) Undo / Redo ────────────────────────

export const listOverlayBatches = (
  actor: Actor,
  workspaceId: string,
  input?: { readonly limit?: number; readonly include_reverted?: boolean },
) =>
  Effect.gen(function* () {
    const ws = yield* assertWorkspaceAccess(actor, workspaceId, "viewer")
    const db = yield* Database
    const limit = Math.max(1, Math.min(input?.limit ?? 50, 200))
    const filter = input?.include_reverted === false ? "AND reverted_at IS NULL" : ""
    const res = yield* db.query<Record<string, unknown>>(
      `SELECT id, kind, actor_type, actor_id, client_name, reason, affected_count, created_at, reverted_at, reverted_by
       FROM overlay_batch
       WHERE workspace_id = ? ${filter}
       ORDER BY created_at DESC, id DESC
       LIMIT ${limit}`,
      [ws.id],
    )
    return res.rows
  })

export const getOverlayBatch = (actor: Actor, workspaceId: string, batchId: string) =>
  Effect.gen(function* () {
    const ws = yield* assertWorkspaceAccess(actor, workspaceId, "viewer")
    const db = yield* Database
    const res = yield* db.query<Record<string, unknown>>(
      "SELECT * FROM overlay_batch WHERE workspace_id = ? AND id = ? LIMIT 1",
      [ws.id, batchId],
    )
    const row = res.rows[0]
    if (!row) return yield* new NotFoundError({ entity: "overlay_batch", id: batchId })
    return {
      ...row,
      payload_json: parseJsonColumn<Record<string, unknown> | null>(row.payload_json, null),
    }
  })

export const undoOverlayBatch = (actor: Actor, workspaceId: string, batchId: string) =>
  Effect.gen(function* () {
    const ws = yield* assertWorkspaceAccess(actor, workspaceId, "member")
    const db = yield* Database

    return yield* db.transaction((tx) =>
      Effect.gen(function* () {
        const res = yield* tx.query<{
          id: string
          kind: BatchKind
          payload_json: unknown
          reverted_at: string | null
        }>(
          "SELECT id, kind, payload_json, reverted_at FROM overlay_batch WHERE workspace_id = ? AND id = ? LIMIT 1",
          [ws.id, batchId],
        )
        const batch = res.rows[0]
        if (!batch) return yield* new NotFoundError({ entity: "overlay_batch", id: batchId })
        if (batch.reverted_at) {
          return yield* new ConflictError({ message: `Batch ${batchId} is already reverted` })
        }

        const payload = parseJsonColumn<Record<string, unknown>>(batch.payload_json, {})
        const now = new Date()
        let impactedTxIds: Array<string> = []

        switch (batch.kind) {
          case "tx_overlay":
          case "pending_carry_forward": {
            const ovs = yield* tx.query<{ tx_id: string }>(
              "SELECT DISTINCT tx_id FROM tx_overlay WHERE workspace_id = ? AND batch_id = ?",
              [ws.id, batchId],
            )
            impactedTxIds = ovs.rows.map((r) => r.tx_id)
            yield* tx.execute(
              "UPDATE tx_overlay SET active = 0 WHERE workspace_id = ? AND batch_id = ?",
              [ws.id, batchId],
            )
            break
          }
          case "tx_split": {
            const txId = String(payload.tx_id ?? "")
            if (txId) impactedTxIds = [txId]
            yield* tx.execute(
              "UPDATE tx_split SET active = 0 WHERE workspace_id = ? AND batch_id = ?",
              [ws.id, batchId],
            )
            const replacedIds = Array.isArray(payload.replaced_split_ids)
              ? (payload.replaced_split_ids as ReadonlyArray<string>)
              : []
            if (replacedIds.length > 0) {
              yield* tx.execute(
                `UPDATE tx_split SET active = 1 WHERE workspace_id = ? AND id IN (${placeholders(replacedIds.length)})`,
                [ws.id, ...replacedIds],
              )
            }
            break
          }
          case "tx_reset": {
            const overlayIds = Array.isArray(payload.deactivated_overlay_ids)
              ? (payload.deactivated_overlay_ids as ReadonlyArray<string>)
              : []
            const splitIds = Array.isArray(payload.deactivated_split_ids)
              ? (payload.deactivated_split_ids as ReadonlyArray<string>)
              : []
            if (overlayIds.length > 0) {
              yield* tx.execute(
                `UPDATE tx_overlay SET active = 1 WHERE workspace_id = ? AND id IN (${placeholders(overlayIds.length)})`,
                [ws.id, ...overlayIds],
              )
            }
            if (splitIds.length > 0) {
              yield* tx.execute(
                `UPDATE tx_split SET active = 1 WHERE workspace_id = ? AND id IN (${placeholders(splitIds.length)})`,
                [ws.id, ...splitIds],
              )
            }
            impactedTxIds = Array.isArray(payload.tx_ids) ? (payload.tx_ids as Array<string>) : []
            break
          }
          case "tx_manual": {
            const txId = String(payload.tx_id ?? "")
            if (txId) {
              impactedTxIds = [txId]
              yield* tx.execute(
                "UPDATE manual_transaction SET active = 0 WHERE workspace_id = ? AND id = ?",
                [ws.id, txId],
              )
            }
            break
          }
          case "account_overlay": {
            yield* tx.execute(
              "UPDATE account_overlay SET active = 0 WHERE workspace_id = ? AND batch_id = ?",
              [ws.id, batchId],
            )
            break
          }
          case "rule_create": {
            const ruleId = String(payload.rule_id ?? "")
            const apps = yield* tx.query<{ tx_id: string }>(
              "SELECT tx_id FROM rule_application WHERE workspace_id = ? AND rule_id = ?",
              [ws.id, ruleId],
            )
            impactedTxIds = apps.rows.map((r) => r.tx_id)
            yield* tx.execute(
              "UPDATE rule SET enabled = 0, deleted_at = ?, updated_at = ? WHERE workspace_id = ? AND id = ?",
              [now, now, ws.id, ruleId],
            )
            break
          }
          case "rule_update":
          case "rule_toggle": {
            const ruleId = String(payload.rule_id ?? "")
            const before = payload.before as RuleRecord | undefined
            if (before) {
              const prevApps = yield* tx.query<{ tx_id: string }>(
                "SELECT tx_id FROM rule_application WHERE workspace_id = ? AND rule_id = ?",
                [ws.id, ruleId],
              )
              yield* tx.execute(
                `UPDATE rule SET name = ?, description = ?, priority = ?, enabled = ?, stop_on_match = ?,
                  match_json = ?, actions_json = ?, updated_at = ? WHERE workspace_id = ? AND id = ?`,
                [
                  before.name,
                  before.description,
                  before.priority,
                  before.enabled ? 1 : 0,
                  before.stop_on_match ? 1 : 0,
                  JSON.stringify(before.match_json),
                  JSON.stringify(before.actions_json),
                  now,
                  ws.id,
                  ruleId,
                ],
              )
              const nextMatches = before.enabled
                ? yield* findMatchingTxIdsForRule(tx, ws.id, {
                    id: ruleId,
                    priority: before.priority,
                    stop_on_match: before.stop_on_match,
                    match_json: before.match_json,
                    actions_json: before.actions_json,
                    created_at: before.created_at,
                  })
                : []
              impactedTxIds = Array.from(new Set([...prevApps.rows.map((r) => r.tx_id), ...nextMatches]))
            }
            break
          }
          case "rule_delete": {
            const ruleId = String(payload.rule_id ?? "")
            const before = payload.before as RuleRecord | undefined
            if (before) {
              yield* tx.execute(
                "UPDATE rule SET deleted_at = NULL, enabled = ?, updated_at = ? WHERE workspace_id = ? AND id = ?",
                [before.enabled ? 1 : 0, now, ws.id, ruleId],
              )
              if (before.enabled) {
                impactedTxIds = yield* findMatchingTxIdsForRule(tx, ws.id, {
                  id: ruleId,
                  priority: before.priority,
                  stop_on_match: before.stop_on_match,
                  match_json: before.match_json,
                  actions_json: before.actions_json,
                  created_at: before.created_at,
                })
              }
            }
            break
          }
          case "rule_reorder": {
            const before = (payload.before ?? {}) as Record<string, number>
            for (const [rid, prio] of Object.entries(before)) {
              yield* tx.execute(
                "UPDATE rule SET priority = ?, updated_at = ? WHERE workspace_id = ? AND id = ?",
                [prio, now, ws.id, rid],
              )
            }
            const apps = yield* tx.query<{ tx_id: string }>(
              "SELECT DISTINCT tx_id FROM rule_application WHERE workspace_id = ?",
              [ws.id],
            )
            impactedTxIds = apps.rows.map((r) => r.tx_id)
            break
          }
        }

        if (impactedTxIds.length > 0) {
          yield* rematerializeTransactions(tx, ws.id, impactedTxIds)
        }

        yield* tx.execute(
          "UPDATE overlay_batch SET reverted_at = ?, reverted_by = ? WHERE workspace_id = ? AND id = ?",
          [now, actor.userId, ws.id, batchId],
        )

        return { batch_id: batchId, undone: true, rematerialized_count: impactedTxIds.length }
      }),
    )
  })

export const redoOverlayBatch = (actor: Actor, workspaceId: string, batchId: string) =>
  Effect.gen(function* () {
    const ws = yield* assertWorkspaceAccess(actor, workspaceId, "member")
    const db = yield* Database

    return yield* db.transaction((tx) =>
      Effect.gen(function* () {
        const res = yield* tx.query<{
          id: string
          kind: BatchKind
          payload_json: unknown
          reverted_at: string | null
        }>(
          "SELECT id, kind, payload_json, reverted_at FROM overlay_batch WHERE workspace_id = ? AND id = ? LIMIT 1",
          [ws.id, batchId],
        )
        const batch = res.rows[0]
        if (!batch) return yield* new NotFoundError({ entity: "overlay_batch", id: batchId })
        if (!batch.reverted_at) {
          return yield* new ConflictError({ message: `Batch ${batchId} is not reverted` })
        }

        const payload = parseJsonColumn<Record<string, unknown>>(batch.payload_json, {})
        const now = new Date()
        let impactedTxIds: Array<string> = []

        switch (batch.kind) {
          case "tx_overlay":
          case "pending_carry_forward": {
            yield* tx.execute(
              "UPDATE tx_overlay SET active = 1 WHERE workspace_id = ? AND batch_id = ?",
              [ws.id, batchId],
            )
            const ovs = yield* tx.query<{ tx_id: string }>(
              "SELECT DISTINCT tx_id FROM tx_overlay WHERE workspace_id = ? AND batch_id = ?",
              [ws.id, batchId],
            )
            impactedTxIds = ovs.rows.map((r) => r.tx_id)
            break
          }
          case "tx_split": {
            const txId = String(payload.tx_id ?? "")
            if (txId) impactedTxIds = [txId]
            const replacedIds = Array.isArray(payload.replaced_split_ids)
              ? (payload.replaced_split_ids as ReadonlyArray<string>)
              : []
            if (replacedIds.length > 0) {
              yield* tx.execute(
                `UPDATE tx_split SET active = 0 WHERE workspace_id = ? AND id IN (${placeholders(replacedIds.length)})`,
                [ws.id, ...replacedIds],
              )
            }
            yield* tx.execute(
              "UPDATE tx_split SET active = 1 WHERE workspace_id = ? AND batch_id = ?",
              [ws.id, batchId],
            )
            break
          }
          case "tx_reset": {
            const overlayIds = Array.isArray(payload.deactivated_overlay_ids)
              ? (payload.deactivated_overlay_ids as ReadonlyArray<string>)
              : []
            const splitIds = Array.isArray(payload.deactivated_split_ids)
              ? (payload.deactivated_split_ids as ReadonlyArray<string>)
              : []
            if (overlayIds.length > 0) {
              yield* tx.execute(
                `UPDATE tx_overlay SET active = 0 WHERE workspace_id = ? AND id IN (${placeholders(overlayIds.length)})`,
                [ws.id, ...overlayIds],
              )
            }
            if (splitIds.length > 0) {
              yield* tx.execute(
                `UPDATE tx_split SET active = 0 WHERE workspace_id = ? AND id IN (${placeholders(splitIds.length)})`,
                [ws.id, ...splitIds],
              )
            }
            impactedTxIds = Array.isArray(payload.tx_ids) ? (payload.tx_ids as Array<string>) : []
            break
          }
          case "tx_manual": {
            const txId = String(payload.tx_id ?? "")
            if (txId) {
              impactedTxIds = [txId]
              yield* tx.execute(
                "UPDATE manual_transaction SET active = 1 WHERE workspace_id = ? AND id = ?",
                [ws.id, txId],
              )
            }
            break
          }
          case "account_overlay": {
            yield* tx.execute(
              "UPDATE account_overlay SET active = 1 WHERE workspace_id = ? AND batch_id = ?",
              [ws.id, batchId],
            )
            break
          }
          case "rule_create": {
            const ruleId = String(payload.rule_id ?? "")
            const after = payload.after as { enabled?: boolean; priority?: number; stop_on_match?: boolean; match: RuleMatchNode; actions: RuleActionPatch } | undefined
            yield* tx.execute(
              "UPDATE rule SET deleted_at = NULL, enabled = ?, updated_at = ? WHERE workspace_id = ? AND id = ?",
              [after?.enabled === false ? 0 : 1, now, ws.id, ruleId],
            )
            if (after && after.enabled !== false) {
              impactedTxIds = yield* findMatchingTxIdsForRule(tx, ws.id, {
                id: ruleId,
                priority: after.priority ?? 100,
                stop_on_match: after.stop_on_match ?? false,
                match_json: after.match,
                actions_json: after.actions,
                created_at: now.toISOString(),
              })
            }
            break
          }
          case "rule_update":
          case "rule_toggle": {
            const ruleId = String(payload.rule_id ?? "")
            const after = payload.after as RuleRecord | undefined
            if (after) {
              const prevApps = yield* tx.query<{ tx_id: string }>(
                "SELECT tx_id FROM rule_application WHERE workspace_id = ? AND rule_id = ?",
                [ws.id, ruleId],
              )
              yield* tx.execute(
                `UPDATE rule SET name = ?, description = ?, priority = ?, enabled = ?, stop_on_match = ?,
                  match_json = ?, actions_json = ?, updated_at = ? WHERE workspace_id = ? AND id = ?`,
                [
                  after.name,
                  after.description,
                  after.priority,
                  after.enabled ? 1 : 0,
                  after.stop_on_match ? 1 : 0,
                  JSON.stringify(after.match_json),
                  JSON.stringify(after.actions_json),
                  now,
                  ws.id,
                  ruleId,
                ],
              )
              const nextMatches = after.enabled
                ? yield* findMatchingTxIdsForRule(tx, ws.id, {
                    id: ruleId,
                    priority: after.priority,
                    stop_on_match: after.stop_on_match,
                    match_json: after.match_json,
                    actions_json: after.actions_json,
                    created_at: now.toISOString(),
                  })
                : []
              impactedTxIds = Array.from(new Set([...prevApps.rows.map((r) => r.tx_id), ...nextMatches]))
            }
            break
          }
          case "rule_delete": {
            const ruleId = String(payload.rule_id ?? "")
            const prevApps = yield* tx.query<{ tx_id: string }>(
              "SELECT tx_id FROM rule_application WHERE workspace_id = ? AND rule_id = ?",
              [ws.id, ruleId],
            )
            impactedTxIds = prevApps.rows.map((r) => r.tx_id)
            yield* tx.execute(
              "UPDATE rule SET deleted_at = ?, enabled = 0, updated_at = ? WHERE workspace_id = ? AND id = ?",
              [now, now, ws.id, ruleId],
            )
            break
          }
          case "rule_reorder": {
            const after = (payload.after ?? {}) as Record<string, number>
            for (const [rid, prio] of Object.entries(after)) {
              yield* tx.execute(
                "UPDATE rule SET priority = ?, updated_at = ? WHERE workspace_id = ? AND id = ?",
                [prio, now, ws.id, rid],
              )
            }
            const apps = yield* tx.query<{ tx_id: string }>(
              "SELECT DISTINCT tx_id FROM rule_application WHERE workspace_id = ?",
              [ws.id],
            )
            impactedTxIds = apps.rows.map((r) => r.tx_id)
            break
          }
        }

        if (impactedTxIds.length > 0) {
          yield* rematerializeTransactions(tx, ws.id, impactedTxIds)
        }

        yield* tx.execute(
          "UPDATE overlay_batch SET reverted_at = NULL, reverted_by = NULL WHERE workspace_id = ? AND id = ?",
          [ws.id, batchId],
        )

        return { batch_id: batchId, redone: true, rematerialized_count: impactedTxIds.length }
      }),
    )
  })
