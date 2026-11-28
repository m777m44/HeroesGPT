import type { AccountView, InviteRecord, MemberRecord, WorkspaceRecord } from "@radiant/core"
import { escapeHtml } from "./env"

const BASE_CSS = `
:root { color-scheme: light dark; --bg: #fafafa; --fg: #111; --muted: #666; --card: #fff; --border: #e5e5e5; --accent: #111; --accent-fg: #fff; --danger: #c62828; }
@media (prefers-color-scheme: dark) {
  :root { --bg: #0c0c0d; --fg: #f2f2f3; --muted: #9a9aa0; --card: #141416; --border: #26262a; --accent: #f2f2f3; --accent-fg: #0c0c0d; --danger: #ef5350; }
}
* { box-sizing: border-box; }
body { margin: 0; font: 14px/1.5 ui-sans-serif, system-ui, -apple-system, sans-serif; background: var(--bg); color: var(--fg); }
main { max-width: 920px; margin: 0 auto; padding: 32px 20px 80px; }
header.top { display: flex; align-items: center; justify-content: space-between; gap: 16px; border-bottom: 1px solid var(--border); padding-bottom: 16px; margin-bottom: 28px; }
h1, h2, h3 { margin: 0 0 12px; font-weight: 600; letter-spacing: -0.02em; }
h1 { font-size: 20px; } h2 { font-size: 15px; margin-top: 28px; }
p { margin: 0 0 12px; color: var(--muted); }
a { color: inherit; }
.card { background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 16px; margin-bottom: 16px; }
.row { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 10px; }
.stack { display: flex; flex-direction: column; gap: 10px; }
.inline { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
button, .btn { appearance: none; display: inline-flex; align-items: center; gap: 6px; padding: 7px 12px; border-radius: 6px; border: 1px solid var(--border); background: var(--card); color: var(--fg); font: inherit; font-weight: 500; text-decoration: none; cursor: pointer; }
button.primary, .btn.primary { background: var(--accent); color: var(--accent-fg); border-color: var(--accent); }
button.danger { color: var(--danger); }
button:disabled { opacity: 0.5; cursor: not-allowed; }
input, select { padding: 7px 10px; border-radius: 6px; border: 1px solid var(--border); background: var(--bg); color: var(--fg); font: inherit; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th, td { text-align: left; padding: 8px 6px; border-bottom: 1px solid var(--border); }
th { color: var(--muted); font-weight: 500; }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
code, pre { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; }
pre { background: var(--bg); border: 1px solid var(--border); border-radius: 6px; padding: 12px; overflow-x: auto; margin: 8px 0; }
.badge { display: inline-block; padding: 2px 7px; border-radius: 99px; font-size: 11px; border: 1px solid var(--border); color: var(--muted); }
.badge.ok { color: #1b7f46; border-color: #1b7f4655; }
.badge.warn { color: #b26a00; border-color: #b26a0055; }
.muted { color: var(--muted); font-size: 12px; }
`

const layout = (title: string, body: string, markdownHref?: string): string => `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>${escapeHtml(title)} — Radiant</title>
  ${markdownHref ? `<link rel="alternate" type="text/markdown" href="${escapeHtml(markdownHref)}" />` : ""}
  <style>${BASE_CSS}</style>
</head>
<body>
  <main>${body}</main>
</body>
</html>`

const fmtMoney = (cents: number | null, currency = "USD"): string => {
  if (cents === null || cents === undefined) return "—"
  const sign = cents < 0 ? "-" : ""
  const abs = Math.abs(cents) / 100
  return `${sign}${currency === "USD" ? "$" : `${currency} `}${abs.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

export const renderLandingPage = (baseUrl: string, basePath = ""): string =>
  layout(
    "Sign in",
    `
    <header class="top">
      <h1>Radiant</h1>
      <a class="btn primary" href="${escapeHtml(basePath)}/auth/login">Sign in with Anomaly</a>
    </header>
    <div class="card stack">
      <p style="color:var(--fg);font-size:15px;">Sync Plaid accounts into PlanetScale MySQL and query, overlay, and automate them over MCP.</p>
      <p>Create workspaces, invite teammates or family, connect bank accounts via Plaid Link, apply non-destructive overlays & rules with instant undo, and run structured aggregations or read-only SQL from your agent.</p>
      <div class="inline">
        <a class="btn primary" href="${escapeHtml(basePath)}/auth/login">Sign in to continue</a>
        <a class="btn" href="${escapeHtml(basePath)}/index.md">Agent docs (Markdown)</a>
      </div>
    </div>
    <div class="card">
      <h3>Use with an Agent</h3>
      <p>Paste <code>${escapeHtml(baseUrl)}</code> into your agent — it receives a Markdown onboarding guide with Device Flow sign-in and 1-click bank connect links, or add the MCP server directly:</p>
      <pre>${escapeHtml(baseUrl)}/mcp</pre>
      <p class="muted">Supports OAuth 2.1 with dynamic client registration and PKCE (OpenCode, Claude, Cursor).</p>
    </div>
  `,
    `${baseUrl.replace(/\/+$/, "")}/index.md`,
  )

export const renderEmptyWorkspacesPage = (email: string, basePath = ""): string =>
  layout(
    "Create workspace",
    `
    <header class="top">
      <h1>Radiant</h1>
      <div class="inline">
        <span class="muted">${escapeHtml(email)}</span>
        <form method="POST" action="${escapeHtml(basePath)}/auth/logout"><button type="submit">Sign out</button></form>
      </div>
    </header>
    <div class="card stack">
      <h2>Create your first workspace</h2>
      <p>Group your Plaid accounts, rules, overlays, and collaborators inside a workspace.</p>
      <form class="inline" method="POST" action="${escapeHtml(basePath)}/ui/workspaces">
        <input name="name" placeholder="Personal" required maxlength="120" />
        <input name="currency" value="USD" maxlength="3" style="width:76px" />
        <button class="primary" type="submit">Create workspace</button>
      </form>
    </div>
  `,
  )

export const renderWorkspaceDashboard = (input: {
  readonly baseUrl: string
  readonly basePath: string
  readonly email: string
  readonly workspace: WorkspaceRecord
  readonly workspaces: ReadonlyArray<WorkspaceRecord>
  readonly items: ReadonlyArray<{
    readonly item_id: string
    readonly institution_name: string
    readonly status: string
    readonly error_code: string | null
    readonly last_synced_at: string | null
  }>
  readonly accounts: ReadonlyArray<AccountView>
  readonly members: ReadonlyArray<MemberRecord>
  readonly invites: ReadonlyArray<InviteRecord>
  readonly batches: ReadonlyArray<Record<string, unknown>>
  readonly flash?: string | null
}): string => {
  const ws = input.workspace
  const bp = input.basePath
  const mcpUrl = `${input.baseUrl.replace(/\/$/, "")}/mcp`
  const opencodeSnippet = JSON.stringify(
    { mcp: { servers: { radiant: { type: "remote", url: mcpUrl } } } },
    null,
    2,
  )

  const wsOptions = input.workspaces
    .map(
      (w) =>
        `<option value="${escapeHtml(bp)}/w/${escapeHtml(w.slug)}" ${w.id === ws.id ? "selected" : ""}>${escapeHtml(w.name)} (${escapeHtml(w.role)})</option>`,
    )
    .join("")

  const itemsHtml =
    input.items.length === 0
      ? `<p class="muted">No Plaid institutions connected yet.</p>`
      : `<table>
          <thead><tr><th>Institution</th><th>Status</th><th>Last Synced</th><th></th></tr></thead>
          <tbody>
            ${input.items
              .map(
                (it) => `<tr>
                  <td><strong>${escapeHtml(it.institution_name)}</strong><div class="muted">${escapeHtml(it.item_id)}</div></td>
                  <td><span class="badge ${it.status === "healthy" ? "ok" : "warn"}">${escapeHtml(it.status)}${it.error_code ? ` (${escapeHtml(it.error_code)})` : ""}</span></td>
                  <td class="muted">${it.last_synced_at ? escapeHtml(String(it.last_synced_at)) : "Never"}</td>
                  <td class="num">
                    <div class="inline" style="justify-content:flex-end">
                      <button type="button" onclick="syncItem('${escapeHtml(it.item_id)}')">Sync</button>
                      ${it.status !== "healthy" ? `<button type="button" onclick="openPlaid('update','${escapeHtml(it.item_id)}')">Reconnect</button>` : ""}
                      <button type="button" class="danger" onclick="removeItem('${escapeHtml(it.item_id)}')">Disconnect</button>
                    </div>
                  </td>
                </tr>`,
              )
              .join("")}
          </tbody>
        </table>`

  const accountsHtml =
    input.accounts.length === 0
      ? `<p class="muted">Accounts appear here once synced.</p>`
      : `<table>
          <thead><tr><th>Account</th><th>Institution</th><th>Type</th><th>Status</th><th class="num">Balance</th><th></th></tr></thead>
          <tbody>
            ${input.accounts
              .map(
                (a) => `<tr style="${a.is_active ? "" : "opacity:0.55"}">
                  <td>${escapeHtml(a.nickname ?? a.name)}${a.mask ? ` <span class="muted">••${escapeHtml(a.mask)}</span>` : ""}</td>
                  <td class="muted">${escapeHtml(a.institution_name)}</td>
                  <td class="muted">${escapeHtml(a.type)}${a.subtype ? `/${escapeHtml(a.subtype)}` : ""}</td>
                  <td><span class="badge ${a.is_active ? "ok" : ""}">${a.is_active ? "active" : "inactive"}</span></td>
                  <td class="num">${escapeHtml(fmtMoney(a.current_cents, a.currency))}</td>
                  <td class="num"><button type="button" onclick="toggleAccount('${escapeHtml(a.id)}',${a.is_active ? "false" : "true"})">${a.is_active ? "Deactivate" : "Activate"}</button></td>
                </tr>`,
              )
              .join("")}
          </tbody>
        </table>`

  const membersHtml = `<table>
    <thead><tr><th>Member</th><th>Role</th></tr></thead>
    <tbody>
      ${input.members
        .map(
          (m) => `<tr>
            <td>${escapeHtml(m.email)}${m.name ? ` <span class="muted">(${escapeHtml(m.name)})</span>` : ""}</td>
            <td><span class="badge">${escapeHtml(m.role)}</span></td>
          </tr>`,
        )
        .join("")}
    </tbody>
  </table>`

  const batchesHtml =
    input.batches.length === 0
      ? `<p class="muted">No overlay or rule edits yet.</p>`
      : `<table>
          <thead><tr><th>Batch</th><th>Actor</th><th>Reason</th><th class="num">Rows</th><th></th></tr></thead>
          <tbody>
            ${input.batches
              .map((b) => {
                const id = String(b.id)
                const reverted = Boolean(b.reverted_at)
                return `<tr>
                  <td><code>${escapeHtml(String(b.kind))}</code><div class="muted">${escapeHtml(id)}</div></td>
                  <td class="muted">${escapeHtml(String(b.client_name ?? b.actor_type))}</td>
                  <td>${escapeHtml(String(b.reason ?? "—"))}${reverted ? ' <span class="badge warn">reverted</span>' : ""}</td>
                  <td class="num">${escapeHtml(String(b.affected_count ?? 0))}</td>
                  <td class="num">
                    ${reverted
                      ? `<button type="button" onclick="batchAction('${escapeHtml(id)}','redo')">Redo</button>`
                      : `<button type="button" onclick="batchAction('${escapeHtml(id)}','undo')">Undo</button>`}
                  </td>
                </tr>`
              })
              .join("")}
          </tbody>
        </table>`

  return layout(
    ws.name,
    `
    <header class="top">
      <div class="inline">
        <h1>Radiant</h1>
        <select aria-label="Workspace" onchange="if(this.value)location.href=this.value">${wsOptions}</select>
      </div>
      <div class="inline">
        <span class="muted">${escapeHtml(input.email)}</span>
        <form method="POST" action="${escapeHtml(bp)}/auth/logout"><button type="submit">Sign out</button></form>
      </div>
    </header>

    ${input.flash ? `<div class="card" style="border-color:var(--accent)">${escapeHtml(input.flash)}</div>` : ""}

    <div class="card">
      <div class="row" style="margin-bottom:12px">
        <h2 style="margin:0">Plaid Connections</h2>
        <div class="inline">
          <button type="button" onclick="syncAll()">Sync all</button>
          <button type="button" class="primary" onclick="openPlaid('new')">Connect bank</button>
        </div>
      </div>
      ${itemsHtml}
    </div>

    <div class="card">
      <h2 style="margin-top:0">Accounts</h2>
      ${accountsHtml}
    </div>

    <div class="card">
      <h2 style="margin-top:0">MCP Server</h2>
      <p>Connect OpenCode or any MCP client via OAuth 2.1:</p>
      <pre id="mcp-snippet">${escapeHtml(opencodeSnippet)}</pre>
      <div class="inline">
        <button type="button" onclick="navigator.clipboard.writeText(document.getElementById('mcp-snippet').textContent)">Copy opencode.json</button>
        <button type="button" onclick="mintToken()">Create workspace API token</button>
      </div>
      <div id="token-out" class="muted" style="margin-top:8px"></div>
    </div>

    <div class="card">
      <h2 style="margin-top:0">Members & Invites</h2>
      ${membersHtml}
      <form class="inline" style="margin-top:12px" onsubmit="createInvite(event)">
        <input id="inv-email" type="email" placeholder="teammate@example.com" required />
        <select id="inv-role">
          <option value="member">member</option>
          <option value="admin">admin</option>
          <option value="viewer">viewer</option>
        </select>
        <button type="submit">Create invite link</button>
      </form>
      <div id="inv-out" class="muted" style="margin-top:8px"></div>
    </div>

    <div class="card">
      <h2 style="margin-top:0">Recent Overlays & Rules Activity</h2>
      ${batchesHtml}
    </div>

    <div class="card">
      <h2 style="margin-top:0">New Workspace</h2>
      <form class="inline" method="POST" action="${escapeHtml(bp)}/ui/workspaces">
        <input name="name" placeholder="Household" required maxlength="120" />
        <input name="currency" value="USD" maxlength="3" style="width:76px" />
        <button type="submit">Create</button>
      </form>
    </div>

    <script src="https://cdn.plaid.com/link/v2/stable/link-initialize.js"></script>
    <script>
      const WS = ${JSON.stringify(ws.id)};
      const BASE = ${JSON.stringify(bp)};
      async function api(path, opts = {}) {
        const res = await fetch(BASE + path, { headers: { "content-type": "application/json" }, ...opts });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.error || data.message || res.statusText);
        return data;
      }
      async function openPlaid(mode, itemId) {
        try {
          const { link_token } = await api("/api/v1/workspaces/" + WS + "/plaid/link-token", {
            method: "POST",
            body: JSON.stringify({ mode, item_id: itemId }),
          });
          const handler = Plaid.create({
            token: link_token,
            onSuccess: async (public_token) => {
              await api("/api/v1/workspaces/" + WS + "/plaid/exchange", {
                method: "POST",
                body: JSON.stringify({ public_token }),
              });
              location.reload();
            },
          });
          handler.open();
        } catch (err) { alert("Plaid error: " + err.message); }
      }
      async function syncItem(itemId) {
        try {
          await api("/api/v1/workspaces/" + WS + "/plaid/sync", { method: "POST", body: JSON.stringify({ item_id: itemId }) });
          location.reload();
        } catch (err) { alert(err.message); }
      }
      async function syncAll() {
        try {
          await api("/api/v1/workspaces/" + WS + "/plaid/sync", { method: "POST", body: "{}" });
          location.reload();
        } catch (err) { alert(err.message); }
      }
      async function removeItem(itemId) {
        if (!confirm("Disconnect this bank institution?")) return;
        try {
          await api("/api/v1/workspaces/" + WS + "/plaid/items/" + encodeURIComponent(itemId), { method: "DELETE" });
          location.reload();
        } catch (err) { alert(err.message); }
      }
      async function toggleAccount(accountId, nextActive) {
        try {
          await api("/api/v1/workspaces/" + WS + "/accounts/" + encodeURIComponent(accountId) + "/overlay", {
            method: "POST",
            body: JSON.stringify({ is_active: nextActive, reason: nextActive ? "Activated account" : "Deactivated account" }),
          });
          location.reload();
        } catch (err) { alert(err.message); }
      }
      async function batchAction(batchId, action) {
        try {
          await api("/api/v1/workspaces/" + WS + "/overlays/batches/" + encodeURIComponent(batchId) + "/" + action, { method: "POST" });
          location.reload();
        } catch (err) { alert(err.message); }
      }
      async function createInvite(ev) {
        ev.preventDefault();
        try {
          const email = document.getElementById("inv-email").value;
          const role = document.getElementById("inv-role").value;
          const res = await api("/api/v1/workspaces/" + WS + "/invites", {
            method: "POST",
            body: JSON.stringify({ email, role }),
          });
          document.getElementById("inv-out").innerHTML = "Invite URL (copied): <code>" + res.invite_url + "</code>";
          navigator.clipboard.writeText(res.invite_url).catch(() => {});
        } catch (err) { alert(err.message); }
      }
      async function mintToken() {
        const name = prompt("Token name (e.g. local-script):", "agent-token");
        if (!name) return;
        try {
          const res = await api("/api/v1/workspaces/" + WS + "/tokens", {
            method: "POST",
            body: JSON.stringify({ name, role: "member" }),
          });
          document.getElementById("token-out").innerHTML = "Token (shown once): <code>" + res.token + "</code>";
        } catch (err) { alert(err.message); }
      }
    </script>
  `,
  )
}

export const renderConnectHandoffPage = (input: {
  readonly basePath: string
  readonly workspaceId: string
  readonly workspaceName: string
  readonly workspaceSlug: string
  readonly connectToken: string
  readonly mode: "new" | "update"
  readonly itemId: string | null
}): string =>
  layout(
    "Connect Bank",
    `
    <div class="card stack">
      <h1>${input.mode === "update" ? "Reconnect Bank Account" : "Connect Bank Account"}</h1>
      <p>Connecting a bank account to workspace <strong>${escapeHtml(input.workspaceName)}</strong> (<code>${escapeHtml(input.workspaceId)}</code>).</p>
      <div class="inline">
        <button id="launch" class="primary" type="button">${input.mode === "update" ? "Reconnect with Plaid" : "Connect bank with Plaid"}</button>
        <a class="btn" href="${escapeHtml(input.basePath)}/w/${escapeHtml(input.workspaceSlug)}">Open workspace</a>
      </div>
      <div id="status" class="muted">Opening Plaid Link…</div>
      <ul id="connected-list" style="margin:0;padding-left:18px"></ul>
    </div>
    <script src="https://cdn.plaid.com/link/v2/stable/link-initialize.js"></script>
    <script>
      const BASE = ${JSON.stringify(input.basePath)};
      const WS = ${JSON.stringify(input.workspaceId)};
      const MODE = ${JSON.stringify(input.mode)};
      const ITEM_ID = ${JSON.stringify(input.itemId)};
      const CONNECT_TOKEN = ${JSON.stringify(input.connectToken)};
      let linkedAny = false;

      async function launch() {
        const btn = document.getElementById("launch");
        const status = document.getElementById("status");
        btn.disabled = true;
        status.textContent = "Opening Plaid Link…";
        try {
          const res = await fetch(BASE + "/api/v1/workspaces/" + WS + "/plaid/link-token", {
            method: "POST",
            headers: { "content-type": "application/json" },
            body: JSON.stringify({ mode: linkedAny ? "new" : MODE, item_id: linkedAny ? null : ITEM_ID }),
          });
          const data = await res.json();
          if (!res.ok) throw new Error(data.message || data.error || "Failed to create link token");
          const handler = Plaid.create({
            token: data.link_token,
            onSuccess: async (public_token) => {
              status.textContent = "Syncing accounts and transactions…";
              try {
                const ex = await fetch(BASE + "/api/v1/workspaces/" + WS + "/plaid/exchange", {
                  method: "POST",
                  headers: { "content-type": "application/json" },
                  body: JSON.stringify({ public_token, connect_token: CONNECT_TOKEN }),
                });
                const exData = await ex.json();
                if (!ex.ok) throw new Error(exData.message || exData.error || "Exchange failed");
                linkedAny = true;
                const li = document.createElement("li");
                li.textContent = (exData.institution_name || "Bank") + " — " + (exData.accounts_count ?? 0) + " account(s), " + (exData.sync?.added ?? 0) + " transaction(s) synced";
                document.getElementById("connected-list").appendChild(li);
                status.textContent = "Connected! You can connect another bank below or return to your agent.";
                btn.textContent = "Connect another bank";
              } catch (err) {
                status.textContent = "Sync error: " + err.message;
              } finally {
                btn.disabled = false;
              }
            },
            onExit: () => {
              btn.disabled = false;
              if (!linkedAny) status.textContent = "Plaid Link closed. Click the button above to try again.";
            },
          });
          handler.open();
        } catch (e) {
          btn.disabled = false;
          status.textContent = "Error: " + e.message;
        }
      }
      document.getElementById("launch").addEventListener("click", launch);
      window.addEventListener("load", () => { launch(); });
    </script>
  `,
  )

export const renderOAuthConsentPage = (input: {
  readonly basePath: string
  readonly clientName: string
  readonly redirectUri: string
  readonly email: string
  readonly hiddenFields: Record<string, string>
}): string => {
  const inputs = Object.entries(input.hiddenFields)
    .map(([k, v]) => `<input type="hidden" name="${escapeHtml(k)}" value="${escapeHtml(v)}" />`)
    .join("")
  return layout(
    "Authorize client",
    `
    <div class="card stack">
      <h1>Authorize ${escapeHtml(input.clientName)}</h1>
      <p>Signed in as <strong>${escapeHtml(input.email)}</strong>.</p>
      <p>This client is requesting access to your Radiant workspaces, accounts, transactions, overlays, rules, and SQL queries.</p>
      <p class="muted">Redirect URI: <code>${escapeHtml(input.redirectUri)}</code></p>
      <form class="inline" method="POST" action="${escapeHtml(input.basePath)}/oauth/authorize">
        ${inputs}
        <button class="primary" type="submit" name="decision" value="approve">Approve</button>
        <button type="submit" name="decision" value="deny">Deny</button>
      </form>
    </div>
  `,
  )
}

export const renderDeviceApprovePage = (input: {
  readonly basePath: string
  readonly email: string
  readonly code: string
  readonly clientName?: string | null
  readonly message?: string
}): string =>
  layout(
    "Approve agent sign-in",
    `
    <div class="card stack">
      <h1>Approve ${escapeHtml(input.clientName || "Agent")} Sign-In</h1>
      <p>Signed in as <strong>${escapeHtml(input.email)}</strong>. ${input.clientName ? `<strong>${escapeHtml(input.clientName)}</strong> wants to access your Radiant workspaces.` : ""} Verify the code shown by your agent before approving.</p>
      ${input.message ? `<p style="color:var(--fg)"><strong>${escapeHtml(input.message)}</strong></p>` : ""}
      <form class="inline" method="POST" action="${escapeHtml(input.basePath)}/device">
        <input name="code" value="${escapeHtml(input.code)}" placeholder="BCDF-GHJK" required />
        <button class="primary" type="submit" name="decision" value="approve">Approve</button>
        <button type="submit" name="decision" value="deny">Deny</button>
      </form>
    </div>
  `,
  )
