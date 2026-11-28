import { Effect } from "effect"
import type { ProvenanceMap, TxPatch } from "@radiant/database/schema"
import {
  Database,
  parseJsonColumn,
  toBool,
  toNullableNum,
  toNum,
  type SqlParam,
} from "./db"
import { NotFoundError, ValidationError } from "./errors"
import { applyTransactionOverlay } from "./overlay"
import { getSqlSchemaCatalog, rewriteWorkspaceSql } from "./sql-guard"
import { assertWorkspaceAccess, type Actor } from "./workspace"

export interface AccountView {
  readonly id: string
  readonly item_id: string
  readonly institution_id: string
  readonly institution_name: string
  readonly name: string
  readonly official_name: string | null
  readonly mask: string | null
  readonly type: string
  readonly subtype: string | null
  readonly currency: string
  readonly current_cents: number | null
  readonly available_cents: number | null
  readonly limit_cents: number | null
  readonly nickname: string | null
  readonly account_group: string | null
  readonly owner_label: string | null
  readonly is_active: boolean
  readonly is_hidden: boolean
  readonly is_excluded_from_net_worth: boolean
  readonly notes: string | null
}

export const listAccounts = (
  actor: Actor,
  workspaceId: string,
  options?: { readonly include_hidden?: boolean; readonly include_inactive?: boolean },
) =>
  Effect.gen(function* () {
    const ws = yield* assertWorkspaceAccess(actor, workspaceId, "viewer")
    const db = yield* Database

    const [accsRes, ovsRes] = yield* Effect.all([
      db.query<Record<string, unknown>>(
        `SELECT id, item_id, institution_id, institution_name, name, official_name, mask,
                type, subtype, currency, current_cents, available_cents, limit_cents
         FROM raw_account
         WHERE workspace_id = ? AND removed_at IS NULL
         ORDER BY institution_name ASC, name ASC`,
        [ws.id],
      ),
      db.query<Record<string, unknown>>(
        `SELECT account_id, nickname, account_group, owner_label, is_hidden,
                is_excluded_from_net_worth, notes, seq
         FROM account_overlay
         WHERE workspace_id = ? AND active = 1
         ORDER BY seq ASC, id ASC`,
        [ws.id],
      ),
    ])

    const ovMap = new Map<
      string,
      {
        nickname: string | null
        account_group: string | null
        owner_label: string | null
        is_hidden: boolean
        is_excluded_from_net_worth: boolean
        notes: string | null
      }
    >()

    for (const o of ovsRes.rows) {
      const aid = String(o.account_id)
      const prev = ovMap.get(aid) ?? {
        nickname: null,
        account_group: null,
        owner_label: null,
        is_hidden: false,
        is_excluded_from_net_worth: false,
        notes: null,
      }
      if (o.nickname !== null && o.nickname !== undefined) prev.nickname = String(o.nickname)
      if (o.account_group !== null && o.account_group !== undefined) prev.account_group = String(o.account_group)
      if (o.owner_label !== null && o.owner_label !== undefined) prev.owner_label = String(o.owner_label)
      if (o.is_hidden !== null && o.is_hidden !== undefined) prev.is_hidden = toBool(o.is_hidden)
      if (o.is_excluded_from_net_worth !== null && o.is_excluded_from_net_worth !== undefined) {
        prev.is_excluded_from_net_worth = toBool(o.is_excluded_from_net_worth)
      }
      if (o.notes !== null && o.notes !== undefined) prev.notes = String(o.notes)
      ovMap.set(aid, prev)
    }

    const views: Array<AccountView> = accsRes.rows.map((a) => {
      const id = String(a.id)
      const ov = ovMap.get(id)
      return {
        id,
        item_id: String(a.item_id),
        institution_id: String(a.institution_id),
        institution_name: String(a.institution_name),
        name: String(a.name),
        official_name: a.official_name ? String(a.official_name) : null,
        mask: a.mask ? String(a.mask) : null,
        type: String(a.type),
        subtype: a.subtype ? String(a.subtype) : null,
        currency: String(a.currency),
        current_cents: toNullableNum(a.current_cents),
        available_cents: toNullableNum(a.available_cents),
        limit_cents: toNullableNum(a.limit_cents),
        nickname: ov?.nickname ?? null,
        account_group: ov?.account_group ?? null,
        owner_label: ov?.owner_label ?? null,
        is_active: !(ov?.is_hidden ?? false),
        is_hidden: ov?.is_hidden ?? false,
        is_excluded_from_net_worth: ov?.is_excluded_from_net_worth ?? false,
        notes: ov?.notes ?? null,
      }
    })

    const includeInactive = options?.include_inactive || options?.include_hidden
    return includeInactive ? views : views.filter((v) => v.is_active)
  })

export const getAccount = (actor: Actor, workspaceId: string, accountId: string) =>
  Effect.gen(function* () {
    const accounts = yield* listAccounts(actor, workspaceId, { include_hidden: true })
    const found = accounts.find((a) => a.id === accountId)
    if (!found) return yield* new NotFoundError({ entity: "account", id: accountId })
    return found
  })

const isLiabilityType = (type: string): boolean => type === "credit" || type === "loan"

export const balancesSummary = (actor: Actor, workspaceId: string) =>
  Effect.gen(function* () {
    const accounts = yield* listAccounts(actor, workspaceId, { include_hidden: false })
    const included = accounts.filter((a) => !a.is_excluded_from_net_worth)

    const byCurrency = new Map<
      string,
      { assets_cents: number; liabilities_cents: number; net_worth_cents: number }
    >()
    const byType = new Map<string, number>()

    for (const acc of included) {
      const bal = acc.current_cents ?? 0
      const cur = byCurrency.get(acc.currency) ?? {
        assets_cents: 0,
        liabilities_cents: 0,
        net_worth_cents: 0,
      }
      if (isLiabilityType(acc.type)) {
        cur.liabilities_cents += bal
        cur.net_worth_cents -= bal
      } else {
        cur.assets_cents += bal
        cur.net_worth_cents += bal
      }
      byCurrency.set(acc.currency, cur)
      byType.set(acc.type, (byType.get(acc.type) ?? 0) + (isLiabilityType(acc.type) ? -bal : bal))
    }

    return {
      by_currency: Object.fromEntries(byCurrency.entries()),
      by_type_cents: Object.fromEntries(byType.entries()),
      accounts: included.map((a) => ({
        id: a.id,
        name: a.nickname ?? a.name,
        institution_name: a.institution_name,
        type: a.type,
        subtype: a.subtype,
        currency: a.currency,
        current_cents: a.current_cents,
        available_cents: a.available_cents,
        limit_cents: a.limit_cents,
      })),
    }
  })

export const balancesHistory = (
  actor: Actor,
  workspaceId: string,
  input?: {
    readonly date_from?: string
    readonly date_to?: string
    readonly account_ids?: ReadonlyArray<string>
    readonly bucket?: "day" | "week" | "month"
  },
) =>
  Effect.gen(function* () {
    const ws = yield* assertWorkspaceAccess(actor, workspaceId, "viewer")
    const db = yield* Database
    const accounts = yield* listAccounts(actor, workspaceId, { include_hidden: true })
    const accMap = new Map(accounts.map((a) => [a.id, a]))

    const where: Array<string> = ["workspace_id = ?"]
    const params: Array<SqlParam> = [ws.id]
    if (input?.date_from) {
      where.push("captured_at >= ?")
      params.push(`${input.date_from} 00:00:00`)
    }
    if (input?.date_to) {
      where.push("captured_at <= ?")
      params.push(`${input.date_to} 23:59:59`)
    }
    if (input?.account_ids && input.account_ids.length > 0) {
      where.push(`account_id IN (${input.account_ids.map(() => "?").join(", ")})`)
      params.push(...input.account_ids)
    }

    const res = yield* db.query<{
      account_id: string
      captured_at: string
      currency: string
      current_cents: number | null
    }>(
      `SELECT account_id, captured_at, currency, current_cents
       FROM raw_balance_snapshot
       WHERE ${where.join(" AND ")}
       ORDER BY captured_at ASC`,
      params,
    )

    const bucket = input?.bucket ?? "day"
    const bucketKey = (ts: string): string => {
      const d = String(ts).slice(0, 10)
      if (bucket === "month") return d.slice(0, 7)
      if (bucket === "week") {
        const dt = new Date(`${d}T00:00:00Z`)
        const day = dt.getUTCDay()
        dt.setUTCDate(dt.getUTCDate() - day)
        return dt.toISOString().slice(0, 10)
      }
      return d
    }

    // Keep latest snapshot per (bucket, account_id)
    const buckets = new Map<string, Map<string, number>>()
    const hasExplicitAccounts = Boolean(input?.account_ids && input.account_ids.length > 0)
    for (const row of res.rows) {
      const acc = accMap.get(row.account_id)
      if (!hasExplicitAccounts && acc && (!acc.is_active || acc.is_excluded_from_net_worth)) continue
      const bk = bucketKey(row.captured_at)
      const perAcc = buckets.get(bk) ?? new Map<string, number>()
      const bal = toNullableNum(row.current_cents) ?? 0
      perAcc.set(row.account_id, isLiabilityType(acc?.type ?? "") ? -bal : bal)
      buckets.set(bk, perAcc)
    }

    const series = Array.from(buckets.entries())
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([period, perAcc]) => {
        let netWorthCents = 0
        let assetsCents = 0
        let liabilitiesCents = 0
        for (const v of perAcc.values()) {
          netWorthCents += v
          if (v >= 0) assetsCents += v
          else liabilitiesCents += -v
        }
        return {
          period,
          net_worth_cents: netWorthCents,
          assets_cents: assetsCents,
          liabilities_cents: liabilitiesCents,
          accounts: Object.fromEntries(perAcc.entries()),
        }
      })

    return { bucket, series }
  })

// ── Structured Transaction Query & Filtering ────────────────────────────────

export interface TransactionFilter {
  readonly date_from?: string
  readonly date_to?: string
  readonly account_ids?: ReadonlyArray<string>
  readonly institution_ids?: ReadonlyArray<string>
  readonly categories?: ReadonlyArray<string>
  readonly exclude_categories?: ReadonlyArray<string>
  readonly merchants?: ReadonlyArray<string>
  readonly search?: string
  readonly amount_min_cents?: number
  readonly amount_max_cents?: number
  readonly direction?: "inflow" | "outflow" | "all"
  readonly tags_any?: ReadonlyArray<string>
  readonly tags_all?: ReadonlyArray<string>
  readonly tags_none?: ReadonlyArray<string>
  readonly pending?: boolean | "all"
  readonly include_transfers?: boolean
  readonly include_excluded?: boolean
  readonly include_inactive_accounts?: boolean
  readonly has_overlay?: boolean
  readonly rule_id?: string
  readonly batch_id?: string
  readonly expand_splits?: boolean
}

export interface TransactionQueryInput extends TransactionFilter {
  readonly sort_by?: "date" | "amount_cents" | "merchant_name" | "category"
  readonly sort_dir?: "asc" | "desc"
  readonly cursor?: string
  readonly limit?: number
  readonly include_raw?: boolean
  readonly include_provenance?: boolean
}

const buildFilterWhere = (
  workspaceId: string,
  f: TransactionFilter,
  alias: string,
  defaults: { includeTransfers: boolean; includeExcluded: boolean },
): { readonly whereSql: string; readonly params: Array<SqlParam> } => {
  const conds: Array<string> = [`${alias}.workspace_id = ?`]
  const params: Array<SqlParam> = [workspaceId]

  if (f.date_from) { conds.push(`${alias}.date >= ?`); params.push(f.date_from) }
  if (f.date_to) { conds.push(`${alias}.date <= ?`); params.push(f.date_to) }

  if (f.account_ids && f.account_ids.length > 0) {
    conds.push(`${alias}.account_id IN (${f.account_ids.map(() => "?").join(", ")})`)
    params.push(...f.account_ids)
  }
  if (f.institution_ids && f.institution_ids.length > 0) {
    conds.push(`${alias}.institution_id IN (${f.institution_ids.map(() => "?").join(", ")})`)
    params.push(...f.institution_ids)
  }
  if (f.categories && f.categories.length > 0) {
    const catConds = f.categories.map(() => `(${alias}.category = ? OR ${alias}.category LIKE ?)`)
    conds.push(`(${catConds.join(" OR ")})`)
    for (const c of f.categories) {
      params.push(c, `${c} > %`)
    }
  }
  if (f.exclude_categories && f.exclude_categories.length > 0) {
    for (const c of f.exclude_categories) {
      conds.push(`(${alias}.category IS NULL OR (${alias}.category != ? AND ${alias}.category NOT LIKE ?))`)
      params.push(c, `${c} > %`)
    }
  }
  if (f.merchants && f.merchants.length > 0) {
    const mConds = f.merchants.map(() => `LOWER(COALESCE(${alias}.merchant_name, ${alias}.description)) LIKE ?`)
    conds.push(`(${mConds.join(" OR ")})`)
    for (const m of f.merchants) params.push(`%${m.toLowerCase()}%`)
  }
  if (f.search && f.search.trim().length > 0) {
    const q = `%${f.search.trim().toLowerCase()}%`
    conds.push(
      `(LOWER(COALESCE(${alias}.merchant_name, '')) LIKE ? OR LOWER(${alias}.description) LIKE ? OR LOWER(${alias}.raw_name) LIKE ? OR LOWER(COALESCE(${alias}.notes, '')) LIKE ? OR LOWER(${alias}.tags_text) LIKE ?)`,
    )
    params.push(q, q, q, q, q)
  }
  if (f.amount_min_cents !== undefined) {
    conds.push(`${alias}.amount_cents >= ?`)
    params.push(Math.trunc(f.amount_min_cents))
  }
  if (f.amount_max_cents !== undefined) {
    conds.push(`${alias}.amount_cents <= ?`)
    params.push(Math.trunc(f.amount_max_cents))
  }
  if (f.direction === "outflow") conds.push(`${alias}.amount_cents < 0`)
  else if (f.direction === "inflow") conds.push(`${alias}.amount_cents > 0`)

  if (f.tags_any && f.tags_any.length > 0) {
    const tConds = f.tags_any.map(() => `CONCAT(' ', ${alias}.tags_text, ' ') LIKE ?`)
    conds.push(`(${tConds.join(" OR ")})`)
    for (const t of f.tags_any) params.push(`% ${t.trim().toLowerCase()} %`)
  }
  if (f.tags_all && f.tags_all.length > 0) {
    for (const t of f.tags_all) {
      conds.push(`CONCAT(' ', ${alias}.tags_text, ' ') LIKE ?`)
      params.push(`% ${t.trim().toLowerCase()} %`)
    }
  }
  if (f.tags_none && f.tags_none.length > 0) {
    for (const t of f.tags_none) {
      conds.push(`CONCAT(' ', ${alias}.tags_text, ' ') NOT LIKE ?`)
      params.push(`% ${t.trim().toLowerCase()} %`)
    }
  }

  if (f.pending !== undefined && f.pending !== "all") {
    conds.push(`${alias}.pending = ?`)
    params.push(f.pending ? 1 : 0)
  }

  const includeTransfers = f.include_transfers ?? defaults.includeTransfers
  if (!includeTransfers) conds.push(`${alias}.is_transfer = 0`)

  const includeExcluded = f.include_excluded ?? defaults.includeExcluded
  if (!includeExcluded) conds.push(`${alias}.is_excluded = 0`)

  const includeInactiveAccounts =
    f.include_inactive_accounts ?? Boolean(f.account_ids && f.account_ids.length > 0)
  if (!includeInactiveAccounts) {
    conds.push(
      `(${alias}.account_id IS NULL OR COALESCE((SELECT ao.is_hidden FROM account_overlay ao WHERE ao.workspace_id = ${alias}.workspace_id AND ao.account_id = ${alias}.account_id AND ao.active = 1 AND ao.is_hidden IS NOT NULL ORDER BY ao.seq DESC, ao.id DESC LIMIT 1), 0) = 0)`,
    )
  }

  if (f.has_overlay !== undefined) {
    conds.push(`${alias}.has_overlay = ?`)
    params.push(f.has_overlay ? 1 : 0)
  }

  if (f.rule_id) {
    conds.push(
      `EXISTS (SELECT 1 FROM rule_application ra WHERE ra.workspace_id = ${alias}.workspace_id AND ra.tx_id = ${alias}.id AND ra.rule_id = ?)`,
    )
    params.push(f.rule_id)
  }

  if (f.batch_id) {
    conds.push(
      `(EXISTS (SELECT 1 FROM tx_overlay ov WHERE ov.workspace_id = ${alias}.workspace_id AND ov.tx_id = ${alias}.id AND ov.batch_id = ?) OR EXISTS (SELECT 1 FROM tx_split sp WHERE sp.workspace_id = ${alias}.workspace_id AND sp.tx_id = ${alias}.id AND sp.batch_id = ?))`,
    )
    params.push(f.batch_id, f.batch_id)
  }

  return { whereSql: conds.join(" AND "), params }
}

const encodeCursor = (sortVal: string | number, id: string): string =>
  btoa(JSON.stringify([sortVal, id]))

const decodeCursor = (cursor: string): [string | number, string] | null => {
  try {
    const parsed = JSON.parse(atob(cursor))
    if (Array.isArray(parsed) && parsed.length === 2 && typeof parsed[1] === "string") {
      return [parsed[0] as string | number, parsed[1]]
    }
    return null
  } catch {
    return null
  }
}

export const queryTransactions = (
  actor: Actor,
  workspaceId: string,
  input: TransactionQueryInput = {},
) =>
  Effect.gen(function* () {
    const ws = yield* assertWorkspaceAccess(actor, workspaceId, "viewer")
    const db = yield* Database

    const sortBy = input.sort_by ?? "date"
    const sortDir = input.sort_dir === "asc" ? "ASC" : "DESC"
    const limit = Math.max(1, Math.min(input.limit ?? 50, 500))

    const sortColMap: Record<string, string> = {
      date: "et.date",
      amount_cents: "et.amount_cents",
      merchant_name: "COALESCE(et.merchant_name, et.description)",
      category: "COALESCE(et.category, '')",
    }
    const sortExpr = sortColMap[sortBy] ?? "et.date"

    const { whereSql, params } = buildFilterWhere(ws.id, input, "et", {
      includeTransfers: true,
      includeExcluded: false,
    })

    let fullWhere = whereSql
    if (input.cursor) {
      const decoded = decodeCursor(input.cursor)
      if (!decoded) {
        return yield* new ValidationError({ message: "Invalid pagination cursor", field: "cursor" })
      }
      const [cursorVal, cursorId] = decoded
      const cmp = sortDir === "DESC" ? "<" : ">"
      fullWhere += ` AND (${sortExpr} ${cmp} ? OR (${sortExpr} = ? AND et.id ${cmp} ?))`
      params.push(cursorVal, cursorVal, cursorId)
    }

    const res = yield* db.queryReadOnly<Record<string, unknown>>(
      `SELECT et.*
       FROM effective_transaction et
       WHERE ${fullWhere}
       ORDER BY ${sortExpr} ${sortDir}, et.id ${sortDir}
       LIMIT ${limit + 1}`,
      params,
    )

    const hasMore = res.rows.length > limit
    const pageRows = hasMore ? res.rows.slice(0, limit) : res.rows
    const txIds = pageRows.map((r) => String(r.id))

    const splitsByTx = new Map<string, Array<Record<string, unknown>>>()
    if (txIds.length > 0) {
      const spRes = yield* db.queryReadOnly<Record<string, unknown>>(
        `SELECT id, tx_id, line_index, amount_cents, category, merchant_name, description, tags_json, notes, is_excluded
         FROM tx_split
         WHERE workspace_id = ? AND active = 1 AND tx_id IN (${txIds.map(() => "?").join(", ")})
         ORDER BY line_index ASC`,
        [ws.id, ...txIds],
      )
      for (const s of spRes.rows) {
        const tid = String(s.tx_id)
        const list = splitsByTx.get(tid) ?? []
        list.push({
          id: String(s.id),
          line_index: toNum(s.line_index),
          amount_cents: toNum(s.amount_cents),
          amount: toNum(s.amount_cents) / 100,
          category: s.category ? String(s.category) : null,
          merchant_name: s.merchant_name ? String(s.merchant_name) : null,
          description: s.description ? String(s.description) : null,
          tags: parseJsonColumn<ReadonlyArray<string>>(s.tags_json, []),
          notes: s.notes ? String(s.notes) : null,
          is_excluded: toBool(s.is_excluded),
        })
        splitsByTx.set(tid, list)
      }
    }

    const rawByTx = new Map<string, Record<string, unknown>>()
    if (input.include_raw && txIds.length > 0) {
      const rRes = yield* db.queryReadOnly<Record<string, unknown>>(
        `SELECT id, plaid_transaction_id, raw_amount_cents, date, name, merchant_name, pfc_primary, pfc_detailed, raw_json
         FROM raw_transaction
         WHERE workspace_id = ? AND id IN (${txIds.map(() => "?").join(", ")})`,
        [ws.id, ...txIds],
      )
      for (const r of rRes.rows) {
        rawByTx.set(String(r.id), {
          plaid_transaction_id: r.plaid_transaction_id,
          raw_amount_cents: toNum(r.raw_amount_cents),
          date: r.date,
          name: r.name,
          merchant_name: r.merchant_name,
          pfc_primary: r.pfc_primary,
          pfc_detailed: r.pfc_detailed,
          raw_json: parseJsonColumn<Record<string, unknown>>(r.raw_json, {}),
        })
      }
    }

    const items = pageRows.map((r) => {
      const id = String(r.id)
      const amountCents = toNum(r.amount_cents)
      return {
        id,
        source: String(r.source),
        account_id: r.account_id ? String(r.account_id) : null,
        institution_id: r.institution_id ? String(r.institution_id) : null,
        date: String(r.date),
        raw_date: String(r.raw_date),
        amount_cents: amountCents,
        amount: amountCents / 100,
        raw_amount_cents: toNum(r.raw_amount_cents),
        currency: String(r.currency),
        merchant_name: r.merchant_name ? String(r.merchant_name) : null,
        description: String(r.description),
        raw_name: String(r.raw_name),
        category: r.category ? String(r.category) : null,
        category_top: r.category_top ? String(r.category_top) : null,
        raw_category: r.raw_category ? String(r.raw_category) : null,
        payment_channel: r.payment_channel ? String(r.payment_channel) : null,
        pending: toBool(r.pending),
        is_transfer: toBool(r.is_transfer),
        transfer_pair_id: r.transfer_pair_id ? String(r.transfer_pair_id) : null,
        is_excluded: toBool(r.is_excluded),
        has_splits: toBool(r.has_splits),
        has_overlay: toBool(r.has_overlay),
        recurring_group: r.recurring_group ? String(r.recurring_group) : null,
        tags: parseJsonColumn<ReadonlyArray<string>>(r.tags_json, []),
        notes: r.notes ? String(r.notes) : null,
        custom_fields: parseJsonColumn<Record<string, unknown> | null>(r.custom_fields_json, null),
        splits: splitsByTx.get(id) ?? [],
        ...(input.include_provenance
          ? {
              provenance: parseJsonColumn<ProvenanceMap>(r.provenance_json, {}),
              applied_rule_ids: parseJsonColumn<ReadonlyArray<string>>(r.applied_rule_ids_json, []),
            }
          : {}),
        ...(input.include_raw ? { raw: rawByTx.get(id) ?? null } : {}),
      }
    })

    const last = pageRows[pageRows.length - 1]
    const nextCursor =
      hasMore && last
        ? encodeCursor(
            sortBy === "amount_cents"
              ? toNum(last.amount_cents)
              : sortBy === "merchant_name"
                ? String(last.merchant_name ?? last.description)
                : sortBy === "category"
                  ? String(last.category ?? "")
                  : String(last.date),
            String(last.id),
          )
        : null

    return { items, next_cursor: nextCursor, has_more: hasMore }
  })

export const getTransactionDetail = (actor: Actor, workspaceId: string, txId: string) =>
  Effect.gen(function* () {
    const ws = yield* assertWorkspaceAccess(actor, workspaceId, "viewer")
    const db = yield* Database
    const effRes = yield* db.queryReadOnly<Record<string, unknown>>(
      "SELECT * FROM effective_transaction WHERE workspace_id = ? AND id = ? LIMIT 1",
      [ws.id, txId],
    )
    const r = effRes.rows[0]
    if (!r) return yield* new NotFoundError({ entity: "transaction", id: txId })

    const [rawRes, splitsRes, overlaysRes] = yield* Effect.all([
      db.queryReadOnly<Record<string, unknown>>(
        "SELECT * FROM raw_transaction WHERE workspace_id = ? AND id = ? LIMIT 1",
        [ws.id, txId],
      ),
      db.queryReadOnly<Record<string, unknown>>(
        "SELECT * FROM tx_split WHERE workspace_id = ? AND tx_id = ? AND active = 1 ORDER BY line_index ASC",
        [ws.id, txId],
      ),
      db.queryReadOnly<Record<string, unknown>>(
        `SELECT o.id, o.batch_id, o.seq, o.patch_json, o.active, o.created_at, b.reason, b.actor_type, b.client_name
         FROM tx_overlay o
         LEFT JOIN overlay_batch b ON b.workspace_id = o.workspace_id AND b.id = o.batch_id
         WHERE o.workspace_id = ? AND o.tx_id = ?
         ORDER BY o.seq ASC`,
        [ws.id, txId],
      ),
    ])

    const amountCents = toNum(r.amount_cents)
    return {
      effective: {
        id: String(r.id),
        source: String(r.source),
        account_id: r.account_id ? String(r.account_id) : null,
        date: String(r.date),
        raw_date: String(r.raw_date),
        amount_cents: amountCents,
        amount: amountCents / 100,
        currency: String(r.currency),
        merchant_name: r.merchant_name ? String(r.merchant_name) : null,
        description: String(r.description),
        raw_name: String(r.raw_name),
        category: r.category ? String(r.category) : null,
        category_top: r.category_top ? String(r.category_top) : null,
        raw_category: r.raw_category ? String(r.raw_category) : null,
        pending: toBool(r.pending),
        is_transfer: toBool(r.is_transfer),
        is_excluded: toBool(r.is_excluded),
        has_splits: toBool(r.has_splits),
        has_overlay: toBool(r.has_overlay),
        tags: parseJsonColumn<ReadonlyArray<string>>(r.tags_json, []),
        notes: r.notes ? String(r.notes) : null,
        custom_fields: parseJsonColumn<Record<string, unknown> | null>(r.custom_fields_json, null),
        provenance: parseJsonColumn<ProvenanceMap>(r.provenance_json, {}),
        applied_rule_ids: parseJsonColumn<ReadonlyArray<string>>(r.applied_rule_ids_json, []),
      },
      raw: rawRes.rows[0]
        ? {
            ...rawRes.rows[0],
            raw_amount_cents: toNum(rawRes.rows[0].raw_amount_cents),
            raw_json: parseJsonColumn<Record<string, unknown>>(rawRes.rows[0].raw_json, {}),
          }
        : null,
      splits: splitsRes.rows.map((s) => ({
        id: String(s.id),
        line_index: toNum(s.line_index),
        amount_cents: toNum(s.amount_cents),
        amount: toNum(s.amount_cents) / 100,
        category: s.category ? String(s.category) : null,
        merchant_name: s.merchant_name ? String(s.merchant_name) : null,
        description: s.description ? String(s.description) : null,
        tags: parseJsonColumn<ReadonlyArray<string>>(s.tags_json, []),
        notes: s.notes ? String(s.notes) : null,
        is_excluded: toBool(s.is_excluded),
      })),
      overlay_history: overlaysRes.rows.map((o) => ({
        id: String(o.id),
        batch_id: String(o.batch_id),
        active: toBool(o.active),
        patch: parseJsonColumn<TxPatch>(o.patch_json, {}),
        reason: o.reason ? String(o.reason) : null,
        actor_type: o.actor_type ? String(o.actor_type) : null,
        client_name: o.client_name ? String(o.client_name) : null,
        created_at: String(o.created_at),
      })),
    }
  })

/** Overlay transactions selected either by explicit tx_ids OR by a structured TransactionFilter. */
export const applyOverlayByIdsOrFilter = (
  actor: Actor,
  workspaceId: string,
  input: {
    readonly tx_ids?: ReadonlyArray<string>
    readonly filter?: TransactionFilter
    readonly patch: TxPatch
    readonly reason?: string
    readonly dry_run?: boolean
  },
) =>
  Effect.gen(function* () {
    if (input.tx_ids && input.tx_ids.length > 0) {
      return yield* applyTransactionOverlay(actor, workspaceId, {
        tx_ids: input.tx_ids,
        patch: input.patch,
        reason: input.reason,
        dry_run: input.dry_run,
      })
    }
    if (!input.filter) {
      return yield* new ValidationError({
        message: "Either tx_ids or filter must be provided",
        field: "tx_ids",
      })
    }
    const ws = yield* assertWorkspaceAccess(actor, workspaceId, "member")
    const db = yield* Database
    const { whereSql, params } = buildFilterWhere(ws.id, input.filter, "et", {
      includeTransfers: true,
      includeExcluded: true,
    })
    const matched = yield* db.query<{ id: string }>(
      `SELECT et.id FROM effective_transaction et WHERE ${whereSql} LIMIT 2001`,
      params,
    )
    if (matched.rows.length > 2000) {
      return yield* new ValidationError({
        message: "Filter matches more than 2,000 transactions; narrow the filter or create a rule instead",
      })
    }
    return yield* applyTransactionOverlay(actor, workspaceId, {
      tx_ids: matched.rows.map((r) => r.id),
      patch: input.patch,
      reason: input.reason,
      dry_run: input.dry_run,
    })
  })

// ── Structured Multi-Dimension Aggregation ──────────────────────────────────

export type AggregateDimension =
  | "day"
  | "week"
  | "month"
  | "quarter"
  | "year"
  | "category"
  | "category_top"
  | "merchant_name"
  | "account_id"
  | "institution_id"
  | "tag"
  | "payment_channel"
  | "pending"
  | "currency"

export interface AggregateInput extends TransactionFilter {
  readonly group_by?: ReadonlyArray<AggregateDimension>
  readonly order_by?: "sum_cents" | "abs_sum_cents" | "count" | "outflow_cents" | "inflow_cents" | "group"
  readonly order_dir?: "asc" | "desc"
  readonly limit?: number
  readonly compare_previous_period?: boolean
}

const timeBucket = (isoDate: string, dim: "day" | "week" | "month" | "quarter" | "year"): string => {
  if (dim === "day") return isoDate
  if (dim === "month") return isoDate.slice(0, 7)
  if (dim === "year") return isoDate.slice(0, 4)
  if (dim === "quarter") {
    const m = Number(isoDate.slice(5, 7))
    return `${isoDate.slice(0, 4)}-Q${Math.floor((m - 1) / 3) + 1}`
  }
  const dt = new Date(`${isoDate}T00:00:00Z`)
  dt.setUTCDate(dt.getUTCDate() - dt.getUTCDay())
  return dt.toISOString().slice(0, 10)
}

const shiftDateRangePrevious = (
  dateFrom: string,
  dateTo: string,
): { readonly date_from: string; readonly date_to: string } => {
  const fromMs = Date.parse(`${dateFrom}T00:00:00Z`)
  const toMs = Date.parse(`${dateTo}T00:00:00Z`)
  const spanDays = Math.max(1, Math.round((toMs - fromMs) / 86_400_000) + 1)
  const prevTo = new Date(fromMs - 86_400_000)
  const prevFrom = new Date(fromMs - spanDays * 86_400_000)
  return {
    date_from: prevFrom.toISOString().slice(0, 10),
    date_to: prevTo.toISOString().slice(0, 10),
  }
}

const runAggregationPass = (
  workspaceId: string,
  input: AggregateInput,
) =>
  Effect.gen(function* () {
    const db = yield* Database
    const groupBy = (input.group_by ?? []).slice(0, 3)
    const expandSplits = input.expand_splits ?? true

    const { whereSql, params } = buildFilterWhere(workspaceId, input, "et", {
      includeTransfers: false,
      includeExcluded: false,
    })

    // Fetch filtered effective rows (and active splits when split-aware)
    const effRes = yield* db.queryReadOnly<Record<string, unknown>>(
      `SELECT et.id, et.date, et.amount_cents, et.currency, et.account_id, et.institution_id,
              et.merchant_name, et.description, et.category, et.category_top,
              et.payment_channel, et.pending, et.has_splits, et.tags_json, et.is_excluded
       FROM effective_transaction et
       WHERE ${whereSql}`,
      params,
    )

    const splitParentIds = expandSplits
      ? effRes.rows.filter((r) => toBool(r.has_splits)).map((r) => String(r.id))
      : []

    const splitsByTx = new Map<string, Array<Record<string, unknown>>>()
    if (splitParentIds.length > 0) {
      const spRes = yield* db.queryReadOnly<Record<string, unknown>>(
        `SELECT tx_id, amount_cents, category, merchant_name, description, tags_json, is_excluded
         FROM tx_split
         WHERE workspace_id = ? AND active = 1 AND tx_id IN (${splitParentIds.map(() => "?").join(", ")})`,
        [workspaceId, ...splitParentIds],
      )
      for (const s of spRes.rows) {
        const tid = String(s.tx_id)
        const list = splitsByTx.get(tid) ?? []
        list.push(s)
        splitsByTx.set(tid, list)
      }
    }

    interface RowUnit {
      date: string
      amount_cents: number
      currency: string
      account_id: string | null
      institution_id: string | null
      merchant_name: string | null
      category: string | null
      category_top: string | null
      payment_channel: string | null
      pending: boolean
      tags: ReadonlyArray<string>
    }

    const units: Array<RowUnit> = []
    const includeExcluded = input.include_excluded ?? false

    for (const r of effRes.rows) {
      const id = String(r.id)
      const splits = expandSplits ? splitsByTx.get(id) : undefined
      if (splits && splits.length > 0) {
        for (const s of splits) {
          if (!includeExcluded && toBool(s.is_excluded)) continue
          const cat = s.category ? String(s.category) : r.category ? String(r.category) : null
          const topIdx = cat ? cat.indexOf(">") : -1
          units.push({
            date: String(r.date),
            amount_cents: toNum(s.amount_cents),
            currency: String(r.currency),
            account_id: r.account_id ? String(r.account_id) : null,
            institution_id: r.institution_id ? String(r.institution_id) : null,
            merchant_name: s.merchant_name
              ? String(s.merchant_name)
              : r.merchant_name
                ? String(r.merchant_name)
                : String(r.description),
            category: cat,
            category_top: cat ? (topIdx === -1 ? cat : cat.slice(0, topIdx).trim()) : null,
            payment_channel: r.payment_channel ? String(r.payment_channel) : null,
            pending: toBool(r.pending),
            tags: parseJsonColumn<ReadonlyArray<string>>(s.tags_json, []),
          })
        }
      } else {
        units.push({
          date: String(r.date),
          amount_cents: toNum(r.amount_cents),
          currency: String(r.currency),
          account_id: r.account_id ? String(r.account_id) : null,
          institution_id: r.institution_id ? String(r.institution_id) : null,
          merchant_name: r.merchant_name ? String(r.merchant_name) : String(r.description),
          category: r.category ? String(r.category) : null,
          category_top: r.category_top ? String(r.category_top) : null,
          payment_channel: r.payment_channel ? String(r.payment_channel) : null,
          pending: toBool(r.pending),
          tags: parseJsonColumn<ReadonlyArray<string>>(r.tags_json, []),
        })
      }
    }

    interface BucketAcc {
      key: Record<string, string | boolean | null>
      count: number
      sum_cents: number
      inflow_cents: number
      outflow_cents: number
      min_cents: number
      max_cents: number
    }

    const extractDim = (u: RowUnit, dim: AggregateDimension): ReadonlyArray<string | boolean | null> => {
      switch (dim) {
        case "day":
        case "week":
        case "month":
        case "quarter":
        case "year":
          return [timeBucket(u.date, dim)]
        case "category":
          return [u.category ?? "Uncategorized"]
        case "category_top":
          return [u.category_top ?? "Uncategorized"]
        case "merchant_name":
          return [u.merchant_name ?? "Unknown"]
        case "account_id":
          return [u.account_id]
        case "institution_id":
          return [u.institution_id]
        case "payment_channel":
          return [u.payment_channel ?? "unknown"]
        case "pending":
          return [u.pending]
        case "currency":
          return [u.currency]
        case "tag":
          return u.tags.length > 0 ? u.tags : ["(untagged)"]
      }
    }

    const buckets = new Map<string, BucketAcc>()
    let totalSum = 0
    let totalInflow = 0
    let totalOutflow = 0

    for (const u of units) {
      totalSum += u.amount_cents
      if (u.amount_cents > 0) totalInflow += u.amount_cents
      else totalOutflow += -u.amount_cents

      // Expand cartesian product (usually 1 key unless grouping by multi-valued 'tag')
      let combos: Array<Record<string, string | boolean | null>> = [{}]
      for (const dim of groupBy) {
        const vals = extractDim(u, dim)
        const next: Array<Record<string, string | boolean | null>> = []
        for (const c of combos) {
          for (const v of vals) next.push({ ...c, [dim]: v })
        }
        combos = next
      }

      for (const keyObj of combos) {
        const mapKey = JSON.stringify(keyObj)
        const acc = buckets.get(mapKey) ?? {
          key: keyObj,
          count: 0,
          sum_cents: 0,
          inflow_cents: 0,
          outflow_cents: 0,
          min_cents: u.amount_cents,
          max_cents: u.amount_cents,
        }
        acc.count++
        acc.sum_cents += u.amount_cents
        if (u.amount_cents > 0) acc.inflow_cents += u.amount_cents
        else acc.outflow_cents += -u.amount_cents
        if (u.amount_cents < acc.min_cents) acc.min_cents = u.amount_cents
        if (u.amount_cents > acc.max_cents) acc.max_cents = u.amount_cents
        buckets.set(mapKey, acc)
      }
    }

    const absDenom = Math.abs(totalSum) || totalOutflow || totalInflow || 1
    const rows = Array.from(buckets.values()).map((b) => ({
      group: b.key,
      count: b.count,
      sum_cents: b.sum_cents,
      sum: b.sum_cents / 100,
      avg_cents: Math.round(b.sum_cents / Math.max(1, b.count)),
      min_cents: b.min_cents,
      max_cents: b.max_cents,
      inflow_cents: b.inflow_cents,
      outflow_cents: b.outflow_cents,
      net_cents: b.sum_cents,
      pct_of_total: Number(((Math.abs(b.sum_cents) / absDenom) * 100).toFixed(2)),
    }))

    const orderBy = input.order_by ?? "abs_sum_cents"
    const dir = input.order_dir === "asc" ? 1 : -1
    rows.sort((a, b) => {
      switch (orderBy) {
        case "sum_cents":
          return (a.sum_cents - b.sum_cents) * dir
        case "count":
          return (a.count - b.count) * dir
        case "outflow_cents":
          return (a.outflow_cents - b.outflow_cents) * dir
        case "inflow_cents":
          return (a.inflow_cents - b.inflow_cents) * dir
        case "group":
          return JSON.stringify(a.group).localeCompare(JSON.stringify(b.group)) * dir
        default:
          return (Math.abs(a.sum_cents) - Math.abs(b.sum_cents)) * dir
      }
    })

    const limit = Math.max(1, Math.min(input.limit ?? 100, 1000))
    return {
      totals: {
        count: units.length,
        sum_cents: totalSum,
        sum: totalSum / 100,
        inflow_cents: totalInflow,
        outflow_cents: totalOutflow,
        net_cents: totalSum,
      },
      groups: rows.slice(0, limit),
    }
  })

export const aggregateTransactions = (
  actor: Actor,
  workspaceId: string,
  input: AggregateInput = {},
) =>
  Effect.gen(function* () {
    const ws = yield* assertWorkspaceAccess(actor, workspaceId, "viewer")
    const current = yield* runAggregationPass(ws.id, input)

    if (input.compare_previous_period && input.date_from && input.date_to) {
      const prevRange = shiftDateRangePrevious(input.date_from, input.date_to)
      const previous = yield* runAggregationPass(ws.id, {
        ...input,
        date_from: prevRange.date_from,
        date_to: prevRange.date_to,
      })
      const deltaNet = current.totals.net_cents - previous.totals.net_cents
      const deltaOutflow = current.totals.outflow_cents - previous.totals.outflow_cents
      return {
        ...current,
        previous_period: {
          ...prevRange,
          totals: previous.totals,
          delta_net_cents: deltaNet,
          delta_outflow_cents: deltaOutflow,
          outflow_change_pct:
            previous.totals.outflow_cents > 0
              ? Number(((deltaOutflow / previous.totals.outflow_cents) * 100).toFixed(2))
              : null,
        },
      }
    }

    return current
  })

// ── Safe Read-Only Workspace SQL Execution ──────────────────────────────────

export const getWorkspaceSqlSchema = (actor: Actor, workspaceId: string) =>
  Effect.gen(function* () {
    yield* assertWorkspaceAccess(actor, workspaceId, "viewer")
    return getSqlSchemaCatalog()
  })

export const executeWorkspaceSql = (
  actor: Actor,
  workspaceId: string,
  input: {
    readonly sql: string
    readonly params?: ReadonlyArray<SqlParam>
    readonly limit?: number
  },
) =>
  Effect.gen(function* () {
    const ws = yield* assertWorkspaceAccess(actor, workspaceId, "viewer")
    const rewritten = yield* rewriteWorkspaceSql({
      sql: input.sql,
      workspaceId: ws.id,
      userParams: input.params,
      limit: input.limit,
    })
    const db = yield* Database
    const res = yield* db.queryReadOnly<Record<string, unknown>>(rewritten.sql, rewritten.params)
    const columns = res.rows.length > 0 ? Object.keys(res.rows[0]!) : []
    return {
      columns,
      row_count: res.rows.length,
      limit: rewritten.limit,
      rows: res.rows,
    }
  })
