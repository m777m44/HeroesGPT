import {
  bigint,
  boolean,
  index,
  int,
  json,
  mysqlTable,
  primaryKey,
  text,
  timestamp,
  uniqueIndex,
  varchar,
} from "drizzle-orm/mysql-core"

export type WorkspaceRole = "owner" | "admin" | "member" | "viewer"

export type SyncTrigger = "initial" | "webhook" | "manual" | "cron"

export type BatchKind =
  | "tx_overlay"
  | "tx_split"
  | "tx_reset"
  | "tx_manual"
  | "account_overlay"
  | "rule_create"
  | "rule_update"
  | "rule_reorder"
  | "rule_toggle"
  | "rule_delete"
  | "pending_carry_forward"

export interface TxPatch {
  category?: string | null
  merchant_name?: string | null
  description?: string | null
  date?: string | null
  amount_cents?: number | null
  tags_set?: ReadonlyArray<string> | null
  tags_add?: ReadonlyArray<string>
  tags_remove?: ReadonlyArray<string>
  notes?: string | null
  is_transfer?: boolean | null
  transfer_pair_id?: string | null
  is_excluded?: boolean | null
  recurring_group?: string | null
  custom_fields?: Record<string, unknown> | null
}

export interface RuleActionPatch {
  set_category?: string
  set_merchant_name?: string
  set_description?: string
  add_tags?: ReadonlyArray<string>
  remove_tags?: ReadonlyArray<string>
  set_is_transfer?: boolean
  set_is_excluded?: boolean
  set_notes?: string
  set_recurring_group?: string
  merge_custom_fields?: Record<string, unknown>
}

export type RuleConditionOp =
  | "eq"
  | "neq"
  | "in"
  | "not_in"
  | "contains"
  | "icontains"
  | "starts_with"
  | "ends_with"
  | "regex"
  | "gt"
  | "gte"
  | "lt"
  | "lte"
  | "between"
  | "is_null"

export type RuleConditionField =
  | "account_id"
  | "account_type"
  | "account_subtype"
  | "institution_id"
  | "raw_name"
  | "raw_merchant_name"
  | "raw_category_primary"
  | "raw_category_detailed"
  | "payment_channel"
  | "currency"
  | "amount_cents"
  | "date"
  | "day_of_week"
  | "pending"
  | "counterparty_name"

export type RuleMatchNode =
  | { all: ReadonlyArray<RuleMatchNode> }
  | { any: ReadonlyArray<RuleMatchNode> }
  | { not: RuleMatchNode }
  | { field: RuleConditionField; op: RuleConditionOp; value?: unknown }

export type ProvenanceMap = Record<string, string>

// ── Identity, Sessions & OAuth 2.1 ──────────────────────────────────────────

export const user = mysqlTable(
  "user",
  {
    id: varchar({ length: 36 }).primaryKey(),
    external_sub: varchar({ length: 255 }).notNull(),
    issuer: varchar({ length: 255 }).notNull(),
    email: varchar({ length: 320 }).notNull(),
    name: varchar({ length: 255 }),
    created_at: timestamp({ fsp: 3 }).notNull().defaultNow(),
    updated_at: timestamp({ fsp: 3 }).notNull().defaultNow(),
    disabled_at: timestamp({ fsp: 3 }),
  },
  (table) => [
    uniqueIndex("uq_user_issuer_sub").on(table.issuer, table.external_sub),
    index("idx_user_email").on(table.email),
  ],
)

export const session = mysqlTable(
  "session",
  {
    id: varchar({ length: 36 }).primaryKey(),
    user_id: varchar({ length: 36 }).notNull(),
    token_hash: varchar({ length: 64 }).notNull(),
    expires_at: timestamp({ fsp: 3 }).notNull(),
    created_at: timestamp({ fsp: 3 }).notNull().defaultNow(),
    revoked_at: timestamp({ fsp: 3 }),
  },
  (table) => [
    uniqueIndex("uq_session_token").on(table.token_hash),
    index("idx_session_user").on(table.user_id),
  ],
)

export const oauth_client = mysqlTable("oauth_client", {
  id: varchar({ length: 64 }).primaryKey(),
  name: varchar({ length: 255 }).notNull(),
  redirect_uris: json().$type<ReadonlyArray<string>>().notNull(),
  created_at: timestamp({ fsp: 3 }).notNull().defaultNow(),
})

export const oauth_flow = mysqlTable(
  "oauth_flow",
  {
    id: varchar({ length: 64 }).primaryKey(),
    kind: varchar({ length: 32 }).notNull(), // "browser_login" | "mcp_oauth" | "device"
    client_id: varchar({ length: 64 }),
    redirect_uri: text(),
    state: varchar({ length: 512 }),
    code_challenge: varchar({ length: 128 }),
    code_challenge_method: varchar({ length: 16 }),
    scope: varchar({ length: 255 }),
    upstream_verifier: varchar({ length: 128 }),
    upstream_nonce: varchar({ length: 128 }),
    browser_binding_hash: varchar({ length: 64 }),
    return_to: text(),
    approved_user_id: varchar({ length: 36 }),
    expires_at: timestamp({ fsp: 3 }).notNull(),
    consumed_at: timestamp({ fsp: 3 }),
    created_at: timestamp({ fsp: 3 }).notNull().defaultNow(),
  },
  (table) => [index("idx_oauth_flow_exp").on(table.expires_at)],
)

export const oauth_code = mysqlTable(
  "oauth_code",
  {
    code_hash: varchar({ length: 64 }).primaryKey(),
    client_id: varchar({ length: 64 }).notNull(),
    user_id: varchar({ length: 36 }).notNull(),
    redirect_uri: text().notNull(),
    code_challenge: varchar({ length: 128 }).notNull(),
    scope: varchar({ length: 255 }).notNull(),
    expires_at: timestamp({ fsp: 3 }).notNull(),
    consumed_at: timestamp({ fsp: 3 }),
    created_at: timestamp({ fsp: 3 }).notNull().defaultNow(),
  },
  (table) => [index("idx_oauth_code_user").on(table.user_id)],
)

export const oauth_grant = mysqlTable(
  "oauth_grant",
  {
    id: varchar({ length: 36 }).primaryKey(),
    client_id: varchar({ length: 64 }).notNull(),
    client_name: varchar({ length: 255 }).notNull(),
    user_id: varchar({ length: 36 }).notNull(),
    scope: varchar({ length: 255 }).notNull(),
    access_token_hash: varchar({ length: 64 }).notNull(),
    access_expires_at: timestamp({ fsp: 3 }).notNull(),
    refresh_token_hash: varchar({ length: 64 }).notNull(),
    refresh_expires_at: timestamp({ fsp: 3 }).notNull(),
    previous_refresh_hash: varchar({ length: 64 }),
    revoked_at: timestamp({ fsp: 3 }),
    created_at: timestamp({ fsp: 3 }).notNull().defaultNow(),
    updated_at: timestamp({ fsp: 3 }).notNull().defaultNow(),
  },
  (table) => [
    uniqueIndex("uq_oauth_grant_access").on(table.access_token_hash),
    uniqueIndex("uq_oauth_grant_refresh").on(table.refresh_token_hash),
    index("idx_oauth_grant_user").on(table.user_id),
  ],
)

export const device_code = mysqlTable(
  "device_code",
  {
    id: varchar({ length: 36 }).primaryKey(),
    device_code_hash: varchar({ length: 64 }).notNull(),
    user_code: varchar({ length: 16 }).notNull(),
    client_name: varchar({ length: 120 }).notNull(),
    status: varchar({ length: 24 }).notNull(), // "pending" | "approved" | "denied" | "consumed"
    user_id: varchar({ length: 36 }),
    interval_seconds: int().notNull().default(5),
    last_polled_at: timestamp({ fsp: 3 }),
    expires_at: timestamp({ fsp: 3 }).notNull(),
    created_at: timestamp({ fsp: 3 }).notNull().defaultNow(),
  },
  (table) => [
    uniqueIndex("uq_device_code_hash").on(table.device_code_hash),
    uniqueIndex("uq_device_user_code").on(table.user_code),
  ],
)

export const api_token = mysqlTable(
  "api_token",
  {
    id: varchar({ length: 36 }).primaryKey(),
    workspace_id: varchar({ length: 36 }).notNull(),
    user_id: varchar({ length: 36 }).notNull(),
    name: varchar({ length: 120 }).notNull(),
    role: varchar({ length: 16 }).$type<WorkspaceRole>().notNull(),
    token_hash: varchar({ length: 64 }).notNull(),
    last_used_at: timestamp({ fsp: 3 }),
    expires_at: timestamp({ fsp: 3 }),
    revoked_at: timestamp({ fsp: 3 }),
    created_at: timestamp({ fsp: 3 }).notNull().defaultNow(),
  },
  (table) => [
    uniqueIndex("uq_api_token_hash").on(table.token_hash),
    index("idx_api_token_ws_user").on(table.workspace_id, table.user_id),
  ],
)

// ── Workspaces, Members & Invites ───────────────────────────────────────────

export const workspace = mysqlTable(
  "workspace",
  {
    id: varchar({ length: 36 }).primaryKey(),
    slug: varchar({ length: 80 }).notNull(),
    name: varchar({ length: 120 }).notNull(),
    currency: varchar({ length: 8 }).notNull().default("USD"),
    created_by: varchar({ length: 36 }).notNull(),
    created_at: timestamp({ fsp: 3 }).notNull().defaultNow(),
    updated_at: timestamp({ fsp: 3 }).notNull().defaultNow(),
    deleted_at: timestamp({ fsp: 3 }),
  },
  (table) => [uniqueIndex("uq_workspace_slug").on(table.slug)],
)

export const workspace_member = mysqlTable(
  "workspace_member",
  {
    workspace_id: varchar({ length: 36 }).notNull(),
    user_id: varchar({ length: 36 }).notNull(),
    role: varchar({ length: 16 }).$type<WorkspaceRole>().notNull(),
    created_at: timestamp({ fsp: 3 }).notNull().defaultNow(),
    updated_at: timestamp({ fsp: 3 }).notNull().defaultNow(),
  },
  (table) => [
    primaryKey({ columns: [table.workspace_id, table.user_id] }),
    index("idx_ws_member_user").on(table.user_id, table.workspace_id),
  ],
)

export const workspace_invite = mysqlTable(
  "workspace_invite",
  {
    workspace_id: varchar({ length: 36 }).notNull(),
    id: varchar({ length: 36 }).notNull(),
    email: varchar({ length: 320 }).notNull(),
    role: varchar({ length: 16 }).$type<WorkspaceRole>().notNull(),
    token_hash: varchar({ length: 64 }).notNull(),
    invited_by: varchar({ length: 36 }).notNull(),
    expires_at: timestamp({ fsp: 3 }).notNull(),
    accepted_at: timestamp({ fsp: 3 }),
    accepted_by: varchar({ length: 36 }),
    revoked_at: timestamp({ fsp: 3 }),
    created_at: timestamp({ fsp: 3 }).notNull().defaultNow(),
  },
  (table) => [
    primaryKey({ columns: [table.workspace_id, table.id] }),
    uniqueIndex("uq_ws_invite_token").on(table.token_hash),
    index("idx_ws_invite_ws_email").on(table.workspace_id, table.email),
  ],
)

// ── Plaid Credentials & Handoff Tokens (NEVER exposed to sql_query) ─────────

export const plaid_credential = mysqlTable(
  "plaid_credential",
  {
    workspace_id: varchar({ length: 36 }).notNull(),
    item_id: varchar({ length: 128 }).notNull(),
    access_token_enc: text().notNull(),
    key_version: varchar({ length: 32 }).notNull(),
    created_by: varchar({ length: 36 }).notNull(),
    created_at: timestamp({ fsp: 3 }).notNull().defaultNow(),
    revoked_at: timestamp({ fsp: 3 }),
  },
  (table) => [
    primaryKey({ columns: [table.workspace_id, table.item_id] }),
    uniqueIndex("uq_plaid_cred_item").on(table.item_id),
  ],
)

export const connect_token = mysqlTable(
  "connect_token",
  {
    token_hash: varchar({ length: 64 }).primaryKey(),
    workspace_id: varchar({ length: 36 }).notNull(),
    user_id: varchar({ length: 36 }).notNull(),
    mode: varchar({ length: 16 }).notNull(), // "new" | "update"
    item_id: varchar({ length: 128 }),
    expires_at: timestamp({ fsp: 3 }).notNull(),
    consumed_at: timestamp({ fsp: 3 }),
    created_at: timestamp({ fsp: 3 }).notNull().defaultNow(),
  },
  (table) => [index("idx_connect_token_ws").on(table.workspace_id)],
)

// ── Lossless Plaid Raw Tables (Mutated ONLY by Plaid Sync) ──────────────────

export const raw_item = mysqlTable(
  "raw_item",
  {
    workspace_id: varchar({ length: 36 }).notNull(),
    item_id: varchar({ length: 128 }).notNull(),
    institution_id: varchar({ length: 128 }).notNull(),
    institution_name: varchar({ length: 255 }).notNull(),
    status: varchar({ length: 32 }).notNull().default("healthy"), // "healthy" | "needs_reauth" | "error" | "disconnected"
    error_code: varchar({ length: 128 }),
    error_message: text(),
    sync_cursor: varchar({ length: 512 }),
    last_synced_at: timestamp({ fsp: 3 }),
    consent_expires_at: timestamp({ fsp: 3 }),
    raw_json: json().$type<Record<string, unknown>>().notNull(),
    created_at: timestamp({ fsp: 3 }).notNull().defaultNow(),
    updated_at: timestamp({ fsp: 3 }).notNull().defaultNow(),
    disconnected_at: timestamp({ fsp: 3 }),
  },
  (table) => [
    primaryKey({ columns: [table.workspace_id, table.item_id] }),
    index("idx_raw_item_ws_status").on(table.workspace_id, table.status),
  ],
)

export const raw_account = mysqlTable(
  "raw_account",
  {
    workspace_id: varchar({ length: 36 }).notNull(),
    id: varchar({ length: 36 }).notNull(),
    item_id: varchar({ length: 128 }).notNull(),
    plaid_account_id: varchar({ length: 128 }).notNull(),
    institution_id: varchar({ length: 128 }).notNull(),
    institution_name: varchar({ length: 255 }).notNull(),
    name: varchar({ length: 255 }).notNull(),
    official_name: varchar({ length: 255 }),
    mask: varchar({ length: 32 }),
    type: varchar({ length: 64 }).notNull(),
    subtype: varchar({ length: 64 }),
    currency: varchar({ length: 8 }).notNull().default("USD"),
    current_cents: bigint({ mode: "number" }),
    available_cents: bigint({ mode: "number" }),
    limit_cents: bigint({ mode: "number" }),
    raw_json: json().$type<Record<string, unknown>>().notNull(),
    created_at: timestamp({ fsp: 3 }).notNull().defaultNow(),
    updated_at: timestamp({ fsp: 3 }).notNull().defaultNow(),
    removed_at: timestamp({ fsp: 3 }),
  },
  (table) => [
    primaryKey({ columns: [table.workspace_id, table.id] }),
    uniqueIndex("uq_raw_account_plaid").on(table.workspace_id, table.plaid_account_id),
    index("idx_raw_account_ws_item").on(table.workspace_id, table.item_id),
    index("idx_raw_account_dedup").on(table.workspace_id, table.institution_id, table.mask, table.type),
  ],
)

export const raw_balance_snapshot = mysqlTable(
  "raw_balance_snapshot",
  {
    workspace_id: varchar({ length: 36 }).notNull(),
    id: varchar({ length: 36 }).notNull(),
    account_id: varchar({ length: 36 }).notNull(),
    captured_at: timestamp({ fsp: 3 }).notNull(),
    currency: varchar({ length: 8 }).notNull().default("USD"),
    current_cents: bigint({ mode: "number" }),
    available_cents: bigint({ mode: "number" }),
    limit_cents: bigint({ mode: "number" }),
  },
  (table) => [
    primaryKey({ columns: [table.workspace_id, table.id] }),
    index("idx_balance_snap_ws_acc_at").on(table.workspace_id, table.account_id, table.captured_at),
    index("idx_balance_snap_ws_at").on(table.workspace_id, table.captured_at),
  ],
)

export const raw_transaction = mysqlTable(
  "raw_transaction",
  {
    workspace_id: varchar({ length: 36 }).notNull(),
    id: varchar({ length: 36 }).notNull(),
    account_id: varchar({ length: 36 }).notNull(),
    item_id: varchar({ length: 128 }).notNull(),
    plaid_transaction_id: varchar({ length: 128 }).notNull(),
    pending_transaction_id: varchar({ length: 128 }),
    superseded_by: varchar({ length: 36 }),
    raw_amount_cents: bigint({ mode: "number" }).notNull(), // Plaid native sign: + outflow, - inflow
    currency: varchar({ length: 8 }).notNull().default("USD"),
    date: varchar({ length: 10 }).notNull(), // YYYY-MM-DD
    authorized_date: varchar({ length: 10 }),
    name: varchar({ length: 512 }).notNull(),
    merchant_name: varchar({ length: 255 }),
    merchant_entity_id: varchar({ length: 128 }),
    pfc_primary: varchar({ length: 128 }),
    pfc_detailed: varchar({ length: 128 }),
    pfc_confidence: varchar({ length: 32 }),
    payment_channel: varchar({ length: 64 }),
    pending: boolean().notNull().default(false),
    counterparty_name: varchar({ length: 255 }),
    raw_json: json().$type<Record<string, unknown>>().notNull(),
    created_at: timestamp({ fsp: 3 }).notNull().defaultNow(),
    updated_at: timestamp({ fsp: 3 }).notNull().defaultNow(),
    removed_at: timestamp({ fsp: 3 }),
  },
  (table) => [
    primaryKey({ columns: [table.workspace_id, table.id] }),
    uniqueIndex("uq_raw_tx_plaid").on(table.workspace_id, table.plaid_transaction_id),
    index("idx_raw_tx_ws_acc_date").on(table.workspace_id, table.account_id, table.date),
    index("idx_raw_tx_ws_pending").on(table.workspace_id, table.pending_transaction_id),
  ],
)

export const sync_run = mysqlTable(
  "sync_run",
  {
    workspace_id: varchar({ length: 36 }).notNull(),
    id: varchar({ length: 36 }).notNull(),
    item_id: varchar({ length: 128 }).notNull(),
    trigger: varchar({ length: 24 }).$type<SyncTrigger>().notNull(),
    status: varchar({ length: 24 }).notNull(), // "running" | "succeeded" | "failed"
    added_count: int().notNull().default(0),
    modified_count: int().notNull().default(0),
    removed_count: int().notNull().default(0),
    rules_applied_count: int().notNull().default(0),
    cursor_before: varchar({ length: 512 }),
    cursor_after: varchar({ length: 512 }),
    error_code: varchar({ length: 128 }),
    error_message: text(),
    started_at: timestamp({ fsp: 3 }).notNull().defaultNow(),
    finished_at: timestamp({ fsp: 3 }),
  },
  (table) => [
    primaryKey({ columns: [table.workspace_id, table.id] }),
    index("idx_sync_run_ws_item_at").on(table.workspace_id, table.item_id, table.started_at),
  ],
)

// ── Non-Destructive Overlay, Rules & Undo Tables ────────────────────────────

export const overlay_batch = mysqlTable(
  "overlay_batch",
  {
    workspace_id: varchar({ length: 36 }).notNull(),
    id: varchar({ length: 36 }).notNull(),
    kind: varchar({ length: 32 }).$type<BatchKind>().notNull(),
    actor_type: varchar({ length: 16 }).notNull(), // "user" | "agent" | "system"
    actor_id: varchar({ length: 36 }).notNull(),
    client_name: varchar({ length: 120 }),
    reason: text(),
    payload_json: json().$type<Record<string, unknown>>(),
    affected_count: int().notNull().default(0),
    created_at: timestamp({ fsp: 3 }).notNull().defaultNow(),
    reverted_at: timestamp({ fsp: 3 }),
    reverted_by: varchar({ length: 36 }),
  },
  (table) => [
    primaryKey({ columns: [table.workspace_id, table.id] }),
    index("idx_overlay_batch_ws_at").on(table.workspace_id, table.created_at),
  ],
)

export const tx_overlay = mysqlTable(
  "tx_overlay",
  {
    workspace_id: varchar({ length: 36 }).notNull(),
    id: varchar({ length: 36 }).notNull(),
    batch_id: varchar({ length: 36 }).notNull(),
    tx_id: varchar({ length: 36 }).notNull(),
    seq: bigint({ mode: "number" }).notNull(),
    patch_json: json().$type<TxPatch>().notNull(),
    active: boolean().notNull().default(true),
    created_at: timestamp({ fsp: 3 }).notNull().defaultNow(),
  },
  (table) => [
    primaryKey({ columns: [table.workspace_id, table.id] }),
    index("idx_tx_overlay_ws_tx").on(table.workspace_id, table.tx_id, table.active, table.seq),
    index("idx_tx_overlay_ws_batch").on(table.workspace_id, table.batch_id),
  ],
)

export const tx_split = mysqlTable(
  "tx_split",
  {
    workspace_id: varchar({ length: 36 }).notNull(),
    id: varchar({ length: 36 }).notNull(),
    batch_id: varchar({ length: 36 }).notNull(),
    tx_id: varchar({ length: 36 }).notNull(),
    line_index: int().notNull(),
    amount_cents: bigint({ mode: "number" }).notNull(),
    category: varchar({ length: 255 }),
    merchant_name: varchar({ length: 255 }),
    description: varchar({ length: 512 }),
    tags_json: json().$type<ReadonlyArray<string>>().notNull(),
    notes: text(),
    is_excluded: boolean().notNull().default(false),
    active: boolean().notNull().default(true),
    created_at: timestamp({ fsp: 3 }).notNull().defaultNow(),
  },
  (table) => [
    primaryKey({ columns: [table.workspace_id, table.id] }),
    index("idx_tx_split_ws_tx").on(table.workspace_id, table.tx_id, table.active, table.line_index),
    index("idx_tx_split_ws_batch").on(table.workspace_id, table.batch_id),
  ],
)

export const account_overlay = mysqlTable(
  "account_overlay",
  {
    workspace_id: varchar({ length: 36 }).notNull(),
    id: varchar({ length: 36 }).notNull(),
    batch_id: varchar({ length: 36 }).notNull(),
    account_id: varchar({ length: 36 }).notNull(),
    seq: bigint({ mode: "number" }).notNull(),
    nickname: varchar({ length: 255 }),
    account_group: varchar({ length: 120 }),
    owner_label: varchar({ length: 120 }),
    is_hidden: boolean(),
    is_excluded_from_net_worth: boolean(),
    notes: text(),
    active: boolean().notNull().default(true),
    created_at: timestamp({ fsp: 3 }).notNull().defaultNow(),
  },
  (table) => [
    primaryKey({ columns: [table.workspace_id, table.id] }),
    index("idx_acc_overlay_ws_acc").on(table.workspace_id, table.account_id, table.active, table.seq),
    index("idx_acc_overlay_ws_batch").on(table.workspace_id, table.batch_id),
  ],
)

export const manual_transaction = mysqlTable(
  "manual_transaction",
  {
    workspace_id: varchar({ length: 36 }).notNull(),
    id: varchar({ length: 36 }).notNull(),
    batch_id: varchar({ length: 36 }).notNull(),
    account_id: varchar({ length: 36 }),
    date: varchar({ length: 10 }).notNull(),
    amount_cents: bigint({ mode: "number" }).notNull(), // standard accounting sign: - outflow / + inflow
    currency: varchar({ length: 8 }).notNull().default("USD"),
    merchant_name: varchar({ length: 255 }),
    description: varchar({ length: 512 }).notNull(),
    category: varchar({ length: 255 }),
    tags_json: json().$type<ReadonlyArray<string>>().notNull(),
    notes: text(),
    is_transfer: boolean().notNull().default(false),
    is_excluded: boolean().notNull().default(false),
    custom_fields_json: json().$type<Record<string, unknown>>(),
    active: boolean().notNull().default(true),
    created_at: timestamp({ fsp: 3 }).notNull().defaultNow(),
  },
  (table) => [
    primaryKey({ columns: [table.workspace_id, table.id] }),
    index("idx_manual_tx_ws_batch").on(table.workspace_id, table.batch_id),
    index("idx_manual_tx_ws_active_date").on(table.workspace_id, table.active, table.date),
  ],
)

export const rule = mysqlTable(
  "rule",
  {
    workspace_id: varchar({ length: 36 }).notNull(),
    id: varchar({ length: 36 }).notNull(),
    name: varchar({ length: 160 }).notNull(),
    description: text(),
    priority: int().notNull().default(100),
    enabled: boolean().notNull().default(true),
    stop_on_match: boolean().notNull().default(false),
    match_json: json().$type<RuleMatchNode>().notNull(),
    actions_json: json().$type<RuleActionPatch>().notNull(),
    version: int().notNull().default(1),
    created_at: timestamp({ fsp: 3 }).notNull().defaultNow(),
    updated_at: timestamp({ fsp: 3 }).notNull().defaultNow(),
    deleted_at: timestamp({ fsp: 3 }),
  },
  (table) => [
    primaryKey({ columns: [table.workspace_id, table.id] }),
    index("idx_rule_ws_enabled_prio").on(table.workspace_id, table.enabled, table.priority),
  ],
)

export const rule_application = mysqlTable(
  "rule_application",
  {
    workspace_id: varchar({ length: 36 }).notNull(),
    rule_id: varchar({ length: 36 }).notNull(),
    tx_id: varchar({ length: 36 }).notNull(),
    applied_at: timestamp({ fsp: 3 }).notNull().defaultNow(),
  },
  (table) => [
    primaryKey({ columns: [table.workspace_id, table.rule_id, table.tx_id] }),
    index("idx_rule_app_ws_tx").on(table.workspace_id, table.tx_id),
  ],
)

// ── Materialized Effective Layer (Fast Indexed Queries & Aggregations) ──────

export const effective_transaction = mysqlTable(
  "effective_transaction",
  {
    workspace_id: varchar({ length: 36 }).notNull(),
    id: varchar({ length: 36 }).notNull(),
    source: varchar({ length: 16 }).notNull(), // "plaid" | "manual"
    account_id: varchar({ length: 36 }),
    institution_id: varchar({ length: 128 }),
    date: varchar({ length: 10 }).notNull(), // YYYY-MM-DD (effective)
    raw_date: varchar({ length: 10 }).notNull(),
    amount_cents: bigint({ mode: "number" }).notNull(), // standard accounting sign: - outflow / + inflow
    raw_amount_cents: bigint({ mode: "number" }).notNull(), // Plaid native sign (or manual amount)
    currency: varchar({ length: 8 }).notNull().default("USD"),
    merchant_name: varchar({ length: 255 }),
    description: varchar({ length: 512 }).notNull(),
    raw_name: varchar({ length: 512 }).notNull(),
    category: varchar({ length: 255 }),
    category_top: varchar({ length: 128 }),
    raw_category: varchar({ length: 255 }),
    payment_channel: varchar({ length: 64 }),
    pending: boolean().notNull().default(false),
    is_transfer: boolean().notNull().default(false),
    transfer_pair_id: varchar({ length: 36 }),
    is_excluded: boolean().notNull().default(false),
    has_splits: boolean().notNull().default(false),
    has_overlay: boolean().notNull().default(false),
    recurring_group: varchar({ length: 128 }),
    tags_json: json().$type<ReadonlyArray<string>>().notNull(),
    tags_text: text().notNull(),
    notes: text(),
    custom_fields_json: json().$type<Record<string, unknown>>(),
    provenance_json: json().$type<ProvenanceMap>().notNull(),
    applied_rule_ids_json: json().$type<ReadonlyArray<string>>().notNull(),
    updated_at: timestamp({ fsp: 3 }).notNull().defaultNow(),
  },
  (table) => [
    primaryKey({ columns: [table.workspace_id, table.id] }),
    index("idx_eff_tx_ws_date_id").on(table.workspace_id, table.date, table.id),
    index("idx_eff_tx_ws_acc_date").on(table.workspace_id, table.account_id, table.date),
    index("idx_eff_tx_ws_cat_date").on(table.workspace_id, table.category, table.date),
    index("idx_eff_tx_ws_cattop_date").on(table.workspace_id, table.category_top, table.date),
    index("idx_eff_tx_ws_merch_date").on(table.workspace_id, table.merchant_name, table.date),
    index("idx_eff_tx_ws_flags_date").on(table.workspace_id, table.is_excluded, table.is_transfer, table.date),
    index("idx_eff_tx_ws_amount").on(table.workspace_id, table.amount_cents),
    index("idx_eff_tx_ws_overlay_date").on(table.workspace_id, table.has_overlay, table.date),
  ],
)
