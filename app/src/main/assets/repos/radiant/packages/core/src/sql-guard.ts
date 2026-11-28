import { Effect } from "effect"
import type { SqlParam } from "./db"
import { SqlGuardError } from "./errors"

export interface LogicalViewSpec {
  readonly name: string
  readonly description: string
  readonly columns: ReadonlyArray<{ readonly name: string; readonly type: string; readonly note?: string }>
  readonly derivedSql: string
  readonly workspaceParamCount: number
}

export const LOGICAL_VIEWS: Readonly<Record<string, LogicalViewSpec>> = {
  transactions: {
    name: "transactions",
    description:
      "Effective transactions with active splits expanded into line rows (so SUM(amount_cents) never double-counts splits). Uses standard accounting sign: negative = outflow/spending, positive = inflow/income.",
    columns: [
      { name: "id", type: "varchar", note: "Transaction ID (or split line ID when split)" },
      { name: "parent_tx_id", type: "varchar", note: "Parent transaction ID" },
      { name: "is_split_line", type: "boolean" },
      { name: "source", type: "varchar", note: "'plaid' | 'manual'" },
      { name: "account_id", type: "varchar" },
      { name: "institution_id", type: "varchar" },
      { name: "date", type: "varchar", note: "YYYY-MM-DD effective date" },
      { name: "raw_date", type: "varchar", note: "YYYY-MM-DD original bank date" },
      { name: "amount_cents", type: "bigint", note: "Signed cents (- outflow / + inflow)" },
      { name: "amount", type: "decimal", note: "Decimal major units (amount_cents / 100.0)" },
      { name: "currency", type: "varchar" },
      { name: "merchant_name", type: "varchar" },
      { name: "description", type: "varchar" },
      { name: "raw_name", type: "varchar" },
      { name: "category", type: "varchar" },
      { name: "category_top", type: "varchar" },
      { name: "raw_category", type: "varchar" },
      { name: "payment_channel", type: "varchar" },
      { name: "pending", type: "boolean" },
      { name: "is_transfer", type: "boolean" },
      { name: "is_excluded", type: "boolean" },
      { name: "has_overlay", type: "boolean" },
      { name: "recurring_group", type: "varchar" },
      { name: "tags", type: "json" },
      { name: "tags_text", type: "text" },
      { name: "notes", type: "text" },
      { name: "custom_fields", type: "json" },
      { name: "provenance", type: "json" },
    ],
    derivedSql: `(
      SELECT
        et.id AS id, et.id AS parent_tx_id, 0 AS is_split_line, et.source AS source,
        et.account_id AS account_id, et.institution_id AS institution_id,
        et.date AS date, et.raw_date AS raw_date, et.amount_cents AS amount_cents,
        (et.amount_cents / 100.0) AS amount, et.currency AS currency,
        et.merchant_name AS merchant_name, et.description AS description, et.raw_name AS raw_name,
        et.category AS category, et.category_top AS category_top, et.raw_category AS raw_category,
        et.payment_channel AS payment_channel, et.pending AS pending,
        et.is_transfer AS is_transfer, et.is_excluded AS is_excluded,
        et.has_overlay AS has_overlay, et.recurring_group AS recurring_group,
        et.tags_json AS tags, et.tags_text AS tags_text, et.notes AS notes,
        et.custom_fields_json AS custom_fields, et.provenance_json AS provenance
      FROM effective_transaction et
      WHERE et.workspace_id = ? AND et.has_splits = 0
        AND (et.account_id IS NULL OR COALESCE((SELECT ao.is_hidden FROM account_overlay ao WHERE ao.workspace_id = et.workspace_id AND ao.account_id = et.account_id AND ao.active = 1 AND ao.is_hidden IS NOT NULL ORDER BY ao.seq DESC, ao.id DESC LIMIT 1), 0) = 0)
      UNION ALL
      SELECT
        sp.id AS id, et.id AS parent_tx_id, 1 AS is_split_line, et.source AS source,
        et.account_id AS account_id, et.institution_id AS institution_id,
        et.date AS date, et.raw_date AS raw_date, sp.amount_cents AS amount_cents,
        (sp.amount_cents / 100.0) AS amount, et.currency AS currency,
        COALESCE(sp.merchant_name, et.merchant_name) AS merchant_name,
        COALESCE(sp.description, et.description) AS description, et.raw_name AS raw_name,
        COALESCE(sp.category, et.category) AS category,
        COALESCE(sp.category, et.category_top) AS category_top, et.raw_category AS raw_category,
        et.payment_channel AS payment_channel, et.pending AS pending,
        et.is_transfer AS is_transfer, sp.is_excluded AS is_excluded,
        1 AS has_overlay, et.recurring_group AS recurring_group,
        sp.tags_json AS tags, et.tags_text AS tags_text,
        COALESCE(sp.notes, et.notes) AS notes,
        et.custom_fields_json AS custom_fields, et.provenance_json AS provenance
      FROM tx_split sp
      INNER JOIN effective_transaction et ON et.workspace_id = sp.workspace_id AND et.id = sp.tx_id
      WHERE sp.workspace_id = ? AND sp.active = 1
        AND (et.account_id IS NULL OR COALESCE((SELECT ao.is_hidden FROM account_overlay ao WHERE ao.workspace_id = et.workspace_id AND ao.account_id = et.account_id AND ao.active = 1 AND ao.is_hidden IS NOT NULL ORDER BY ao.seq DESC, ao.id DESC LIMIT 1), 0) = 0)
    )`,
    workspaceParamCount: 2,
  },
  transactions_unsplit: {
    name: "transactions_unsplit",
    description: "Effective parent transactions without expanding split lines.",
    columns: [
      { name: "id", type: "varchar" },
      { name: "source", type: "varchar" },
      { name: "account_id", type: "varchar" },
      { name: "institution_id", type: "varchar" },
      { name: "date", type: "varchar" },
      { name: "raw_date", type: "varchar" },
      { name: "amount_cents", type: "bigint" },
      { name: "amount", type: "decimal" },
      { name: "raw_amount_cents", type: "bigint" },
      { name: "currency", type: "varchar" },
      { name: "merchant_name", type: "varchar" },
      { name: "description", type: "varchar" },
      { name: "raw_name", type: "varchar" },
      { name: "category", type: "varchar" },
      { name: "category_top", type: "varchar" },
      { name: "raw_category", type: "varchar" },
      { name: "payment_channel", type: "varchar" },
      { name: "pending", type: "boolean" },
      { name: "is_transfer", type: "boolean" },
      { name: "transfer_pair_id", type: "varchar" },
      { name: "is_excluded", type: "boolean" },
      { name: "has_splits", type: "boolean" },
      { name: "has_overlay", type: "boolean" },
      { name: "recurring_group", type: "varchar" },
      { name: "tags", type: "json" },
      { name: "tags_text", type: "text" },
      { name: "notes", type: "text" },
      { name: "custom_fields", type: "json" },
      { name: "provenance", type: "json" },
      { name: "applied_rule_ids", type: "json" },
    ],
    derivedSql: `(
      SELECT
        id, source, account_id, institution_id, date, raw_date,
        amount_cents, (amount_cents / 100.0) AS amount, raw_amount_cents,
        currency, merchant_name, description, raw_name,
        category, category_top, raw_category, payment_channel,
        pending, is_transfer, transfer_pair_id, is_excluded,
        has_splits, has_overlay, recurring_group,
        tags_json AS tags, tags_text, notes,
        custom_fields_json AS custom_fields,
        provenance_json AS provenance,
        applied_rule_ids_json AS applied_rule_ids
      FROM effective_transaction et
      WHERE et.workspace_id = ?
        AND (et.account_id IS NULL OR COALESCE((SELECT ao.is_hidden FROM account_overlay ao WHERE ao.workspace_id = et.workspace_id AND ao.account_id = et.account_id AND ao.active = 1 AND ao.is_hidden IS NOT NULL ORDER BY ao.seq DESC, ao.id DESC LIMIT 1), 0) = 0)
    )`,
    workspaceParamCount: 1,
  },
  splits: {
    name: "splits",
    description: "Active transaction split lines.",
    columns: [
      { name: "id", type: "varchar" },
      { name: "tx_id", type: "varchar" },
      { name: "batch_id", type: "varchar" },
      { name: "line_index", type: "int" },
      { name: "amount_cents", type: "bigint" },
      { name: "amount", type: "decimal" },
      { name: "category", type: "varchar" },
      { name: "merchant_name", type: "varchar" },
      { name: "description", type: "varchar" },
      { name: "tags", type: "json" },
      { name: "notes", type: "text" },
      { name: "is_excluded", type: "boolean" },
    ],
    derivedSql: `(
      SELECT id, tx_id, batch_id, line_index, amount_cents, (amount_cents / 100.0) AS amount,
        category, merchant_name, description, tags_json AS tags, notes, is_excluded
      FROM tx_split
      WHERE workspace_id = ? AND active = 1
    )`,
    workspaceParamCount: 1,
  },
  raw_transactions: {
    name: "raw_transactions",
    description: "Immutable raw Plaid transactions (raw_amount_cents uses Plaid sign: + outflow, - inflow).",
    columns: [
      { name: "id", type: "varchar" },
      { name: "account_id", type: "varchar" },
      { name: "item_id", type: "varchar" },
      { name: "plaid_transaction_id", type: "varchar" },
      { name: "pending_transaction_id", type: "varchar" },
      { name: "superseded_by", type: "varchar" },
      { name: "raw_amount_cents", type: "bigint" },
      { name: "currency", type: "varchar" },
      { name: "date", type: "varchar" },
      { name: "authorized_date", type: "varchar" },
      { name: "name", type: "varchar" },
      { name: "merchant_name", type: "varchar" },
      { name: "pfc_primary", type: "varchar" },
      { name: "pfc_detailed", type: "varchar" },
      { name: "payment_channel", type: "varchar" },
      { name: "pending", type: "boolean" },
      { name: "counterparty_name", type: "varchar" },
      { name: "raw_json", type: "json" },
      { name: "removed_at", type: "timestamp" },
    ],
    derivedSql: `(
      SELECT id, account_id, item_id, plaid_transaction_id, pending_transaction_id,
        superseded_by, raw_amount_cents, currency, date, authorized_date,
        name, merchant_name, pfc_primary, pfc_detailed, payment_channel,
        pending, counterparty_name, raw_json, removed_at
      FROM raw_transaction
      WHERE workspace_id = ?
    )`,
    workspaceParamCount: 1,
  },
  accounts: {
    name: "accounts",
    description: "Connected accounts with latest Plaid balances and institution info.",
    columns: [
      { name: "id", type: "varchar" },
      { name: "item_id", type: "varchar" },
      { name: "institution_id", type: "varchar" },
      { name: "institution_name", type: "varchar" },
      { name: "name", type: "varchar" },
      { name: "official_name", type: "varchar" },
      { name: "mask", type: "varchar" },
      { name: "type", type: "varchar" },
      { name: "subtype", type: "varchar" },
      { name: "currency", type: "varchar" },
      { name: "current_cents", type: "bigint" },
      { name: "available_cents", type: "bigint" },
      { name: "limit_cents", type: "bigint" },
      { name: "removed_at", type: "timestamp" },
    ],
    derivedSql: `(
      SELECT ra.id, ra.item_id, ra.institution_id, ra.institution_name, ra.name, ra.official_name,
        ra.mask, ra.type, ra.subtype, ra.currency, ra.current_cents, ra.available_cents, ra.limit_cents, ra.removed_at
      FROM raw_account ra
      WHERE ra.workspace_id = ? AND ra.removed_at IS NULL
        AND COALESCE((SELECT ao.is_hidden FROM account_overlay ao WHERE ao.workspace_id = ra.workspace_id AND ao.account_id = ra.id AND ao.active = 1 AND ao.is_hidden IS NOT NULL ORDER BY ao.seq DESC, ao.id DESC LIMIT 1), 0) = 0
    )`,
    workspaceParamCount: 1,
  },
  balance_snapshots: {
    name: "balance_snapshots",
    description: "Historical point-in-time account balance snapshots captured on sync and daily cron.",
    columns: [
      { name: "id", type: "varchar" },
      { name: "account_id", type: "varchar" },
      { name: "captured_at", type: "timestamp" },
      { name: "currency", type: "varchar" },
      { name: "current_cents", type: "bigint" },
      { name: "available_cents", type: "bigint" },
      { name: "limit_cents", type: "bigint" },
    ],
    derivedSql: `(
      SELECT bs.id, bs.account_id, bs.captured_at, bs.currency, bs.current_cents, bs.available_cents, bs.limit_cents
      FROM raw_balance_snapshot bs
      WHERE bs.workspace_id = ?
        AND COALESCE((SELECT ao.is_hidden FROM account_overlay ao WHERE ao.workspace_id = bs.workspace_id AND ao.account_id = bs.account_id AND ao.active = 1 AND ao.is_hidden IS NOT NULL ORDER BY ao.seq DESC, ao.id DESC LIMIT 1), 0) = 0
    )`,
    workspaceParamCount: 1,
  },
  rules: {
    name: "rules",
    description: "Declarative transaction reclassification rules.",
    columns: [
      { name: "id", type: "varchar" },
      { name: "name", type: "varchar" },
      { name: "description", type: "text" },
      { name: "priority", type: "int" },
      { name: "enabled", type: "boolean" },
      { name: "stop_on_match", type: "boolean" },
      { name: "match_json", type: "json" },
      { name: "actions_json", type: "json" },
      { name: "version", type: "int" },
      { name: "created_at", type: "timestamp" },
      { name: "updated_at", type: "timestamp" },
    ],
    derivedSql: `(
      SELECT id, name, description, priority, enabled, stop_on_match,
        match_json, actions_json, version, created_at, updated_at
      FROM rule
      WHERE workspace_id = ? AND deleted_at IS NULL
    )`,
    workspaceParamCount: 1,
  },
  overlay_batches: {
    name: "overlay_batches",
    description: "Undoable change batches applied by humans or agents.",
    columns: [
      { name: "id", type: "varchar" },
      { name: "kind", type: "varchar" },
      { name: "actor_type", type: "varchar" },
      { name: "actor_id", type: "varchar" },
      { name: "client_name", type: "varchar" },
      { name: "reason", type: "text" },
      { name: "affected_count", type: "int" },
      { name: "created_at", type: "timestamp" },
      { name: "reverted_at", type: "timestamp" },
    ],
    derivedSql: `(
      SELECT id, kind, actor_type, actor_id, client_name, reason,
        affected_count, created_at, reverted_at
      FROM overlay_batch
      WHERE workspace_id = ?
    )`,
    workspaceParamCount: 1,
  },
}

type TokenKind = "word" | "quoted_ident" | "string" | "number" | "param" | "punct" | "op"

interface Token {
  readonly kind: TokenKind
  readonly raw: string
  readonly value: string
  readonly upper: string
}

const FORBIDDEN_KEYWORDS = new Set([
  "INSERT", "UPDATE", "DELETE", "REPLACE", "DROP", "ALTER", "CREATE", "TRUNCATE",
  "GRANT", "REVOKE", "SET", "SHOW", "CALL", "DO", "LOAD", "HANDLER", "LOCK", "UNLOCK",
  "USE", "PREPARE", "EXECUTE", "DEALLOCATE", "FLUSH", "RESET", "PURGE", "OPTIMIZE",
  "REPAIR", "ANALYZE", "RENAME", "OUTFILE", "DUMPFILE", "ATTACH", "PRAGMA", "VACUUM",
])

const FORBIDDEN_FUNCTIONS = new Set([
  "SLEEP", "BENCHMARK", "LOAD_FILE", "GET_LOCK", "RELEASE_LOCK", "RELEASE_ALL_LOCKS",
  "IS_FREE_LOCK", "IS_USED_LOCK", "SYSTEM_USER", "SESSION_USER", "CURRENT_USER",
  "USER", "VERSION", "DATABASE", "SCHEMA",
])

const FORBIDDEN_SCHEMAS = new Set([
  "INFORMATION_SCHEMA", "MYSQL", "PERFORMANCE_SCHEMA", "SYS", "VITESS",
])

const CLAUSE_KEYWORDS = new Set([
  "WHERE", "GROUP", "ORDER", "HAVING", "LIMIT", "OFFSET", "UNION", "INTERSECT", "EXCEPT",
  "JOIN", "INNER", "LEFT", "RIGHT", "FULL", "CROSS", "STRAIGHT_JOIN", "NATURAL",
  "ON", "USING", "WINDOW", "QUALIFY", "SET",
])

const BACKTICK = String.fromCharCode(96)

const tokenizeSql = (sql: string): Effect.Effect<ReadonlyArray<Token>, SqlGuardError> => {
  const tokens: Array<Token> = []
  let i = 0
  const len = sql.length

  while (i < len) {
    const ch = sql[i]!
    if (/\s/.test(ch)) { i++; continue }

    if ((ch === "-" && sql[i + 1] === "-") || ch === "#") {
      while (i < len && sql[i] !== "\n") i++
      continue
    }

    if (ch === "/" && sql[i + 1] === "*") {
      const next = sql[i + 2]
      if (next === "!" || next === "+") {
        return Effect.fail(new SqlGuardError({ message: "MySQL executable comments and optimizer hints are not allowed" }))
      }
      const end = sql.indexOf("*/", i + 2)
      if (end === -1) return Effect.fail(new SqlGuardError({ message: "Unterminated block comment" }))
      i = end + 2
      continue
    }

    if (ch === "@") {
      return Effect.fail(new SqlGuardError({ message: "SQL variables (@ / @@) are not allowed" }))
    }

    if (ch === "?") {
      tokens.push({ kind: "param", raw: "?", value: "?", upper: "?" })
      i++
      continue
    }

    if (ch === "'") {
      let j = i + 1
      let val = ""
      let closed = false
      while (j < len) {
        if (sql[j] === "\\" && j + 1 < len) { val += sql[j]! + sql[j + 1]!; j += 2; continue }
        if (sql[j] === "'" && sql[j + 1] === "'") { val += "''"; j += 2; continue }
        if (sql[j] === "'") { closed = true; j++; break }
        val += sql[j]!
        j++
      }
      if (!closed) return Effect.fail(new SqlGuardError({ message: "Unterminated string literal" }))
      const raw = sql.slice(i, j)
      tokens.push({ kind: "string", raw, value: val, upper: raw })
      i = j
      continue
    }

    if (ch === BACKTICK || ch === '"') {
      const quote = ch
      let j = i + 1
      let val = ""
      let closed = false
      while (j < len) {
        if (sql[j] === quote && sql[j + 1] === quote) { val += quote; j += 2; continue }
        if (sql[j] === quote) { closed = true; j++; break }
        val += sql[j]!
        j++
      }
      if (!closed) return Effect.fail(new SqlGuardError({ message: "Unterminated quoted identifier" }))
      const raw = sql.slice(i, j)
      tokens.push({ kind: "quoted_ident", raw, value: val, upper: val.toUpperCase() })
      i = j
      continue
    }

    if (/[0-9]/.test(ch)) {
      let j = i + 1
      while (j < len && /[0-9._eE]/.test(sql[j]!)) j++
      const raw = sql.slice(i, j)
      tokens.push({ kind: "number", raw, value: raw, upper: raw })
      i = j
      continue
    }

    if (/[a-zA-Z_]/.test(ch)) {
      let j = i + 1
      while (j < len && /[a-zA-Z0-9_$]/.test(sql[j]!)) j++
      const raw = sql.slice(i, j)
      tokens.push({ kind: "word", raw, value: raw, upper: raw.toUpperCase() })
      i = j
      continue
    }

    if ("(),.;".includes(ch)) {
      tokens.push({ kind: "punct", raw: ch, value: ch, upper: ch })
      i++
      continue
    }

    const three = sql.slice(i, i + 3)
    if (three === "->>") {
      tokens.push({ kind: "op", raw: three, value: three, upper: three })
      i += 3
      continue
    }
    const two = sql.slice(i, i + 2)
    if (["->", "<=", ">=", "<>", "!=", "||", "&&"].includes(two)) {
      tokens.push({ kind: "op", raw: two, value: two, upper: two })
      i += 2
      continue
    }

    if ("+-*/%=<>!~&|^".includes(ch)) {
      tokens.push({ kind: "op", raw: ch, value: ch, upper: ch })
      i++
      continue
    }

    return Effect.fail(new SqlGuardError({ message: `Unexpected character in SQL: ${ch}` }))
  }

  return Effect.succeed(tokens)
}

const collectCteNames = (tokens: ReadonlyArray<Token>): Set<string> => {
  const ctes = new Set<string>()
  for (let i = 0; i < tokens.length; i++) {
    if (tokens[i]!.kind !== "word" || tokens[i]!.upper !== "WITH") continue
    let j = i + 1
    if (tokens[j]?.kind === "word" && tokens[j]!.upper === "RECURSIVE") j++
    while (j < tokens.length) {
      const nameTok = tokens[j]
      if (!nameTok || (nameTok.kind !== "word" && nameTok.kind !== "quoted_ident")) break
      const cteName = nameTok.value.toLowerCase()
      j++
      if (tokens[j]?.raw === "(") {
        let depth = 1
        j++
        while (j < tokens.length && depth > 0) {
          if (tokens[j]!.raw === "(") depth++
          else if (tokens[j]!.raw === ")") depth--
          j++
        }
      }
      if (tokens[j]?.kind !== "word" || tokens[j]!.upper !== "AS") break
      j++
      if (tokens[j]?.raw !== "(") break
      ctes.add(cteName)
      let depth = 1
      j++
      while (j < tokens.length && depth > 0) {
        if (tokens[j]!.raw === "(") depth++
        else if (tokens[j]!.raw === ")") depth--
        j++
      }
      if (tokens[j]?.raw === ",") { j++; continue }
      break
    }
  }
  return ctes
}

export interface RewrittenSql {
  readonly sql: string
  readonly params: ReadonlyArray<SqlParam>
  readonly limit: number
}

export const rewriteWorkspaceSql = (input: {
  readonly sql: string
  readonly workspaceId: string
  readonly userParams?: ReadonlyArray<SqlParam>
  readonly limit?: number
}): Effect.Effect<RewrittenSql, SqlGuardError> =>
  Effect.gen(function* () {
    const rawSql = input.sql.trim()
    if (rawSql.length === 0) {
      return yield* new SqlGuardError({ message: "SQL query must not be empty" })
    }
    if (rawSql.length > 20_000) {
      return yield* new SqlGuardError({ message: "SQL query exceeds 20,000 character limit" })
    }

    const tokens = yield* tokenizeSql(rawSql)
    if (tokens.length === 0) {
      return yield* new SqlGuardError({ message: "SQL query must not be empty" })
    }

    const trimmed = tokens[tokens.length - 1]!.raw === ";" ? tokens.slice(0, -1) : tokens
    if (trimmed.length === 0) {
      return yield* new SqlGuardError({ message: "SQL query must not be empty" })
    }
    if (trimmed.some((t) => t.raw === ";")) {
      return yield* new SqlGuardError({ message: "Multiple SQL statements are not allowed" })
    }

    const first = trimmed[0]!
    if (first.kind !== "word" || (first.upper !== "SELECT" && first.upper !== "WITH")) {
      return yield* new SqlGuardError({
        message: "Only read-only SELECT and WITH ... SELECT statements are allowed",
      })
    }

    let userParamCount = 0
    for (let i = 0; i < trimmed.length; i++) {
      const tok = trimmed[i]!
      if (tok.kind === "param") userParamCount++
      if (tok.kind === "word") {
        if (FORBIDDEN_KEYWORDS.has(tok.upper)) {
          return yield* new SqlGuardError({ message: `Forbidden SQL keyword: ${tok.upper}` })
        }
        if (
          tok.upper === "FOR" &&
          trimmed[i + 1]?.kind === "word" &&
          (trimmed[i + 1]!.upper === "UPDATE" || trimmed[i + 1]!.upper === "SHARE")
        ) {
          return yield* new SqlGuardError({ message: "Locking reads (FOR UPDATE / FOR SHARE) are not allowed" })
        }
        if (tok.upper === "INTO") {
          return yield* new SqlGuardError({ message: "SELECT ... INTO is not allowed" })
        }
        if (FORBIDDEN_FUNCTIONS.has(tok.upper) && trimmed[i + 1]?.raw === "(") {
          return yield* new SqlGuardError({ message: `Forbidden SQL function: ${tok.upper}()` })
        }
      }
      if (
        (tok.kind === "word" || tok.kind === "quoted_ident") &&
        FORBIDDEN_SCHEMAS.has(tok.upper) &&
        trimmed[i + 1]?.raw === "."
      ) {
        return yield* new SqlGuardError({ message: `Access to system schema '${tok.value}' is not allowed` })
      }
    }

    const userParams = input.userParams ?? []
    if (userParamCount !== userParams.length) {
      return yield* new SqlGuardError({
        message: `Query has ${userParamCount} '?' placeholder(s) but ${userParams.length} parameter(s) were supplied`,
      })
    }

    const cteNames = collectCteNames(trimmed)
    const outParts: Array<string> = []
    const finalParams: Array<SqlParam> = []
    let userParamIdx = 0
    let expectTableRef = false
    const inFromListDepth: Array<number> = []
    let parenDepth = 0

    const pushDerivedTable = (tableName: string, hasExplicitAlias: boolean): Effect.Effect<void, SqlGuardError> => {
      const lower = tableName.toLowerCase()
      if (cteNames.has(lower)) {
        outParts.push(tableName)
        return Effect.void
      }
      const view = LOGICAL_VIEWS[lower]
      if (!view) {
        return Effect.fail(
          new SqlGuardError({
            message: `Table '${tableName}' is not accessible. Allowed views: ${Object.keys(LOGICAL_VIEWS).join(", ")}`,
          }),
        )
      }
      outParts.push(hasExplicitAlias ? view.derivedSql : `${view.derivedSql} AS ${lower}`)
      for (let k = 0; k < view.workspaceParamCount; k++) finalParams.push(input.workspaceId)
      return Effect.void
    }

    for (let i = 0; i < trimmed.length; i++) {
      const tok = trimmed[i]!
      const prev = i > 0 ? trimmed[i - 1] : undefined
      const next = trimmed[i + 1]

      if (tok.raw === "(") {
        parenDepth++
        expectTableRef = false
        outParts.push("(")
        continue
      }
      if (tok.raw === ")") {
        if (inFromListDepth.length > 0 && inFromListDepth[inFromListDepth.length - 1] === parenDepth) {
          inFromListDepth.pop()
        }
        parenDepth--
        expectTableRef = false
        outParts.push(")")
        continue
      }

      if (tok.kind === "param") {
        finalParams.push(userParams[userParamIdx++]!)
        outParts.push("?")
        continue
      }

      if (
        tok.kind === "word" &&
        CLAUSE_KEYWORDS.has(tok.upper) &&
        inFromListDepth.length > 0 &&
        inFromListDepth[inFromListDepth.length - 1] === parenDepth
      ) {
        inFromListDepth.pop()
      }

      if (
        tok.raw === "," &&
        inFromListDepth.length > 0 &&
        inFromListDepth[inFromListDepth.length - 1] === parenDepth
      ) {
        outParts.push(",")
        expectTableRef = true
        continue
      }

      if (expectTableRef) {
        if ((tok.kind === "word" || tok.kind === "quoted_ident") && next?.raw === ".") {
          return yield* new SqlGuardError({
            message: "Schema-qualified table references are not allowed; use the view names from sql_schema",
          })
        }
        if (tok.kind === "word" || tok.kind === "quoted_ident") {
          const hasExplicitAlias =
            (next?.kind === "word" && next.upper === "AS") ||
            (next !== undefined &&
              (next.kind === "word" || next.kind === "quoted_ident") &&
              !CLAUSE_KEYWORDS.has(next.upper))
          yield* pushDerivedTable(tok.value, hasExplicitAlias)
          expectTableRef = false
          continue
        }
        expectTableRef = false
      }

      if (tok.kind === "word" && tok.upper === "FROM") {
        const isFuncFrom =
          parenDepth > 0 &&
          prev !== undefined &&
          (prev.upper === "YEAR" || prev.upper === "MONTH" || prev.upper === "DAY" ||
            prev.upper === "QUARTER" || prev.upper === "WEEK" || prev.upper === "HOUR" ||
            prev.upper === "MINUTE" || prev.upper === "SECOND" || prev.kind === "string")
        outParts.push(tok.raw)
        if (!isFuncFrom) {
          expectTableRef = true
          inFromListDepth.push(parenDepth)
        }
        continue
      }

      if (tok.kind === "word" && (tok.upper === "JOIN" || tok.upper === "STRAIGHT_JOIN")) {
        outParts.push(tok.raw)
        expectTableRef = true
        continue
      }

      outParts.push(tok.raw)
    }

    const effectiveLimit = Math.max(1, Math.min(input.limit ?? 1000, 10_000))
    const innerSql = outParts.join(" ")
    const wrappedSql = `SELECT * FROM (${innerSql}) AS _radiant_q LIMIT ${effectiveLimit}`

    return { sql: wrappedSql, params: finalParams, limit: effectiveLimit }
  })

export const getSqlSchemaCatalog = () => ({
  dialect: "mysql",
  sign_convention:
    "Effective transaction views (transactions, transactions_unsplit, splits) use standard accounting sign: negative = outflow/spending, positive = inflow/income. raw_transactions.raw_amount_cents preserves Plaid's native sign (+ outflow / - inflow). Amounts are integer minor units (cents); decimal 'amount' = amount_cents / 100.0.",
  limits: { default_limit: 1000, max_limit: 10000 },
  views: Object.values(LOGICAL_VIEWS).map((v) => ({
    name: v.name,
    description: v.description,
    columns: v.columns,
  })),
  examples: [
    {
      title: "Monthly spend by top-level category (excluding transfers & excluded)",
      sql: "SELECT SUBSTR(date, 1, 7) AS month, category_top, COUNT(*) AS tx_count, SUM(-amount_cents) / 100.0 AS spend FROM transactions WHERE is_excluded = 0 AND is_transfer = 0 AND amount_cents < 0 GROUP BY month, category_top ORDER BY month DESC, spend DESC",
    },
    {
      title: "Top 15 merchants over a date range",
      sql: "SELECT COALESCE(merchant_name, description) AS merchant, COUNT(*) AS n, SUM(-amount_cents) / 100.0 AS total_spend FROM transactions WHERE is_excluded = 0 AND is_transfer = 0 AND amount_cents < 0 AND date >= '2026-08-25' GROUP BY merchant ORDER BY total_spend DESC LIMIT 15",
    },
    {
      title: "Running cumulative flow by account using window function",
      sql: "SELECT account_id, date, description, amount, SUM(amount_cents) OVER (PARTITION BY account_id ORDER BY date, id) / 100.0 AS cumulative_flow FROM transactions_unsplit ORDER BY account_id, date DESC LIMIT 100",
    },
  ],
})
