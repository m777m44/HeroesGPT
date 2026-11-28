import type {
  ProvenanceMap,
  RuleActionPatch,
  RuleMatchNode,
  TxPatch,
} from "@radiant/database/schema"
import { dayOfWeekUtc, evaluateRuleMatch, type MatchContext } from "./rule-ast"

export interface RawTxInput {
  readonly id: string
  readonly source: "plaid" | "manual"
  readonly account_id: string | null
  readonly account_type: string | null
  readonly account_subtype: string | null
  readonly institution_id: string | null
  /** Plaid native sign (+ outflow) when source = "plaid"; standard sign when source = "manual" */
  readonly raw_amount_cents: number
  readonly currency: string
  readonly date: string
  readonly name: string
  readonly merchant_name: string | null
  readonly pfc_primary: string | null
  readonly pfc_detailed: string | null
  readonly payment_channel: string | null
  readonly pending: boolean
  readonly counterparty_name: string | null
  readonly manual_category?: string | null
  readonly manual_tags?: ReadonlyArray<string>
  readonly manual_notes?: string | null
  readonly manual_is_transfer?: boolean
  readonly manual_is_excluded?: boolean
  readonly manual_custom_fields?: Record<string, unknown> | null
}

export interface ActiveRuleInput {
  readonly id: string
  readonly priority: number
  readonly stop_on_match: boolean
  readonly match_json: RuleMatchNode
  readonly actions_json: RuleActionPatch
  readonly created_at: string
}

export interface ActiveOverlayInput {
  readonly id: string
  readonly batch_id: string
  readonly seq: number
  readonly patch_json: TxPatch
}

export interface EffectiveTxOutput {
  readonly id: string
  readonly source: "plaid" | "manual"
  readonly account_id: string | null
  readonly institution_id: string | null
  readonly date: string
  readonly raw_date: string
  readonly amount_cents: number
  readonly raw_amount_cents: number
  readonly currency: string
  readonly merchant_name: string | null
  readonly description: string
  readonly raw_name: string
  readonly category: string | null
  readonly category_top: string | null
  readonly raw_category: string | null
  readonly payment_channel: string | null
  readonly pending: boolean
  readonly is_transfer: boolean
  readonly transfer_pair_id: string | null
  readonly is_excluded: boolean
  readonly has_splits: boolean
  readonly has_overlay: boolean
  readonly recurring_group: string | null
  readonly tags_json: ReadonlyArray<string>
  readonly tags_text: string
  readonly notes: string | null
  readonly custom_fields_json: Record<string, unknown> | null
  readonly provenance_json: ProvenanceMap
  readonly applied_rule_ids_json: ReadonlyArray<string>
}

export const normalizePlaidAmountCents = (plaidAmountCents: number): number =>
  plaidAmountCents === 0 ? 0 : -plaidAmountCents

const titleCaseToken = (token: string): string =>
  token
    .toLowerCase()
    .split("_")
    .filter((w) => w.length > 0)
    .map((w) => w[0]!.toUpperCase() + w.slice(1))
    .join(" ")

export const formatRawCategory = (
  primary: string | null,
  detailed: string | null,
): string | null => {
  if (!primary && !detailed) return null
  if (!primary) return titleCaseToken(detailed!)
  const primaryLabel = titleCaseToken(primary)
  if (!detailed || detailed === primary) return primaryLabel
  const suffix = detailed.startsWith(`${primary}_`)
    ? detailed.slice(primary.length + 1)
    : detailed
  return `${primaryLabel} > ${titleCaseToken(suffix)}`
}

export const computeCategoryTop = (category: string | null): string | null => {
  if (!category) return null
  const idx = category.indexOf(">")
  return (idx === -1 ? category : category.slice(0, idx)).trim() || null
}

const dedupeTags = (tags: ReadonlyArray<string>): ReadonlyArray<string> => {
  const seen = new Set<string>()
  const out: Array<string> = []
  for (const raw of tags) {
    const clean = raw.trim().toLowerCase()
    if (clean.length > 0 && !seen.has(clean)) {
      seen.add(clean)
      out.push(clean)
    }
  }
  return out
}

export const materializeTransaction = (
  raw: RawTxInput,
  activeRules: ReadonlyArray<ActiveRuleInput>,
  activeOverlays: ReadonlyArray<ActiveOverlayInput>,
  hasSplits: boolean,
): EffectiveTxOutput => {
  const baseAmountCents =
    raw.source === "plaid"
      ? normalizePlaidAmountCents(raw.raw_amount_cents)
      : raw.raw_amount_cents

  const rawCategory =
    raw.source === "plaid"
      ? formatRawCategory(raw.pfc_primary, raw.pfc_detailed)
      : (raw.manual_category ?? null)

  let date = raw.date
  let amountCents = baseAmountCents
  let merchantName: string | null = raw.merchant_name
  let description = raw.merchant_name ?? raw.name
  let category: string | null = rawCategory
  let tags: Array<string> = raw.manual_tags ? [...dedupeTags(raw.manual_tags)] : []
  let notes: string | null = raw.manual_notes ?? null
  let isTransfer =
    raw.manual_is_transfer ??
    (raw.pfc_primary === "TRANSFER_IN" ||
      raw.pfc_primary === "TRANSFER_OUT" ||
      raw.pfc_primary === "LOAN_PAYMENTS")
  let transferPairId: string | null = null
  let isExcluded = raw.manual_is_excluded ?? false
  let recurringGroup: string | null = null
  let customFields: Record<string, unknown> | null = raw.manual_custom_fields
    ? { ...raw.manual_custom_fields }
    : null

  const provenance: ProvenanceMap = {}
  const appliedRuleIds: Array<string> = []

  const matchCtx: MatchContext = {
    account_id: raw.account_id,
    account_type: raw.account_type,
    account_subtype: raw.account_subtype,
    institution_id: raw.institution_id,
    raw_name: raw.name,
    raw_merchant_name: raw.merchant_name,
    raw_category_primary: raw.pfc_primary,
    raw_category_detailed: raw.pfc_detailed,
    payment_channel: raw.payment_channel,
    currency: raw.currency,
    amount_cents: baseAmountCents,
    date: raw.date,
    day_of_week: dayOfWeekUtc(raw.date),
    pending: raw.pending,
    counterparty_name: raw.counterparty_name,
  }

  const sortedRules = [...activeRules].sort((a, b) =>
    a.priority !== b.priority
      ? a.priority - b.priority
      : a.created_at !== b.created_at
        ? a.created_at.localeCompare(b.created_at)
        : a.id.localeCompare(b.id),
  )

  for (const r of sortedRules) {
    if (!evaluateRuleMatch(r.match_json, matchCtx)) continue
    appliedRuleIds.push(r.id)
    const src = `rule:${r.id}`
    const act = r.actions_json

    if (act.set_category !== undefined) { category = act.set_category; provenance.category = src }
    if (act.set_merchant_name !== undefined) { merchantName = act.set_merchant_name; provenance.merchant_name = src }
    if (act.set_description !== undefined) { description = act.set_description; provenance.description = src }
    if (act.add_tags && act.add_tags.length > 0) {
      tags = [...dedupeTags([...tags, ...act.add_tags])]
      provenance.tags = src
    }
    if (act.remove_tags && act.remove_tags.length > 0) {
      const removeSet = new Set(act.remove_tags.map((t) => t.trim().toLowerCase()))
      tags = tags.filter((t) => !removeSet.has(t))
      provenance.tags = src
    }
    if (act.set_is_transfer !== undefined) { isTransfer = act.set_is_transfer; provenance.is_transfer = src }
    if (act.set_is_excluded !== undefined) { isExcluded = act.set_is_excluded; provenance.is_excluded = src }
    if (act.set_notes !== undefined) { notes = act.set_notes; provenance.notes = src }
    if (act.set_recurring_group !== undefined) { recurringGroup = act.set_recurring_group; provenance.recurring_group = src }
    if (act.merge_custom_fields) {
      customFields = { ...(customFields ?? {}), ...act.merge_custom_fields }
      provenance.custom_fields = src
    }

    if (r.stop_on_match) break
  }

  const sortedOverlays = [...activeOverlays].sort((a, b) =>
    a.seq !== b.seq ? a.seq - b.seq : a.id.localeCompare(b.id),
  )

  for (const ov of sortedOverlays) {
    const src = `overlay:${ov.batch_id}`
    const p = ov.patch_json

    if (p.category !== undefined) { category = p.category; provenance.category = src }
    if (p.merchant_name !== undefined) { merchantName = p.merchant_name; provenance.merchant_name = src }
    if (p.description !== undefined) { description = p.description ?? raw.merchant_name ?? raw.name; provenance.description = src }
    if (p.date !== undefined) { date = p.date ?? raw.date; provenance.date = src }
    if (p.amount_cents !== undefined) { amountCents = p.amount_cents ?? baseAmountCents; provenance.amount_cents = src }
    if (p.tags_set !== undefined) { tags = p.tags_set ? [...dedupeTags(p.tags_set)] : []; provenance.tags = src }
    if (p.tags_add && p.tags_add.length > 0) {
      tags = [...dedupeTags([...tags, ...p.tags_add])]
      provenance.tags = src
    }
    if (p.tags_remove && p.tags_remove.length > 0) {
      const removeSet = new Set(p.tags_remove.map((t) => t.trim().toLowerCase()))
      tags = tags.filter((t) => !removeSet.has(t))
      provenance.tags = src
    }
    if (p.notes !== undefined) { notes = p.notes; provenance.notes = src }
    if (p.is_transfer !== undefined) { isTransfer = p.is_transfer ?? false; provenance.is_transfer = src }
    if (p.transfer_pair_id !== undefined) { transferPairId = p.transfer_pair_id; provenance.transfer_pair_id = src }
    if (p.is_excluded !== undefined) { isExcluded = p.is_excluded ?? false; provenance.is_excluded = src }
    if (p.recurring_group !== undefined) { recurringGroup = p.recurring_group; provenance.recurring_group = src }
    if (p.custom_fields !== undefined) {
      customFields = p.custom_fields === null ? null : { ...(customFields ?? {}), ...p.custom_fields }
      provenance.custom_fields = src
    }
  }

  const finalTags = dedupeTags(tags)

  return {
    id: raw.id,
    source: raw.source,
    account_id: raw.account_id,
    institution_id: raw.institution_id,
    date,
    raw_date: raw.date,
    amount_cents: amountCents,
    raw_amount_cents: raw.raw_amount_cents,
    currency: raw.currency,
    merchant_name: merchantName,
    description,
    raw_name: raw.name,
    category,
    category_top: computeCategoryTop(category),
    raw_category: rawCategory,
    payment_channel: raw.payment_channel,
    pending: raw.pending,
    is_transfer: isTransfer,
    transfer_pair_id: transferPairId,
    is_excluded: isExcluded,
    has_splits: hasSplits,
    has_overlay: sortedOverlays.length > 0 || hasSplits || appliedRuleIds.length > 0,
    recurring_group: recurringGroup,
    tags_json: finalTags,
    tags_text: finalTags.join(" "),
    notes,
    custom_fields_json: customFields,
    provenance_json: provenance,
    applied_rule_ids_json: appliedRuleIds,
  }
}
