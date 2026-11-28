# Radiant — Architecture & Implementation Plan

Radiant is a minimal, agent-native financial data hub: an ultra-lightweight website where you sign in, create workspaces, invite collaborators, and connect bank accounts via Plaid—paired with lossless raw sync into PlanetScale MySQL, a non-destructive overlay and rules engine with efficient non-LIFO undo, a structured + read-only SQL query/aggregation layer, and a remote MCP server that controls everything.

---

## 1. Finalized Decisions

| Area | Decision |
| --- | --- |
| **Repository** | `anomalyco/radiant` (**public**), default branch `dev`, fast-forward `production`, `/.github/ @thdxr` CODEOWNERS |
| **Runtime & Hosting** | **Cloudflare Workers** (`cf` CLI / `cloudflare.config.ts`); dedicated domain TBD (all routes & URLs built from request origin) |
| **Database** | **PlanetScale MySQL** (`anomalyco/radiant`, AWS `us-east`), accessed via `@planetscale/database` HTTP driver + Drizzle MySQL (`DATABASE_URL` primary + `DATABASE_READ_URL` read-only role) |
| **Backend Stack** | **TypeScript + Effect (v4)** (`effect`, `effect/sql`, Effect `HttpRouter`, `Schema` boundary validation, typed errors, pure domain core with zero HTTP awareness) |
| **Authentication** | **`account.anoma.ly` OIDC** (open to all users) + Radiant's own MCP OAuth 2.1 authorization server (PKCE S256, RFC 7591 DCR, consent screen, rotating refresh tokens, optional device flow & workspace API tokens) |
| **Plaid Scope (v1)** | **Accounts + Balance Snapshots + Transactions (`/transactions/sync`)**; starts in Plaid Sandbox + deterministic mock mode until live keys are wired |
| **Amount Sign Convention** | Integer minor units (`amount_cents`). `raw_transactions.raw_amount_cents` keeps Plaid's native sign (`+` outflow / `-` inflow); `effective_transactions.amount_cents` normalizes to standard accounting sign (`-` outflow / `+` inflow) |
| **Web UI** | **Very simple & performant** — server-rendered HTML directly from the Worker with minimal vanilla JS only for Plaid Link & copy actions (no heavy SPA framework) |

---

## 2. System Architecture

```
Browser / MCP Client (OpenCode, etc.)
        │
        ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Cloudflare Worker (radiant-dev / radiant-production)               │
│  ├─ Minimal SSR HTML UI (/, /w/:slug/*, /connect/:tok, /invite/:tok)│
│  ├─ REST API (/api/v1/*)                                            │
│  ├─ Remote MCP Server (/mcp, Streamable HTTP, stateless)            │
│  ├─ OAuth 2.1 Auth Server (/oauth/*, /.well-known/*, /device)       │
│  ├─ Plaid Webhook Receiver (/webhooks/plaid, ES256 JWK verified)    │
│  └─ Sync Queue Consumer + Daily Cron (balance snapshots + sync)     │
└───────────────┬─────────────────────────────────────┬───────────────┘
                │ DATABASE_URL (primary)              │ DATABASE_READ_URL (reader)
                ▼                                     ▼
┌─────────────────────────────────────────────────────────────────────┐
│  PlanetScale MySQL (anomalyco/radiant — production & dev branches)  │
│  ├─ Identity & Access: users, sessions, oauth_*, api_tokens         │
│  ├─ Workspaces: workspaces, workspace_members, workspace_invites    │
│  ├─ Secrets (app-only, never SQL-exposed): plaid_credentials        │
│  │   (AES-256-GCM encrypted access_token), connect_tokens           │
│  ├─ Lossless Plaid Mirror: raw_items, raw_accounts,                 │
│  │   raw_balance_snapshots, raw_transactions, sync_runs             │
│  ├─ Overlay & Rules Engine: overlay_batches, tx_overlays,           │
│  │   tx_splits, account_overlays, manual_transactions,              │
│  │   rules, rule_applications                                       │
│  └─ Materialized Read Layer: effective_transactions (+ FULLTEXT)    │
└─────────────────────────────────────────────────────────────────────┘
```

### Effect Service & Layer Graph
Following Anomaly's Effect architecture (`opencode-console` pattern):
- **`Database` / `DatabasePlanetscale`:** Effect `SqlClient` over `@planetscale/database` HTTP transport with `DATABASE_URL` (read/write) and `DATABASE_READ_URL` (PlanetScale `reader` role for read-only analytical & agent SQL queries), plus single-retry on transient Cloudflare subrequest transport drops for idempotent reads.
- **`WorkspaceAccess`:** Single auth boundary resolving `(actor, workspace, role)` and verifying active workspace (`deleted_at IS NULL`) before any workspace-scoped service executes.
- **`PlaidClient`:** Typed Effect service wrapping Plaid REST API (`fetch`-based, zero Node-only SDK bloat) with live/sandbox and deterministic mock layers for tests.
- **`CryptoService`:** WebCrypto AES-256-GCM envelope encryption (key-versioned for rotation) for `plaid_credentials.access_token_enc` and SHA-256 token hashing.
- **`Materializer`:** Pure domain engine (`packages/core`) taking `(raw, activeRules, activeOverlays, activeSplits)` → deterministic `effective_transactions` + `provenance_json`.
- **`SqlGuard`:** Pure SQL AST parser & workspace-isolation rewriter (`packages/core`) guaranteeing safe, tenant-isolated read-only MySQL execution.

---

## 3. Identity, Workspaces & Access Control

### Human Sign-In & MCP OAuth 2.1
- **Upstream Identity (`account.anoma.ly` OIDC):** Radiant registers as one OIDC client (`radiant`) with PKCE S256 and ES256 ID token verification against `account.anoma.ly`'s JWKS (cached per isolate). Any valid Anomaly account can sign up (no team gate).
- **Browser Sessions:** `HttpOnly`, `Secure`, `SameSite=Lax` signed session cookie referencing a hashed session row in MySQL.
- **MCP OAuth 2.1 Server (hosted on Radiant Worker, matching `lichkey`):**
  - `/.well-known/oauth-protected-resource/mcp` (RFC 9728)
  - `/.well-known/oauth-authorization-server` (RFC 8414)
  - Dynamic Client Registration (`/oauth/register`, RFC 7591, public PKCE clients)
  - Authorization Code + PKCE S256 (`/oauth/authorize`, `/oauth/callback`, `/oauth/token`, `/oauth/revoke`) with an explicit anti-CSRF consent page
  - Access tokens (`rdm1.<grant>.<secret>`, 1h TTL) + rotating refresh tokens (`rdr1.`, 30d max lifetime, reuse revokes grant), stored as SHA-256 hashes
  - Device Authorization Grant (RFC 8628, `/api/v1/auth/device`, `/device`) for headless/CLI agent login
  - Optional workspace-scoped API tokens (`rdt1.`) for scripts

### Workspaces, Roles & Invites
- First sign-in creates a user record (and optionally a personal workspace, or lets the user/agent create workspaces on demand).
- Users can create and belong to multiple workspaces (e.g., *Personal*, *Household*, *Company*).
- **Roles:**
  - `owner`: full control, delete workspace, manage all members, connections, overlays, rules.
  - `admin`: connect/disconnect Plaid items, manage invites/members, edit overlays & rules.
  - `member`: edit overlays & rules, trigger sync, run queries & SQL.
  - `viewer`: read-only queries, balances, and SQL.
- **Invites:**
  - Managed via both web UI and MCP (`workspace_invite_create`, `list`, `revoke`, `accept`).
  - Creates a hashed single-use token with `email`, `role`, and TTL (default 7 days), returning a shareable URL (`https://<origin>/invite/<token>`).
  - Accepting verifies the signed-in user (and email match if enforced) and inserts into `workspace_members` atomically.

---

## 4. Plaid Integration & Perfect Sync

### Connecting & Re-authenticating Accounts
1. **Browser flow:** `POST /api/v1/workspaces/:ws/plaid/link-token` → Plaid Link modal in browser → `POST /api/v1/workspaces/:ws/plaid/exchange` stores AES-256-GCM encrypted `access_token` in `plaid_credentials`, creates `raw_items` & `raw_accounts`, snapshots balances, and triggers initial sync.
2. **Agent-initiated flow (MCP):** `plaid_create_connect_link(workspace_id, mode: "new" | "update", item_id?)` mints a short-lived single-use URL (`https://<origin>/connect/<token>`, 15 min TTL) that the user opens in their browser to complete Plaid Link or Update Mode.
3. **Update mode:** When Plaid sends `ITEM_LOGIN_REQUIRED` or `PENDING_EXPIRATION`, `raw_items.status` flips to `needs_reauth` and both UI and MCP can generate an Update Mode handoff link.

### Sync Pipeline & Edge Cases
- **Initial link:** Requests `transactions` with `days_requested: 730` (2 years), fetches institution metadata (`institutions/get_by_id`), fetches accounts + balances (`accounts/get`), records a `raw_balance_snapshots` entry, and runs the full `/transactions/sync` cursor loop.
- **Cursor safety & mutation retry:**
  - Loops `/transactions/sync` while `has_more === true`.
  - Stages all pages and advances `raw_items.sync_cursor` only once the batch commits.
  - On `TRANSACTIONS_SYNC_MUTATION_DURING_PAGINATION`, restarts cleanly from the last committed cursor.
- **Lossless raw storage:**
  - Stores full `raw_json` blob plus normalized columns (`plaid_transaction_id`, `account_id`, `raw_amount_cents`, `currency`, `date`, `authorized_date`, `name`, `merchant_name`, `pfc_primary`, `pfc_detailed`, `payment_channel`, `pending`, `pending_transaction_id`, `counterparties_json`, `location_json`).
  - Amounts are signed `BIGINT` minor units (cents) everywhere—no floating-point drift.
  - Sign convention: `raw_transactions.raw_amount_cents` keeps Plaid's native sign (`+` outflow), while `effective_transactions.amount_cents` flips to standard accounting sign (`-` outflow / `+` inflow).
- **Pending → Posted reconciliation:**
  - When a posted transaction arrives with `pending_transaction_id = P`:
    1. Marks pending row `P` with `superseded_by = posted_id` (removed from `effective_transactions` so it never double-counts).
    2. Automatically carries forward any active manual `tx_overlays` and `tx_splits` targeting `P` onto the posted transaction, recording the carry-forward in `overlay_batches` so edits made while pending are preserved.
- **Removals:** Plaid `removed` IDs set `raw_transactions.removed_at` (soft delete) and delete the corresponding `effective_transactions` row while keeping full history.
- **Re-link deduplication:** Matches re-linked accounts by `(workspace_id, institution_id, mask, type, subtype, official_name)` to avoid silently duplicating transaction history on item reconnection.
- **Historical balance snapshots:** Appended on every sync and via a daily Worker cron so agents can query net worth and account balances over time.
- **Webhooks & reliability:**
  - `POST /webhooks/plaid` verifies Plaid's `Plaid-Verification` ES256 JWT (against cached JWKs from `/webhook_verification_key/get`) and constant-time checks the SHA-256 hash of the raw request body.
  - Enqueues a message onto Cloudflare Queue `radiant-plaid-sync` (with retries + DLQ) and returns `200 OK` immediately.
  - Every sync logs a `sync_runs` row (`trigger`, `added`, `modified`, `removed`, `rules_applied`, `cursor_before`, `cursor_after`, `error`, timestamps).

---

## 5. Non-Destructive Overlay & Rules Engine

### Core Invariant
Only the Plaid sync pipeline writes to `raw_*` tables. Users, agents, and rules write exclusively to overlay/rule tables, which deterministically materialize into `effective_transactions`.

### Deterministic 3-Layer Precedence
```
Layer 0: Raw Plaid Record (normalized from raw_transactions; sign converted to - outflow / + inflow)
   ↓
Layer 1: Active Rules matching transaction (ascending priority, then created_at; optional stop_on_match)
   ↓
Layer 2: Active Manual Overlays on transaction (chronological seq order)
   ↓
Materialized Output: effective_transactions + provenance_json (per-field source)
```

### Overlay Capabilities
- **Transaction overlays:** `category` (freeform/hierarchical, e.g. `"Food > Coffee"`), `merchant_name`, `description`, `date` (accounting date override), `amount_cents` (correction override), `tags` (`add`, `remove`, or `set`), `notes`, `is_transfer`, `transfer_pair_id`, `is_excluded`, `recurring_group`, `custom_fields` (JSON key/value map).
- **Splits (`tx_splits`):** Split one transaction into N lines (`amount_cents`, `category`, `merchant_name`, `tags_json`, `notes`, `is_excluded`), validated so `sum(splits.amount_cents) === parent.amount_cents`.
- **Account overlays (`account_overlays`):** `nickname`, `account_group`, `owner_label`, `is_hidden`, `is_excluded_from_net_worth`, `notes`.
- **Manual transactions (`manual_transactions`):** Off-Plaid cash/adjustment entries materialized into `effective_transactions` with `source = 'manual'`, wrapped in an undoable `overlay_batch`.

### Declarative Rules Engine
- **Match AST (structured JSON, safe & inspectable):**
  ```json
  {
    "all": [
      { "field": "raw_name", "op": "icontains", "value": "UBER EATS" },
      { "field": "amount_cents", "op": "lt", "value": 0 }
    ]
  }
  ```
  - Combinators: `all`, `any`, `not`.
  - Operators: `eq`, `neq`, `in`, `not_in`, `contains`, `icontains`, `starts_with`, `ends_with`, `regex`, `gt`, `gte`, `lt`, `lte`, `between`, `is_null`.
  - Matchable fields: `account_id`, `account_type`, `account_subtype`, `institution_id`, `raw_name`, `raw_merchant_name`, `raw_category_primary`, `raw_category_detailed`, `payment_channel`, `currency`, `amount_cents`, `date`, `day_of_week`, `pending`, `counterparty_name`.
- **Actions:** `set_category`, `set_merchant_name`, `set_description`, `add_tags`, `remove_tags`, `set_is_transfer`, `set_is_excluded`, `set_notes`, `set_recurring_group`, `merge_custom_fields`.
- **Dry-Run Preview (`rule_preview`):** Evaluates candidate match + actions against current workspace transactions and returns exact match count + sample before/after diffs without writing.
- **Provenance (`provenance_json`):** Records which layer set each overridden field (`raw`, `rule:<id>`, `overlay:<batch_id>`).

### Efficient, Non-LIFO Undo Architecture
Every mutation (single edit, bulk filter edit, split, account overlay, manual entry, or rule create/update/reorder/delete) creates an **`overlay_batch`** row (`id` ULID, `kind`, `actor_type`, `actor_id`, `client_name`, `reason`, `before_snapshot_json`, `affected_count`, `created_at`, `reverted_at`).
- **`overlay_undo(batch_id)` runs in O(affected rows):**
  1. **Manual overlay / split batch:** Marks `overlay_batches.reverted_at = NOW()` and flips `active = 0` on `tx_overlays` / `tx_splits` for `batch_id`. Fetches only the affected `tx_id`s via `(workspace_id, batch_id)` index and re-materializes only those rows from `raw_transactions` + active rules + remaining active overlays in a single transaction.
  2. **Rule batch:** Restores the rule's `before_snapshot_json`, gathers `affected_tx_ids = previous_matches ∪ new_matches` via `rule_applications(workspace_id, rule_id, tx_id)`, updates `rule_applications`, and re-materializes only those rows.
  3. **Out-of-order (non-LIFO) safe:** Undoing batch #12 while batches #13 and #14 stay active recomputes only the overlapping transactions using the remaining active layers—zero cascading corruption, zero full-table rebuilds.
  4. **Redo (`overlay_redo(batch_id)`)** symmetrically reactivates the batch and re-materializes the same `tx_id` set.
  5. **Reset (`transaction_reset(tx_ids)`)** creates a new undoable batch that deactivates manual overlays on those transactions.

---

## 6. PlanetScale MySQL Schema Design (Drizzle)

Conventions (matching `opencode-console` & PlanetScale Vitess):
- Single Drizzle schema in `packages/database/src/schema.ts`, snake_case columns, expand-only migrations in `migrations/` (`__drizzle_migrations`).
- `foreign_keys_enabled: false` (PlanetScale standard); referential invariants enforced in Effect domain services.
- Typed ULID primary keys (`ws_`, `usr_`, `itm_`, `acc_`, `tx_`, `bat_`, `ovr_`, `spl_`, `rul_`, `syn_`).
- **Every workspace-scoped table leads its primary key and secondary indexes with `workspace_id`** for Vitess index locality and fast single-tenant range scans.

### Tables
| Group | Tables & Key Indexes |
| --- | --- |
| **Identity & OAuth** | `user`, `session`, `oauth_client`, `oauth_flow`, `oauth_code`, `oauth_grant`, `device_code`, `api_token` |
| **Workspaces** | `workspace`, `workspace_member (workspace_id, user_id)`, `workspace_invite (workspace_id, id)` |
| **Plaid Secrets** *(never SQL-exposed)* | `plaid_credential (workspace_id, item_id)` with `access_token_enc` + `key_version`, `connect_token` |
| **Raw Plaid Mirror** | `raw_item (workspace_id, item_id)`, `raw_account (workspace_id, id)`, `raw_balance_snapshot (workspace_id, account_id, captured_at)`, `raw_transaction (workspace_id, id)` + unique `(workspace_id, plaid_transaction_id)`, `sync_run (workspace_id, id)` |
| **Overlays & Rules** | `overlay_batch (workspace_id, id)`, `tx_overlay (workspace_id, id)` + idx `(workspace_id, tx_id, active, seq)` + idx `(workspace_id, batch_id)`, `tx_split (workspace_id, id)` + idx `(workspace_id, tx_id, active)` + idx `(workspace_id, batch_id)`, `account_overlay (workspace_id, account_id)`, `manual_transaction (workspace_id, id)`, `rule (workspace_id, id)` + idx `(workspace_id, enabled, priority)`, `rule_application (workspace_id, rule_id, tx_id)` + idx `(workspace_id, tx_id)` |
| **Materialized Effective** | `effective_transaction (workspace_id, id)` with indexes: `(workspace_id, date DESC, id DESC)`, `(workspace_id, account_id, date DESC)`, `(workspace_id, category, date DESC)`, `(workspace_id, merchant_name, date DESC)`, `(workspace_id, is_excluded, is_transfer, date DESC)`, `(workspace_id, amount_cents)`, plus `FULLTEXT (merchant_name, description, raw_name, notes, tags_text)` |

---

## 7. Query, Aggregation & Safe Agent SQL

### Tier 1: Structured Query & Aggregation API
1. **`transactions_query`:** Filters (`date_from/to`, `account_ids`, `account_types`, `institution_ids`, `categories` prefix-aware, `exclude_categories`, `merchants`, `search` via MySQL `FULLTEXT`, `amount_min/max_cents`, `direction`, `tags_any/all/none`, `pending`, `include_transfers`, `include_excluded`, `has_overlay`, `rule_id`, `batch_id`, `expand_splits`) + keyset cursor pagination (`cursor`, `limit`) + optional `include_raw` / `include_provenance`.
2. **`transactions_aggregate`:** Exact same filters (split-aware, excludes `is_excluded` & `is_transfer` by default). Groups by up to 3 dimensions (`day`, `week`, `month`, `quarter`, `year`, `category`, `category_top`, `merchant_name`, `account_id`, `institution_name`, `tag`, `payment_channel`, `pending`, `currency`) with `sum`, `count`, `avg`, `min`, `max`, `inflow_sum`, `outflow_sum`, `net_sum`, `pct_of_total`, `having`, `order_by`, `limit`, and `compare_previous_period`.
3. **`balances_summary` & `balances_history`:** Current assets/liabilities/net worth by account/type/currency and historical balance series from `raw_balance_snapshots`.

### Tier 2: Read-Only Standard SQL (`sql_query` + `sql_schema`)
Runs **MySQL 8.0 SQL** (CTEs, window functions, `JSON_EXTRACT`/`JSON_TABLE`, `DATE_FORMAT`, `WITH ROLLUP`, subqueries, joins) safely on shared PlanetScale MySQL using defense-in-depth:
1. **Read-only DB credential (`DATABASE_READ_URL`):** PlanetScale `reader` role enforces read-only (`SELECT`) at the MySQL engine level.
2. **Strict SQL AST Validator & Workspace Rewriter (`packages/core/src/sql/`):**
   - Parses incoming SQL into an AST; accepts **only** a single `SELECT` / `WITH ... SELECT` / `UNION` of `SELECT`s.
   - Rejects DML/DDL, multiple statements, `INTO OUTFILE`, `FOR UPDATE`, `LOCK IN SHARE MODE`, MySQL versioned comments (`/*! ... */`), user variables (`@x`), system schemas (`information_schema`, `mysql`, `performance_schema`, `sys`), and hazardous functions (`SLEEP`, `BENCHMARK`, `LOAD_FILE`, `GET_LOCK`).
   - **Table allowlist (8 logical analytical views):** `transactions` (effective, split-expanded), `transactions_unsplit`, `splits`, `raw_transactions`, `accounts`, `balance_snapshots`, `rules`, `overlay_batches`. Sensitive tables (`plaid_credential`, `oauth_*`, `session`, `user`, `api_token`) are completely unreachable.
   - **Automatic workspace rewriting:** Every non-CTE table reference in the AST (including inside subqueries, CTEs, JOINs, `IN`, `EXISTS`) is rewritten to a workspace-scoped derived table `(SELECT <explicit safe columns> FROM <backing_table> WHERE workspace_id = ?)` with `?` bound server-side from the verified `WorkspaceAccess` grant. Because every backing table leads its indexes with `workspace_id`, MySQL pushes the predicate straight into index scans.
3. **Resource guardrails:** Enforced row limit (default 1,000, max 10,000) + `/*+ MAX_EXECUTION_TIME(5000) */` query timeout hint + optional `explain: true`.
4. **`sql_schema` tool:** Returns exact column lists, types, amount sign convention (`-` outflow / `+` inflow), and ready-to-use MySQL query recipes so agents write accurate SQL on the first try.

---

## 8. MCP Server Surface (`/mcp`)

Stateless Streamable HTTP (`POST /mcp`), OAuth 2.1 authenticated. Workspace-scoped tools take `workspace_id` (defaulting automatically when the user belongs to a single workspace).

| Group | Tools |
| --- | --- |
| **Workspaces** | `workspace_list`, `workspace_get`, `workspace_create`, `workspace_update`, `workspace_delete` |
| **Members & Invites** | `workspace_member_list`, `workspace_member_update_role`, `workspace_member_remove`, `workspace_invite_create`, `workspace_invite_list`, `workspace_invite_revoke`, `workspace_invite_accept` |
| **Plaid & Sync** | `plaid_create_connect_link`, `plaid_item_list`, `plaid_item_get`, `plaid_item_remove`, `plaid_sync`, `plaid_sync_runs` |
| **Accounts & Balances** | `account_list`, `account_get`, `account_overlay_set`, `balances_summary`, `balances_history` |
| **Query & Analytics** | `transactions_query`, `transactions_get`, `transactions_aggregate`, `sql_schema`, `sql_query` |
| **Overlays & Splits** | `transaction_overlay_set` (single, ID list, or filter + `dry_run`), `transaction_split_set`, `transaction_split_clear`, `transaction_manual_create`, `transaction_reset` |
| **Rules** | `rule_list`, `rule_get`, `rule_preview`, `rule_create`, `rule_update`, `rule_reorder`, `rule_toggle`, `rule_delete`, `rule_reapply_all` |
| **History & Undo** | `overlay_batch_list`, `overlay_batch_get`, `overlay_undo`, `overlay_redo` |

---

## 9. Minimal, Performant Web UI

Server-rendered HTML straight from the Worker (single clean stylesheet, zero JS framework/hydration overhead, tiny inline script only for Plaid Link modal & copy buttons):
1. **Landing / Sign-in (`/`):** Sign in with Anomaly Account; redirects authenticated users straight to their workspace.
2. **Workspace Dashboard (`/w/:slug`):**
   - Workspace switcher + "New workspace" form.
   - **Connected Institutions:** Plaid Link "Connect Bank" button, item status badges, "Sync now", "Reconnect" (Update Mode), "Disconnect", and account list with current balances.
   - **MCP Setup Card:** Copyable endpoint URL + `opencode.json` snippet + personal/workspace API token generator.
   - **Members & Invites:** Current members, role selector, create/copy/revoke invite link.
   - **Recent Activity & Undo:** Last 25 overlay batches (human & agent) with one-click Undo / Redo.
3. **Handoff Pages:**
   - `/connect/:token` — launches Plaid Link (new or update mode) for MCP-generated connect links.
   - `/invite/:token` — accept workspace invite after sign-in.
   - `/oauth/authorize` & `/device` — OAuth consent and device-flow approval pages.

---

## 10. Repo Structure & Milestones

Repository: `anomalyco/radiant` (`~/dev/projects/anomalyco/radiant`, public), default branch `dev`, release branch `production` (fast-forward only), deployed via GitHub Actions + `anomalyco/secrets` OIDC to `anomaly-dev` and `anomaly-production`.

```
radiant/
├── cloudflare.config.ts        # Worker, Plaid Sync Queue, Daily Cron, env bindings
├── drizzle.config.ts           # PlanetScale MySQL Drizzle config
├── migrations/                 # Linear Drizzle MySQL migration history
├── packages/
│   ├── database/               # Drizzle MySQL schema (src/schema.ts) + migration runner
│   ├── core/                   # Pure Effect domain services (workspace, plaid sync,
│   │                           #   rules AST, materializer, overlay/undo, query builder,
│   │                           #   SQL AST guard/rewriter, crypto, OAuth/identity)
│   └── worker/                 # Cloudflare Worker entrypoint (Effect HttpRouter, /api/v1,
│                               #   /mcp, /oauth, /webhooks/plaid, minimal SSR HTML UI, Queue/Cron)
├── docs/
│   └── plan.md                 # This document
├── AGENTS.md
└── .github/
    ├── CODEOWNERS              # /.github/ @thdxr
    └── workflows/              # check.yml + deploy.yml
```

### Milestones & Proof of Done
1. **M1 — Repo, PlanetScale MySQL, Auth & Workspaces:** Scaffold `anomalyco/radiant`, create PlanetScale MySQL DB (`anomalyco/radiant`, `production` + `dev` branches), Drizzle schema + initial migration, `DatabasePlanetscale` Effect layer, `account.anoma.ly` OIDC + MCP OAuth 2.1 server, workspaces/members/invites services + HTTP + MCP tools + minimal SSR UI. *Proved by:* unit/integration tests + local sign-in, workspace & invite lifecycle, and MCP OAuth connect.
2. **M2 — Plaid Sync Engine:** Versioned AES-256-GCM credential storage, Plaid Link token/exchange + `/connect/:token` handoff page, full `/transactions/sync` cursor loop (mutation retry + pending→posted overlay carry-forward), balance snapshots, ES256 webhook verification + Queue consumer + daily cron, and Sandbox/mock sync tests. *Proved by:* end-to-end sync tests covering initial load, incremental adds/mods/removes, pending→posted settlement, and webhook signature verification.
3. **M3 — Overlay, Rules & Undo Engine:** Deterministic 3-layer materializer, JSON-AST rules engine + `rule_preview`, splits, account overlays, manual transactions, field provenance, and O(affected) non-LIFO `overlay_undo` / `overlay_redo`. *Proved by:* property/scenario tests covering out-of-order undo, rule edits/reorders, pending→posted carry-forward, and split sum invariants.
4. **M4 — Query, Aggregation & Safe Read-Only SQL:** `transactions_query` (FULLTEXT + keyset cursor), `transactions_aggregate` (multi-dimension `group_by` + period comparison), `balances_summary/history`, `SqlGuard` AST parser + workspace-isolation rewriter over `DATABASE_READ_URL`, and `sql_schema` / `sql_query` tools. *Proved by:* query/aggregate accuracy tests + adversarial SQL escape/mutation rejection test suite.
5. **M5 — Minimal Web UI Polish & CI/Deploy Wiring:** Complete SSR UI (connections, MCP setup card, members/invites, recent activity/undo), `check.yml` + `deploy.yml` following Abattoir standards, ready to wire domain & `anomalyco/secrets`.
