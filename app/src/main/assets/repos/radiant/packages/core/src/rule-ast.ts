import { Effect } from "effect"
import type {
  RuleActionPatch,
  RuleConditionField,
  RuleConditionOp,
  RuleMatchNode,
} from "@radiant/database/schema"
import { ValidationError } from "./errors"

export interface MatchContext {
  readonly account_id: string | null
  readonly account_type: string | null
  readonly account_subtype: string | null
  readonly institution_id: string | null
  readonly raw_name: string
  readonly raw_merchant_name: string | null
  readonly raw_category_primary: string | null
  readonly raw_category_detailed: string | null
  readonly payment_channel: string | null
  readonly currency: string
  /** Standard accounting sign (- outflow / + inflow) */
  readonly amount_cents: number
  readonly date: string
  /** 0 = Sunday ... 6 = Saturday (UTC) */
  readonly day_of_week: number
  readonly pending: boolean
  readonly counterparty_name: string | null
}

const VALID_FIELDS = new Set<RuleConditionField>([
  "account_id",
  "account_type",
  "account_subtype",
  "institution_id",
  "raw_name",
  "raw_merchant_name",
  "raw_category_primary",
  "raw_category_detailed",
  "payment_channel",
  "currency",
  "amount_cents",
  "date",
  "day_of_week",
  "pending",
  "counterparty_name",
])

const VALID_OPS = new Set<RuleConditionOp>([
  "eq",
  "neq",
  "in",
  "not_in",
  "contains",
  "icontains",
  "starts_with",
  "ends_with",
  "regex",
  "gt",
  "gte",
  "lt",
  "lte",
  "between",
  "is_null",
])

const MAX_AST_DEPTH = 10
const MAX_REGEX_LENGTH = 200

const validateNode = (node: unknown, depth: number): string | null => {
  if (depth > MAX_AST_DEPTH) return "Rule match expression exceeds maximum nesting depth"
  if (!node || typeof node !== "object" || Array.isArray(node)) {
    return "Rule match node must be an object"
  }
  const rec = node as Record<string, unknown>

  if ("all" in rec) {
    if (!Array.isArray(rec.all) || rec.all.length === 0) {
      return "'all' must be a non-empty array of match nodes"
    }
    for (const child of rec.all) {
      const err = validateNode(child, depth + 1)
      if (err) return err
    }
    return null
  }

  if ("any" in rec) {
    if (!Array.isArray(rec.any) || rec.any.length === 0) {
      return "'any' must be a non-empty array of match nodes"
    }
    for (const child of rec.any) {
      const err = validateNode(child, depth + 1)
      if (err) return err
    }
    return null
  }

  if ("not" in rec) {
    return validateNode(rec.not, depth + 1)
  }

  const field = rec.field
  const op = rec.op
  if (typeof field !== "string" || !VALID_FIELDS.has(field as RuleConditionField)) {
    return `Invalid rule match field: ${String(field)}`
  }
  if (typeof op !== "string" || !VALID_OPS.has(op as RuleConditionOp)) {
    return `Invalid rule match operator: ${String(op)}`
  }
  if (op === "between") {
    if (!Array.isArray(rec.value) || rec.value.length !== 2) {
      return "'between' operator requires a 2-element [min, max] array"
    }
  }
  if ((op === "in" || op === "not_in") && !Array.isArray(rec.value)) {
    return `'${op}' operator requires an array value`
  }
  if (op === "regex") {
    if (typeof rec.value !== "string" || rec.value.length === 0 || rec.value.length > MAX_REGEX_LENGTH) {
      return `'regex' value must be a string of 1..${MAX_REGEX_LENGTH} chars`
    }
    try {
      new RegExp(rec.value, "i")
    } catch {
      return `Invalid regex pattern: ${rec.value}`
    }
  }
  return null
}

export const validateRuleMatch = (node: unknown): Effect.Effect<RuleMatchNode, ValidationError> => {
  const err = validateNode(node, 0)
  return err
    ? Effect.fail(new ValidationError({ message: err, field: "match" }))
    : Effect.succeed(node as RuleMatchNode)
}

export const validateRuleActions = (actions: unknown): Effect.Effect<RuleActionPatch, ValidationError> => {
  if (!actions || typeof actions !== "object" || Array.isArray(actions)) {
    return Effect.fail(new ValidationError({ message: "Rule actions must be an object", field: "actions" }))
  }
  const rec = actions as Record<string, unknown>
  const allowedKeys = new Set([
    "set_category",
    "set_merchant_name",
    "set_description",
    "add_tags",
    "remove_tags",
    "set_is_transfer",
    "set_is_excluded",
    "set_notes",
    "set_recurring_group",
    "merge_custom_fields",
  ])
  const keys = Object.keys(rec)
  if (keys.length === 0) {
    return Effect.fail(new ValidationError({ message: "Rule actions must specify at least one action", field: "actions" }))
  }
  for (const key of keys) {
    if (!allowedKeys.has(key)) {
      return Effect.fail(new ValidationError({ message: `Unknown rule action: ${key}`, field: "actions" }))
    }
  }
  return Effect.succeed(rec as RuleActionPatch)
}

export const dayOfWeekUtc = (isoDate: string): number => {
  const parsed = Date.parse(`${isoDate}T00:00:00Z`)
  return Number.isNaN(parsed) ? 0 : new Date(parsed).getUTCDay()
}

const evalLeaf = (
  ctx: MatchContext,
  field: RuleConditionField,
  op: RuleConditionOp,
  value: unknown,
): boolean => {
  const actual = ctx[field]

  if (op === "is_null") {
    const expectNull = value === undefined ? true : Boolean(value)
    return expectNull ? actual === null || actual === undefined : actual !== null && actual !== undefined
  }

  if (actual === null || actual === undefined) {
    return op === "neq" || op === "not_in"
  }

  switch (op) {
    case "eq":
      return actual === value
    case "neq":
      return actual !== value
    case "in":
      return Array.isArray(value) && value.includes(actual)
    case "not_in":
      return Array.isArray(value) && !value.includes(actual)
    case "contains":
      return typeof actual === "string" && typeof value === "string" && actual.includes(value)
    case "icontains":
      return (
        typeof actual === "string" &&
        typeof value === "string" &&
        actual.toLowerCase().includes(value.toLowerCase())
      )
    case "starts_with":
      return (
        typeof actual === "string" &&
        typeof value === "string" &&
        actual.toLowerCase().startsWith(value.toLowerCase())
      )
    case "ends_with":
      return (
        typeof actual === "string" &&
        typeof value === "string" &&
        actual.toLowerCase().endsWith(value.toLowerCase())
      )
    case "regex": {
      if (typeof actual !== "string" || typeof value !== "string") return false
      try {
        return new RegExp(value, "i").test(actual)
      } catch {
        return false
      }
    }
    case "gt":
      return typeof actual === "number" && typeof value === "number"
        ? actual > value
        : String(actual) > String(value)
    case "gte":
      return typeof actual === "number" && typeof value === "number"
        ? actual >= value
        : String(actual) >= String(value)
    case "lt":
      return typeof actual === "number" && typeof value === "number"
        ? actual < value
        : String(actual) < String(value)
    case "lte":
      return typeof actual === "number" && typeof value === "number"
        ? actual <= value
        : String(actual) <= String(value)
    case "between": {
      if (!Array.isArray(value) || value.length !== 2) return false
      const [lo, hi] = value as [unknown, unknown]
      if (typeof actual === "number" && typeof lo === "number" && typeof hi === "number") {
        return actual >= lo && actual <= hi
      }
      const s = String(actual)
      return s >= String(lo) && s <= String(hi)
    }
  }
}

export const evaluateRuleMatch = (node: RuleMatchNode, ctx: MatchContext): boolean => {
  if ("all" in node) return node.all.every((child) => evaluateRuleMatch(child, ctx))
  if ("any" in node) return node.any.some((child) => evaluateRuleMatch(child, ctx))
  if ("not" in node) return !evaluateRuleMatch(node.not, ctx)
  return evalLeaf(ctx, node.field, node.op, node.value)
}
