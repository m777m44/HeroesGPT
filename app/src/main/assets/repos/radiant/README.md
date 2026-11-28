# Radiant

Agent-native financial data hub on Cloudflare Workers, Effect v4, and PlanetScale MySQL.

- **Workspaces & invites:** create workspaces, invite collaborators with RBAC (`owner`, `admin`, `member`, `viewer`), all manageable via UI and MCP.
- **Lossless Plaid sync:** `/transactions/sync` cursor loop with mutation retry, daily + on-sync balance snapshots, ES256 webhook verification, and automatic carry-forward of manual overlays/splits when pending transactions settle into posted ones.
- **Non-destructive overlays, rules & undo:** raw Plaid tables are never mutated. Deterministic 3-layer materialization (`raw` → prioritized JSON-AST rules → chronological manual overlays/splits) with field provenance, `rule_preview` dry-runs, and O(affected rows) non-LIFO `overlay_undo` / `overlay_redo`.
- **Structured queries + read-only SQL:** indexed filter/search/cursor-pagination (`transactions_query`), split-aware multi-dimension aggregations with period comparison (`transactions_aggregate`), and safe read-only MySQL SQL (`sql_query` / `sql_schema`) guarded by an AST validator and workspace-isolation rewriter over `DATABASE_READ_URL`.
- **Remote MCP server (`/mcp`):** stateless Streamable HTTP with OAuth 2.1 (PKCE S256, dynamic client registration, rotating refresh tokens, device flow, and workspace API tokens) backed by `account.anoma.ly` OIDC.

See [docs/plan.md](docs/plan.md) for the full architecture.

## Development

```sh
bun install --frozen-lockfile
bun run check        # typecheck + unit/integration tests + Worker bundle check
bun run db:generate  # generate Drizzle MySQL migration
bun run db:migrate   # apply migrations to DATABASE_URL
bun run dev          # run Worker locally via cf dev
```
