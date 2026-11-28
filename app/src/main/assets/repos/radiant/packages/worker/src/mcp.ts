import { Effect } from "effect"
import {
  acceptInvite,
  aggregateTransactions,
  applyOverlayByIdsOrFilter,
  balancesHistory,
  balancesSummary,
  clearTransactionSplits,
  createApiToken,
  createConnectHandoffLink,
  createInvite,
  createManualTransaction,
  createRule,
  createWorkspace,
  deleteRule,
  deleteWorkspace,
  executeWorkspaceSql,
  getAccount,
  getOverlayBatch,
  getPlaidItem,
  getRule,
  getTransactionDetail,
  getWorkspaceSqlSchema,
  listAccounts,
  listApiTokens,
  listInvites,
  listMembers,
  listOverlayBatches,
  listPlaidItems,
  listRules,
  listSyncRuns,
  listWorkspaces,
  previewRule,
  queryTransactions,
  reapplyAllRules,
  redoOverlayBatch,
  removeMember,
  removePlaidItem,
  reorderRules,
  resetTransactions,
  resolveWorkspaceAccess,
  revokeApiToken,
  revokeInvite,
  setAccountOverlay,
  setTransactionSplits,
  triggerPlaidSync,
  undoOverlayBatch,
  updateMemberRole,
  updateRule,
  updateWorkspace,
  verifyBearerToken,
  type Actor,
  type AggregateInput,
  type SplitLineInput,
  type SqlParam,
  type TransactionFilter,
  type TransactionQueryInput,
} from "@radiant/core"
import type { TxPatch, WorkspaceRole } from "@radiant/database/schema"
import { jsonResponse, type AppServices, type RouteContext } from "./env"

const SERVER_INSTRUCTIONS = [
  "Radiant syncs Plaid bank accounts and transactions into PlanetScale MySQL with non-destructive overlays, declarative rules, instant non-LIFO undo, structured aggregations, and read-only SQL.",
  "Sign convention: effective transactions use standard accounting sign (negative = outflow/spending, positive = inflow/income). Amounts are integer minor units (cents); decimal 'amount' = amount_cents / 100.0.",
  "Raw Plaid tables are never mutated. Every edit, bulk reclassification, split, manual entry, or rule change creates an overlay_batch that can be undone out of order with overlay_undo.",
  "Before creating a rule, call rule_preview to inspect matching transactions and before/after diffs.",
  "For complex analytics (window functions, CTEs, cohorts, rolling averages), call sql_schema first, then sql_query over the workspace-scoped views (transactions, transactions_unsplit, splits, raw_transactions, accounts, balance_snapshots, rules, overlay_batches).",
  "To connect or re-authenticate a bank account, call plaid_create_connect_link and share the returned connect_url with the user.",
].join(" ")

interface ToolDef {
  readonly name: string
  readonly description: string
  readonly inputSchema: Record<string, unknown>
}

const WS_PROP = {
  workspace_id: {
    type: "string",
    description: "Workspace ID or slug. Optional if you only belong to one workspace.",
  },
}

const TX_FILTER_PROPS = {
  date_from: { type: "string", description: "Start date inclusive (YYYY-MM-DD)" },
  date_to: { type: "string", description: "End date inclusive (YYYY-MM-DD)" },
  account_ids: { type: "array", items: { type: "string" } },
  institution_ids: { type: "array", items: { type: "string" } },
  categories: { type: "array", items: { type: "string" }, description: "Exact or prefix category matches (e.g. 'Food' matches 'Food > Coffee')" },
  exclude_categories: { type: "array", items: { type: "string" } },
  merchants: { type: "array", items: { type: "string" } },
  search: { type: "string", description: "Case-insensitive search across merchant, description, raw_name, notes, and tags" },
  amount_min_cents: { type: "integer", description: "Minimum signed amount_cents (- outflow / + inflow)" },
  amount_max_cents: { type: "integer", description: "Maximum signed amount_cents (- outflow / + inflow)" },
  direction: { type: "string", enum: ["inflow", "outflow", "all"] },
  tags_any: { type: "array", items: { type: "string" } },
  tags_all: { type: "array", items: { type: "string" } },
  tags_none: { type: "array", items: { type: "string" } },
  pending: { oneOf: [{ type: "boolean" }, { type: "string", enum: ["all"] }] },
  include_transfers: { type: "boolean" },
  include_excluded: { type: "boolean" },
  include_inactive_accounts: { type: "boolean", description: "Include transactions from deactivated accounts (default false)" },
  has_overlay: { type: "boolean" },
  rule_id: { type: "string" },
  batch_id: { type: "string" },
  expand_splits: { type: "boolean" },
}

export const MCP_TOOLS: ReadonlyArray<ToolDef> = [
  // Workspaces & Members
  { name: "workspace_list", description: "List workspaces you belong to.", inputSchema: { type: "object", properties: {} } },
  { name: "workspace_get", description: "Get details for a workspace.", inputSchema: { type: "object", properties: { ...WS_PROP } } },
  {
    name: "workspace_create",
    description: "Create a new workspace.",
    inputSchema: {
      type: "object",
      required: ["name"],
      properties: {
        name: { type: "string" },
        slug: { type: "string" },
        currency: { type: "string", description: "3-letter ISO code, default USD" },
      },
    },
  },
  {
    name: "workspace_update",
    description: "Rename a workspace or change its default currency.",
    inputSchema: {
      type: "object",
      properties: { ...WS_PROP, name: { type: "string" }, currency: { type: "string" } },
    },
  },
  { name: "workspace_delete", description: "Soft-delete a workspace (owner only).", inputSchema: { type: "object", properties: { ...WS_PROP } } },
  { name: "workspace_member_list", description: "List members of a workspace.", inputSchema: { type: "object", properties: { ...WS_PROP } } },
  {
    name: "workspace_member_update_role",
    description: "Change a workspace member's role (owner/admin/member/viewer).",
    inputSchema: {
      type: "object",
      required: ["user_id", "role"],
      properties: {
        ...WS_PROP,
        user_id: { type: "string" },
        role: { type: "string", enum: ["owner", "admin", "member", "viewer"] },
      },
    },
  },
  {
    name: "workspace_member_remove",
    description: "Remove a member from a workspace.",
    inputSchema: { type: "object", required: ["user_id"], properties: { ...WS_PROP, user_id: { type: "string" } } },
  },
  {
    name: "workspace_invite_create",
    description: "Invite someone by email to a workspace and return a shareable invite URL.",
    inputSchema: {
      type: "object",
      required: ["email"],
      properties: {
        ...WS_PROP,
        email: { type: "string" },
        role: { type: "string", enum: ["owner", "admin", "member", "viewer"] },
        expires_in_days: { type: "integer" },
      },
    },
  },
  { name: "workspace_invite_list", description: "List workspace invites.", inputSchema: { type: "object", properties: { ...WS_PROP } } },
  {
    name: "workspace_invite_revoke",
    description: "Revoke a pending workspace invite.",
    inputSchema: { type: "object", required: ["invite_id"], properties: { ...WS_PROP, invite_id: { type: "string" } } },
  },
  {
    name: "workspace_invite_accept",
    description: "Accept a workspace invite using its token.",
    inputSchema: { type: "object", required: ["invite_token"], properties: { invite_token: { type: "string" } } },
  },
  {
    name: "workspace_token_create",
    description: "Create a workspace-scoped API token (secret shown once).",
    inputSchema: {
      type: "object",
      required: ["name"],
      properties: {
        ...WS_PROP,
        name: { type: "string" },
        role: { type: "string", enum: ["owner", "admin", "member", "viewer"] },
        expires_in_days: { type: "integer" },
      },
    },
  },
  { name: "workspace_token_list", description: "List API tokens for a workspace.", inputSchema: { type: "object", properties: { ...WS_PROP } } },
  {
    name: "workspace_token_revoke",
    description: "Revoke a workspace API token.",
    inputSchema: { type: "object", required: ["token_id"], properties: { ...WS_PROP, token_id: { type: "string" } } },
  },

  // Plaid & Sync
  {
    name: "plaid_create_connect_link",
    description: "Generate a short-lived browser URL for the user to connect a new bank account via Plaid Link or reconnect an expired item (mode='update').",
    inputSchema: {
      type: "object",
      properties: {
        ...WS_PROP,
        mode: { type: "string", enum: ["new", "update"] },
        item_id: { type: "string", description: "Required when mode='update'" },
      },
    },
  },
  { name: "plaid_item_list", description: "List connected Plaid institutions and their sync status.", inputSchema: { type: "object", properties: { ...WS_PROP } } },
  { name: "plaid_item_get", description: "Get status and sync cursor details for one Plaid item.", inputSchema: { type: "object", required: ["item_id"], properties: { ...WS_PROP, item_id: { type: "string" } } } },
  { name: "plaid_item_remove", description: "Disconnect a Plaid item and revoke its access token.", inputSchema: { type: "object", required: ["item_id"], properties: { ...WS_PROP, item_id: { type: "string" } } } },
  {
    name: "plaid_sync",
    description: "Trigger an on-demand Plaid sync for one item or all active items in the workspace.",
    inputSchema: {
      type: "object",
      properties: { ...WS_PROP, item_id: { type: "string" }, force_refresh: { type: "boolean" } },
    },
  },
  {
    name: "plaid_sync_runs",
    description: "List recent Plaid sync runs with added/modified/removed counts and errors.",
    inputSchema: { type: "object", properties: { ...WS_PROP, item_id: { type: "string" }, limit: { type: "integer" } } },
  },

  // Accounts & Balances
  {
    name: "account_list",
    description: "List active accounts with current balances and overlays (pass include_inactive: true to include deactivated accounts).",
    inputSchema: { type: "object", properties: { ...WS_PROP, include_inactive: { type: "boolean" }, include_hidden: { type: "boolean" } } },
  },
  { name: "account_get", description: "Get one account by ID.", inputSchema: { type: "object", required: ["account_id"], properties: { ...WS_PROP, account_id: { type: "string" } } } },
  {
    name: "account_overlay_set",
    description: "Apply an undoable overlay to an account (toggle is_active to include/omit from queries while still syncing, nickname, group, owner_label, exclude from net worth, notes).",
    inputSchema: {
      type: "object",
      required: ["account_id"],
      properties: {
        ...WS_PROP,
        account_id: { type: "string" },
        is_active: { type: ["boolean", "null"], description: "Set false to omit this account and its transactions from queries, aggregates, balances, and SQL views while continuing to sync it." },
        nickname: { type: ["string", "null"] },
        account_group: { type: ["string", "null"] },
        owner_label: { type: ["string", "null"] },
        is_hidden: { type: ["boolean", "null"] },
        is_excluded_from_net_worth: { type: ["boolean", "null"] },
        notes: { type: ["string", "null"] },
        reason: { type: "string" },
      },
    },
  },
  { name: "balances_summary", description: "Get current assets, liabilities, and net worth grouped by currency and account type.", inputSchema: { type: "object", properties: { ...WS_PROP } } },
  {
    name: "balances_history",
    description: "Get historical net worth and per-account balance time series from balance snapshots.",
    inputSchema: {
      type: "object",
      properties: {
        ...WS_PROP,
        date_from: { type: "string" },
        date_to: { type: "string" },
        account_ids: { type: "array", items: { type: "string" } },
        bucket: { type: "string", enum: ["day", "week", "month"] },
      },
    },
  },

  // Query, Aggregation & SQL
  {
    name: "transactions_query",
    description: "Filter, search, sort, and cursor-paginate effective transactions.",
    inputSchema: {
      type: "object",
      properties: {
        ...WS_PROP,
        ...TX_FILTER_PROPS,
        sort_by: { type: "string", enum: ["date", "amount_cents", "merchant_name", "category"] },
        sort_dir: { type: "string", enum: ["asc", "desc"] },
        cursor: { type: "string" },
        limit: { type: "integer" },
        include_raw: { type: "boolean" },
        include_provenance: { type: "boolean" },
      },
    },
  },
  {
    name: "transactions_get",
    description: "Get full detail for a single transaction: effective state, raw Plaid record, splits, provenance, and overlay history.",
    inputSchema: { type: "object", required: ["tx_id"], properties: { ...WS_PROP, tx_id: { type: "string" } } },
  },
  {
    name: "transactions_aggregate",
    description: "Run split-aware multi-dimension grouping and aggregations (sum, count, avg, min, max, inflow, outflow, % of total, previous-period comparison).",
    inputSchema: {
      type: "object",
      properties: {
        ...WS_PROP,
        ...TX_FILTER_PROPS,
        group_by: {
          type: "array",
          maxItems: 3,
          items: {
            type: "string",
            enum: [
              "day", "week", "month", "quarter", "year",
              "category", "category_top", "merchant_name",
              "account_id", "institution_id", "tag",
              "payment_channel", "pending", "currency",
            ],
          },
        },
        order_by: { type: "string", enum: ["sum_cents", "abs_sum_cents", "count", "outflow_cents", "inflow_cents", "group"] },
        order_dir: { type: "string", enum: ["asc", "desc"] },
        limit: { type: "integer" },
        compare_previous_period: { type: "boolean" },
      },
    },
  },
  {
    name: "sql_schema",
    description: "Inspect the read-only MySQL views, columns, sign convention, and example queries available to sql_query.",
    inputSchema: { type: "object", properties: { ...WS_PROP } },
  },
  {
    name: "sql_query",
    description: "Execute a read-only MySQL SELECT / WITH query against the workspace's isolated analytical views (call sql_schema first).",
    inputSchema: {
      type: "object",
      required: ["sql"],
      properties: {
        ...WS_PROP,
        sql: { type: "string" },
        params: { type: "array", items: { type: ["string", "number", "boolean", "null"] } },
        limit: { type: "integer", description: "Row cap (default 1000, max 10000)" },
      },
    },
  },

  // Overlays, Splits & Manual Transactions
  {
    name: "transaction_overlay_set",
    description: "Apply a non-destructive, undoable overlay patch to one or more transactions (by tx_ids or filter; supports dry_run).",
    inputSchema: {
      type: "object",
      required: ["patch"],
      properties: {
        ...WS_PROP,
        tx_ids: { type: "array", items: { type: "string" } },
        filter: { type: "object", properties: TX_FILTER_PROPS },
        patch: {
          type: "object",
          properties: {
            category: { type: ["string", "null"] },
            merchant_name: { type: ["string", "null"] },
            description: { type: ["string", "null"] },
            date: { type: ["string", "null"] },
            amount_cents: { type: ["integer", "null"] },
            tags_set: { type: ["array", "null"], items: { type: "string" } },
            tags_add: { type: "array", items: { type: "string" } },
            tags_remove: { type: "array", items: { type: "string" } },
            notes: { type: ["string", "null"] },
            is_transfer: { type: ["boolean", "null"] },
            transfer_pair_id: { type: ["string", "null"] },
            is_excluded: { type: ["boolean", "null"] },
            recurring_group: { type: ["string", "null"] },
            custom_fields: { type: ["object", "null"] },
          },
        },
        reason: { type: "string" },
        dry_run: { type: "boolean" },
      },
    },
  },
  {
    name: "transaction_split_set",
    description: "Split a transaction into 2+ lines whose amount_cents sum to the parent transaction's amount_cents (undoable).",
    inputSchema: {
      type: "object",
      required: ["tx_id", "splits"],
      properties: {
        ...WS_PROP,
        tx_id: { type: "string" },
        splits: {
          type: "array",
          minItems: 2,
          items: {
            type: "object",
            required: ["amount_cents"],
            properties: {
              amount_cents: { type: "integer" },
              category: { type: ["string", "null"] },
              merchant_name: { type: ["string", "null"] },
              description: { type: ["string", "null"] },
              tags: { type: "array", items: { type: "string" } },
              notes: { type: ["string", "null"] },
              is_excluded: { type: "boolean" },
            },
          },
        },
        reason: { type: "string" },
      },
    },
  },
  {
    name: "transaction_split_clear",
    description: "Clear active splits on a transaction (undoable).",
    inputSchema: { type: "object", required: ["tx_id"], properties: { ...WS_PROP, tx_id: { type: "string" }, reason: { type: "string" } } },
  },
  {
    name: "transaction_manual_create",
    description: "Create a manual (off-Plaid / cash / adjustment) transaction wrapped in an undoable batch.",
    inputSchema: {
      type: "object",
      required: ["date", "amount_cents", "description"],
      properties: {
        ...WS_PROP,
        date: { type: "string" },
        amount_cents: { type: "integer", description: "Standard sign: - outflow / + inflow" },
        description: { type: "string" },
        account_id: { type: ["string", "null"] },
        currency: { type: "string" },
        merchant_name: { type: ["string", "null"] },
        category: { type: ["string", "null"] },
        tags: { type: "array", items: { type: "string" } },
        notes: { type: ["string", "null"] },
        is_transfer: { type: "boolean" },
        is_excluded: { type: "boolean" },
        custom_fields: { type: ["object", "null"] },
        reason: { type: "string" },
      },
    },
  },
  {
    name: "transaction_reset",
    description: "Clear manual overlays and splits on specified transactions, reverting them to raw + rules (undoable).",
    inputSchema: {
      type: "object",
      required: ["tx_ids"],
      properties: { ...WS_PROP, tx_ids: { type: "array", items: { type: "string" } }, reason: { type: "string" } },
    },
  },

  // Rules Engine
  { name: "rule_list", description: "List declarative rules with priority and current match counts.", inputSchema: { type: "object", properties: { ...WS_PROP } } },
  { name: "rule_get", description: "Get one rule by ID.", inputSchema: { type: "object", required: ["rule_id"], properties: { ...WS_PROP, rule_id: { type: "string" } } } },
  {
    name: "rule_preview",
    description: "Dry-run a candidate rule match AST + actions against existing transactions and inspect before/after diffs.",
    inputSchema: {
      type: "object",
      required: ["match", "actions"],
      properties: {
        ...WS_PROP,
        match: { type: "object" },
        actions: { type: "object" },
        priority: { type: "integer" },
        stop_on_match: { type: "boolean" },
        sample_limit: { type: "integer" },
      },
    },
  },
  {
    name: "rule_create",
    description: "Create a declarative reclassification rule (applies automatically to future synced transactions and optionally retroactively).",
    inputSchema: {
      type: "object",
      required: ["name", "match", "actions"],
      properties: {
        ...WS_PROP,
        name: { type: "string" },
        description: { type: ["string", "null"] },
        priority: { type: "integer" },
        enabled: { type: "boolean" },
        stop_on_match: { type: "boolean" },
        match: { type: "object" },
        actions: { type: "object" },
        apply_retroactively: { type: "boolean" },
        reason: { type: "string" },
      },
    },
  },
  {
    name: "rule_update",
    description: "Update a rule and efficiently rematerialize affected transactions (undoable).",
    inputSchema: {
      type: "object",
      required: ["rule_id"],
      properties: {
        ...WS_PROP,
        rule_id: { type: "string" },
        name: { type: "string" },
        description: { type: ["string", "null"] },
        priority: { type: "integer" },
        enabled: { type: "boolean" },
        stop_on_match: { type: "boolean" },
        match: { type: "object" },
        actions: { type: "object" },
        reason: { type: "string" },
      },
    },
  },
  {
    name: "rule_reorder",
    description: "Set rule execution priority order by passing rule IDs in ascending priority order (undoable).",
    inputSchema: {
      type: "object",
      required: ["rule_ids"],
      properties: { ...WS_PROP, rule_ids: { type: "array", items: { type: "string" } }, reason: { type: "string" } },
    },
  },
  {
    name: "rule_delete",
    description: "Soft-delete a rule and rematerialize only the transactions it matched (undoable).",
    inputSchema: { type: "object", required: ["rule_id"], properties: { ...WS_PROP, rule_id: { type: "string" }, reason: { type: "string" } } },
  },
  { name: "rule_reapply_all", description: "Re-materialize all transactions in the workspace from raw + active rules + active overlays.", inputSchema: { type: "object", properties: { ...WS_PROP } } },

  // History & Undo
  {
    name: "overlay_batch_list",
    description: "List human & agent overlay/rule edit batches.",
    inputSchema: { type: "object", properties: { ...WS_PROP, limit: { type: "integer" }, include_reverted: { type: "boolean" } } },
  },
  { name: "overlay_batch_get", description: "Inspect payload and details of one overlay batch.", inputSchema: { type: "object", required: ["batch_id"], properties: { ...WS_PROP, batch_id: { type: "string" } } } },
  { name: "overlay_undo", description: "Undo any overlay/split/rule batch (works out-of-order / non-LIFO in O(affected rows)).", inputSchema: { type: "object", required: ["batch_id"], properties: { ...WS_PROP, batch_id: { type: "string" } } } },
  { name: "overlay_redo", description: "Re-apply a previously undone overlay/split/rule batch.", inputSchema: { type: "object", required: ["batch_id"], properties: { ...WS_PROP, batch_id: { type: "string" } } } },
]

const dispatchTool = (
  actor: Actor,
  origin: string,
  name: string,
  args: Record<string, unknown>,
): Effect.Effect<unknown, unknown, AppServices> =>
  Effect.gen(function* () {
    const wsIdArg = typeof args.workspace_id === "string" ? args.workspace_id : undefined
    const resolveWs = (minRole: WorkspaceRole = "viewer") =>
      resolveWorkspaceAccess(actor, wsIdArg, minRole).pipe(Effect.map((w) => w.id))

    switch (name) {
      case "workspace_list":
        return yield* listWorkspaces(actor)
      case "workspace_get":
        return yield* resolveWorkspaceAccess(actor, wsIdArg, "viewer")
      case "workspace_create":
        return yield* createWorkspace(actor, {
          name: String(args.name ?? ""),
          slug: typeof args.slug === "string" ? args.slug : undefined,
          currency: typeof args.currency === "string" ? args.currency : undefined,
        })
      case "workspace_update":
        return yield* updateWorkspace(actor, yield* resolveWs("admin"), {
          name: typeof args.name === "string" ? args.name : undefined,
          currency: typeof args.currency === "string" ? args.currency : undefined,
        })
      case "workspace_delete":
        return yield* deleteWorkspace(actor, yield* resolveWs("owner"))
      case "workspace_member_list":
        return yield* listMembers(actor, yield* resolveWs("viewer"))
      case "workspace_member_update_role":
        return yield* updateMemberRole(
          actor,
          yield* resolveWs("admin"),
          String(args.user_id ?? ""),
          args.role as WorkspaceRole,
        )
      case "workspace_member_remove":
        return yield* removeMember(actor, yield* resolveWs("viewer"), String(args.user_id ?? ""))
      case "workspace_invite_create":
        return yield* createInvite(
          actor,
          yield* resolveWs("admin"),
          {
            email: String(args.email ?? ""),
            role: args.role as WorkspaceRole | undefined,
            expiresInDays: typeof args.expires_in_days === "number" ? args.expires_in_days : undefined,
          },
          origin,
        )
      case "workspace_invite_list":
        return yield* listInvites(actor, yield* resolveWs("admin"))
      case "workspace_invite_revoke":
        return yield* revokeInvite(actor, yield* resolveWs("admin"), String(args.invite_id ?? ""))
      case "workspace_invite_accept":
        return yield* acceptInvite(actor, String(args.invite_token ?? ""))
      case "workspace_token_create":
        return yield* createApiToken(actor, yield* resolveWs("admin"), {
          name: String(args.name ?? ""),
          role: args.role as WorkspaceRole | undefined,
          expiresInDays: typeof args.expires_in_days === "number" ? args.expires_in_days : undefined,
        })
      case "workspace_token_list":
        return yield* listApiTokens(actor, yield* resolveWs("admin"))
      case "workspace_token_revoke":
        return yield* revokeApiToken(actor, yield* resolveWs("admin"), String(args.token_id ?? ""))

      case "plaid_create_connect_link":
        return yield* createConnectHandoffLink(
          actor,
          yield* resolveWs("admin"),
          {
            mode: args.mode === "update" ? "update" : "new",
            item_id: typeof args.item_id === "string" ? args.item_id : undefined,
          },
          origin,
        )
      case "plaid_item_list":
        return yield* listPlaidItems(actor, yield* resolveWs("viewer"))
      case "plaid_item_get":
        return yield* getPlaidItem(actor, yield* resolveWs("viewer"), String(args.item_id ?? ""))
      case "plaid_item_remove":
        return yield* removePlaidItem(actor, yield* resolveWs("admin"), String(args.item_id ?? ""))
      case "plaid_sync":
        return yield* triggerPlaidSync(actor, yield* resolveWs("member"), {
          item_id: typeof args.item_id === "string" ? args.item_id : undefined,
          force_refresh: Boolean(args.force_refresh),
        })
      case "plaid_sync_runs":
        return yield* listSyncRuns(actor, yield* resolveWs("viewer"), {
          item_id: typeof args.item_id === "string" ? args.item_id : undefined,
          limit: typeof args.limit === "number" ? args.limit : undefined,
        })

      case "account_list":
        return yield* listAccounts(actor, yield* resolveWs("viewer"), {
          include_inactive: Boolean(args.include_inactive || args.include_hidden),
        })
      case "account_get":
        return yield* getAccount(actor, yield* resolveWs("viewer"), String(args.account_id ?? ""))
      case "account_overlay_set":
        return yield* setAccountOverlay(actor, yield* resolveWs("member"), {
          account_id: String(args.account_id ?? ""),
          is_active: args.is_active as boolean | null | undefined,
          nickname: args.nickname as string | null | undefined,
          account_group: args.account_group as string | null | undefined,
          owner_label: args.owner_label as string | null | undefined,
          is_hidden: args.is_hidden as boolean | null | undefined,
          is_excluded_from_net_worth: args.is_excluded_from_net_worth as boolean | null | undefined,
          notes: args.notes as string | null | undefined,
          reason: typeof args.reason === "string" ? args.reason : undefined,
        })
      case "balances_summary":
        return yield* balancesSummary(actor, yield* resolveWs("viewer"))
      case "balances_history":
        return yield* balancesHistory(actor, yield* resolveWs("viewer"), {
          date_from: typeof args.date_from === "string" ? args.date_from : undefined,
          date_to: typeof args.date_to === "string" ? args.date_to : undefined,
          account_ids: Array.isArray(args.account_ids) ? (args.account_ids as ReadonlyArray<string>) : undefined,
          bucket: args.bucket as "day" | "week" | "month" | undefined,
        })

      case "transactions_query":
        return yield* queryTransactions(actor, yield* resolveWs("viewer"), args as TransactionQueryInput)
      case "transactions_get":
        return yield* getTransactionDetail(actor, yield* resolveWs("viewer"), String(args.tx_id ?? ""))
      case "transactions_aggregate":
        return yield* aggregateTransactions(actor, yield* resolveWs("viewer"), args as AggregateInput)
      case "sql_schema":
        return yield* getWorkspaceSqlSchema(actor, yield* resolveWs("viewer"))
      case "sql_query":
        return yield* executeWorkspaceSql(actor, yield* resolveWs("viewer"), {
          sql: String(args.sql ?? ""),
          params: Array.isArray(args.params) ? (args.params as ReadonlyArray<SqlParam>) : undefined,
          limit: typeof args.limit === "number" ? args.limit : undefined,
        })

      case "transaction_overlay_set":
        return yield* applyOverlayByIdsOrFilter(actor, yield* resolveWs("member"), {
          tx_ids: Array.isArray(args.tx_ids) ? (args.tx_ids as ReadonlyArray<string>) : undefined,
          filter: args.filter as TransactionFilter | undefined,
          patch: (args.patch ?? {}) as TxPatch,
          reason: typeof args.reason === "string" ? args.reason : undefined,
          dry_run: Boolean(args.dry_run),
        })
      case "transaction_split_set":
        return yield* setTransactionSplits(actor, yield* resolveWs("member"), {
          tx_id: String(args.tx_id ?? ""),
          splits: Array.isArray(args.splits) ? (args.splits as ReadonlyArray<SplitLineInput>) : [],
          reason: typeof args.reason === "string" ? args.reason : undefined,
        })
      case "transaction_split_clear":
        return yield* clearTransactionSplits(
          actor,
          yield* resolveWs("member"),
          String(args.tx_id ?? ""),
          typeof args.reason === "string" ? args.reason : undefined,
        )
      case "transaction_manual_create":
        return yield* createManualTransaction(actor, yield* resolveWs("member"), {
          date: String(args.date ?? ""),
          amount_cents: Number(args.amount_cents ?? 0),
          description: String(args.description ?? ""),
          account_id: args.account_id as string | null | undefined,
          currency: typeof args.currency === "string" ? args.currency : undefined,
          merchant_name: args.merchant_name as string | null | undefined,
          category: args.category as string | null | undefined,
          tags: Array.isArray(args.tags) ? (args.tags as ReadonlyArray<string>) : undefined,
          notes: args.notes as string | null | undefined,
          is_transfer: typeof args.is_transfer === "boolean" ? args.is_transfer : undefined,
          is_excluded: typeof args.is_excluded === "boolean" ? args.is_excluded : undefined,
          custom_fields: args.custom_fields as Record<string, unknown> | null | undefined,
          reason: typeof args.reason === "string" ? args.reason : undefined,
        })
      case "transaction_reset":
        return yield* resetTransactions(
          actor,
          yield* resolveWs("member"),
          Array.isArray(args.tx_ids) ? (args.tx_ids as ReadonlyArray<string>) : [],
          typeof args.reason === "string" ? args.reason : undefined,
        )

      case "rule_list":
        return yield* listRules(actor, yield* resolveWs("viewer"))
      case "rule_get":
        return yield* getRule(actor, yield* resolveWs("viewer"), String(args.rule_id ?? ""))
      case "rule_preview":
        return yield* previewRule(actor, yield* resolveWs("viewer"), {
          match: args.match,
          actions: args.actions,
          priority: typeof args.priority === "number" ? args.priority : undefined,
          stop_on_match: typeof args.stop_on_match === "boolean" ? args.stop_on_match : undefined,
          sample_limit: typeof args.sample_limit === "number" ? args.sample_limit : undefined,
        })
      case "rule_create":
        return yield* createRule(actor, yield* resolveWs("member"), {
          name: String(args.name ?? ""),
          description: args.description as string | null | undefined,
          priority: typeof args.priority === "number" ? args.priority : undefined,
          enabled: typeof args.enabled === "boolean" ? args.enabled : undefined,
          stop_on_match: typeof args.stop_on_match === "boolean" ? args.stop_on_match : undefined,
          match: args.match,
          actions: args.actions,
          apply_retroactively: typeof args.apply_retroactively === "boolean" ? args.apply_retroactively : undefined,
          reason: typeof args.reason === "string" ? args.reason : undefined,
        })
      case "rule_update":
        return yield* updateRule(actor, yield* resolveWs("member"), String(args.rule_id ?? ""), {
          name: typeof args.name === "string" ? args.name : undefined,
          description: args.description as string | null | undefined,
          priority: typeof args.priority === "number" ? args.priority : undefined,
          enabled: typeof args.enabled === "boolean" ? args.enabled : undefined,
          stop_on_match: typeof args.stop_on_match === "boolean" ? args.stop_on_match : undefined,
          match: args.match,
          actions: args.actions,
          reason: typeof args.reason === "string" ? args.reason : undefined,
        })
      case "rule_reorder":
        return yield* reorderRules(
          actor,
          yield* resolveWs("member"),
          Array.isArray(args.rule_ids) ? (args.rule_ids as ReadonlyArray<string>) : [],
          typeof args.reason === "string" ? args.reason : undefined,
        )
      case "rule_delete":
        return yield* deleteRule(
          actor,
          yield* resolveWs("member"),
          String(args.rule_id ?? ""),
          typeof args.reason === "string" ? args.reason : undefined,
        )
      case "rule_reapply_all":
        return yield* reapplyAllRules(actor, yield* resolveWs("admin"))

      case "overlay_batch_list":
        return yield* listOverlayBatches(actor, yield* resolveWs("viewer"), {
          limit: typeof args.limit === "number" ? args.limit : undefined,
          include_reverted: typeof args.include_reverted === "boolean" ? args.include_reverted : undefined,
        })
      case "overlay_batch_get":
        return yield* getOverlayBatch(actor, yield* resolveWs("viewer"), String(args.batch_id ?? ""))
      case "overlay_undo":
        return yield* undoOverlayBatch(actor, yield* resolveWs("member"), String(args.batch_id ?? ""))
      case "overlay_redo":
        return yield* redoOverlayBatch(actor, yield* resolveWs("member"), String(args.batch_id ?? ""))

      default:
        return yield* Effect.fail({ _tag: "NotFoundError", message: `Unknown tool: ${name}` })
    }
  })

const formatToolError = (err: unknown): string => {
  if (err && typeof err === "object") {
    const rec = err as Record<string, unknown>
    const tag = typeof rec._tag === "string" ? rec._tag : "Error"
    const msg = typeof rec.message === "string" ? rec.message : JSON.stringify(rec)
    return `${tag}: ${msg}`
  }
  return String(err)
}

export const handleMcpRequest = (
  request: Request,
  route: RouteContext,
): Effect.Effect<Response, unknown, AppServices> =>
  Effect.gen(function* () {
    if (request.method !== "POST") {
      return new Response("Method Not Allowed", { status: 405, headers: { allow: "POST" } })
    }

    const authHeader = request.headers.get("authorization") ?? ""
    const bearer = authHeader.startsWith("Bearer ") ? authHeader.slice(7).trim() : ""
    const actor = bearer ? yield* verifyBearerToken(bearer) : null

    if (!actor) {
      return jsonResponse(
        { error: "unauthorized", error_description: "Valid Bearer token required" },
        401,
        {
          "www-authenticate": `Bearer resource_metadata="${route.origin}/.well-known/oauth-protected-resource${route.basePath}/mcp"`,
        },
      )
    }

    const rpc = yield* Effect.tryPromise({
      try: () => request.json() as Promise<{
        jsonrpc?: string
        id?: string | number | null
        method?: string
        params?: Record<string, unknown>
      }>,
      catch: () => ({ jsonrpc: "2.0", id: null, method: "" }),
    })

    const id = rpc.id ?? null

    if (rpc.method === "notifications/initialized") {
      return new Response(null, { status: 202 })
    }

    if (rpc.method === "ping") {
      return jsonResponse({ jsonrpc: "2.0", id, result: {} })
    }

    if (rpc.method === "initialize") {
      const requested = typeof rpc.params?.protocolVersion === "string" ? rpc.params.protocolVersion : "2025-11-25"
      const supported = ["2025-11-25", "2025-06-18", "2025-03-26"]
      const protocolVersion = supported.includes(requested) ? requested : "2025-11-25"
      return jsonResponse({
        jsonrpc: "2.0",
        id,
        result: {
          protocolVersion,
          capabilities: { tools: {} },
          serverInfo: { name: "radiant", version: "0.1.0" },
          instructions: SERVER_INSTRUCTIONS,
        },
      })
    }

    if (rpc.method === "tools/list") {
      return jsonResponse({
        jsonrpc: "2.0",
        id,
        result: { tools: MCP_TOOLS },
      })
    }

    if (rpc.method === "tools/call") {
      const toolName = typeof rpc.params?.name === "string" ? rpc.params.name : ""
      const toolArgs =
        rpc.params?.arguments && typeof rpc.params.arguments === "object"
          ? (rpc.params.arguments as Record<string, unknown>)
          : {}

      const outcome = yield* Effect.result(dispatchTool(actor, route.baseUrl, toolName, toolArgs))
      if (outcome._tag === "Failure") {
        return jsonResponse({
          jsonrpc: "2.0",
          id,
          result: {
            isError: true,
            content: [{ type: "text", text: formatToolError(outcome.failure) }],
          },
        })
      }

      return jsonResponse({
        jsonrpc: "2.0",
        id,
        result: {
          content: [{ type: "text", text: JSON.stringify(outcome.success, null, 2) }],
        },
      })
    }

    return jsonResponse({
      jsonrpc: "2.0",
      id,
      error: { code: -32601, message: `Method not found: ${rpc.method ?? ""}` },
    })
  })
