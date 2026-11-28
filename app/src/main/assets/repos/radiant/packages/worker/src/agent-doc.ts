// Content negotiation and agent-first Markdown onboarding guide for Radiant.

export const MARKDOWN_CONTENT_TYPE = "text/markdown; charset=utf-8"

export const prefersMarkdown = (accept: string | null): boolean => {
  if (!accept || accept.trim() === "") return true
  let markdown = 0
  let html = 0
  let plain = 0
  let hasHtml = false

  for (const part of accept.split(",")) {
    const [rawType, ...params] = part.trim().toLowerCase().split(";")
    const type = rawType?.trim() ?? ""
    const qParam = params.map((p) => p.trim()).find((p) => p.startsWith("q="))
    const q = qParam ? Number(qParam.slice(2)) : 1
    if (!Number.isFinite(q) || q <= 0) continue

    if (type === "text/markdown" || type === "text/x-markdown") {
      markdown = Math.max(markdown, q)
    } else if (type === "text/html" || type === "application/xhtml+xml") {
      html = Math.max(html, q)
      hasHtml = true
    } else if (type === "text/plain") {
      plain = Math.max(plain, q)
    }
  }

  if (markdown > 0 && markdown >= html) return true
  if (plain > 0 && !hasHtml) return true
  if (!hasHtml) return true
  return false
}

export const markdownResponse = (markdown: string, status = 200): Response =>
  new Response(markdown, {
    status,
    headers: {
      "content-type": MARKDOWN_CONTENT_TYPE,
      vary: "Accept",
      "cache-control": "public, max-age=60",
    },
  })

const TEMPLATE = "# Radiant\n\nAgent-native financial data hub: connect bank accounts through Plaid, sync lossless raw data into PlanetScale MySQL, apply non-destructive overlays and reclassification rules with instant non-LIFO undo, and run structured aggregations or read-only SQL over MCP or HTTP.\n\n- **MCP endpoint (Streamable HTTP, OAuth 2.1):** `{{base}}/mcp`\n- **Web UI:** {{base}}\n- **REST API:** `{{base}}/api/v1/*`\n- **Markdown guide:** `{{base}}/index.md`\n\n---\n\n## Quickstart for Agents (Connect MCP First)\n\nIf a user gave you this URL and asked to set up or use Radiant, **connect the remote MCP server first** — OAuth 2.1 handles sign-in automatically and gives you all 40+ tools directly.\n\n### Step 1 — Add the Radiant MCP server\n\n**OpenCode** (`opencode.json`):\n```json\n{\n  \"mcp\": {\n    \"servers\": {\n      \"radiant\": {\n        \"type\": \"remote\",\n        \"url\": \"{{base}}/mcp\"\n      }\n    }\n  }\n}\n```\n\n**Claude Code:** `claude mcp add --transport http radiant {{base}}/mcp`\n\n**Cursor** (`.cursor/mcp.json`): `{\"mcpServers\": {\"radiant\": {\"url\": \"{{base}}/mcp\"}}}`\n\nThe first tool call triggers OAuth 2.1 sign-in with the user's Anomaly account (PKCE S256 + dynamic client registration), which automatically creates their user account and a default Personal workspace.\n\n### Step 2 — Set up their workspace and send a 1-click bank connect link\n\nOnce MCP is connected, do the setup for them:\n\n1. Call `workspace_list`. If they have none, call `workspace_create` (e.g. `{\"name\": \"Personal\", \"currency\": \"USD\"}`).\n2. To invite a partner, teammate, or accountant, call `workspace_invite_create` and share the returned `invite_url`.\n3. Call `plaid_create_connect_link` (`{\"workspace_id\": \"<ws>\", \"mode\": \"new\"}`) and send the user the returned `connect_url` (`{{base}}/connect/rdl1_…`). Opening that link **auto-launches Plaid Link immediately** and stays active for 15 minutes so they can connect multiple banks in one visit.\n4. For an expired bank connection (`status: \"needs_reauth\"`), call `plaid_create_connect_link` with `{\"mode\": \"update\", \"item_id\": \"<item_id>\"}`.\n5. After the user connects, inspect synced data with `plaid_item_list`, `account_list`, `balances_summary`, `transactions_query`, `transactions_aggregate`, or `sql_schema` + `sql_query`.\n\n### MCP Tool Overview\n\n- **Workspaces & invites:** `workspace_list`, `workspace_create`, `workspace_invite_create`, `workspace_member_list`, `workspace_token_create`\n- **Plaid & sync:** `plaid_create_connect_link`, `plaid_item_list`, `plaid_sync`, `plaid_sync_runs`\n- **Accounts & balances:** `account_list`, `account_overlay_set`, `balances_summary`, `balances_history`\n- **Query & SQL:** `transactions_query`, `transactions_get`, `transactions_aggregate`, `sql_schema`, `sql_query`\n- **Non-destructive overlays & splits:** `transaction_overlay_set` (by IDs or filter, supports `dry_run`), `transaction_split_set`, `transaction_manual_create`, `transaction_reset`\n- **Rules:** `rule_preview` (dry-run before/after diffs), `rule_create`, `rule_update`, `rule_reorder`, `rule_delete`\n- **Instant non-LIFO undo/redo:** `overlay_batch_list`, `overlay_undo`, `overlay_redo`\n\n> **Sign convention:** Effective transactions use standard accounting sign (`-` outflow / spending, `+` inflow / income) in integer minor units (`amount_cents`; `amount = amount_cents / 100.0`). Raw Plaid data (`raw_transactions`) is immutable. Every edit, split, or rule change creates an `overlay_batch` that can be undone out of order in O(affected rows).\n\n---\n\n## Fallback: HTTP API + Device Flow (if you cannot add an MCP server right now)\n\nIf your runtime cannot attach an MCP server directly, sign the user in via OAuth 2.0 Device Flow (RFC 8628) and call the REST API directly:\n\n```http\n# 1. Start device sign-in — show the user verification_uri_complete and user_code\nPOST {{base}}/api/v1/auth/device\nContent-Type: application/json\n{\"client_name\": \"<your agent name>\"}\n→ {\"device_code\": \"rdd1.…\", \"user_code\": \"BCDF-GHJK\", \"verification_uri_complete\": \"{{base}}/device?code=BCDF-GHJK\", \"interval\": 5}\n\n# 2. Poll every interval seconds until 200 (authorization_pending = keep waiting)\nPOST {{base}}/api/v1/auth/token\nContent-Type: application/json\n{\"grant_type\": \"urn:ietf:params:oauth:grant-type:device_code\", \"device_code\": \"rdd1.…\"}\n→ 200 {\"access_token\": \"rdm1.…\", \"refresh_token\": \"rdr1.…\", \"expires_in\": 3600}\n\n# 3. List or create a workspace\nGET  {{base}}/api/v1/workspaces                       (Authorization: Bearer <access_token>)\nPOST {{base}}/api/v1/workspaces                       {\"name\": \"Personal\", \"currency\": \"USD\"}\n\n# 4. Mint a 1-click bank connect deep link (auto-launches Plaid Link)\nPOST {{base}}/api/v1/workspaces/<workspace_id>/plaid/connect-link\n{\"mode\": \"new\"}\n→ {\"connect_url\": \"{{base}}/connect/rdl1_…\", \"expires_at\": \"…\"}\n```\n\nREST endpoints mirror MCP 1:1: `GET /accounts`, `GET /balances`, `POST /transactions/query`, `POST /transactions/aggregate`, `GET /sql/schema`, `POST /sql/query`, `POST /transactions/overlay`, `PUT /transactions/<tx_id>/splits`, `POST /rules/preview`, `POST /rules`, `POST /overlays/batches/<batch_id>/undo`.\n"

export const renderAgentMarkdown = (baseUrl: string): string =>
  TEMPLATE.replaceAll("{{base}}", baseUrl.replace(/\/+$/, ""))
