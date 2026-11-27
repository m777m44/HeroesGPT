# hermes-plugin-tirith

Scan every Hermes `terminal` command with [tirith](https://github.com/sheeki03/tirith)
before it runs. When tirith reports a finding, the command goes to Hermes's normal
approval prompt (CLI panel, gateway buttons, Desktop card) showing the finding's
severity, title and rule id. The plugin never approves or blocks anything on its
own: you decide, and cron / `-q` / unattended runs follow your
`approvals.cron_mode` / `single_query_mode` / `unattended_mode` (default `deny`).

Hermes used to bundle tirith in core. It moved here so that people who want it
can turn it on, and nobody else pays for it on every command.

## Install

1. Install tirith yourself. This plugin never downloads binaries:

   ```bash
   brew install tirith            # macOS / Linux with Homebrew
   # or a signed release: https://github.com/sheeki03/tirith/releases
   tirith --version
   ```

2. Install and enable the plugin:

   ```bash
   hermes plugins install tirith      # from the plugin catalog
   hermes plugins enable tirith
   ```

## Settings

Set these in Desktop under Capabilities, then Plugins, then tirith. From the CLI:
`hermes config set plugins.entries.tirith.settings.<key> <value>`.

| Key | Default | Meaning |
|---|---|---|
| `path` | `tirith` | Executable name on `PATH`, or an absolute path (`~` expands). |
| `timeout` | `5` | Seconds per scan. |
| `offline` | `true` | Pass `--offline`: no OSV / deps.dev / ecosyste.ms / Safe Browsing lookups. Set `false` to allow them (slower; package names leave your machine). |
| `min_severity` | `LOW` | Lowest severity that asks for approval. |
| `ignore_rules` | `[]` | Rule ids that never ask, e.g. `[analysis_incomplete, lookalike_tld]`. |
| `fail_closed` | `false` | If tirith is missing, times out or crashes, ask for approval instead of letting the command run unscanned. |

## What to expect

From a 40-command probe against tirith 0.4.2 (16 attack commands, 24 everyday
agent commands):

- It catches things Hermes's built-in patterns do not: homograph / punycode URLs,
  package typosquats, and some exfiltration shapes.
- It also flags many ordinary commands: `gh api ... | python3`, `echo $((6*7))`,
  `"$VAR/script.sh"`, curl to a LAN IP, `.dev` domains, and most `pip install` /
  `npm install` when `offline` is off (`analysis_incomplete`). Under cron with
  `cron_mode: deny`, every one of those is a blocked command. Use `ignore_rules`
  and `min_severity` to tune it.
- Approving a finding for the session covers later commands only when they trip
  exactly the same set of rules.
- tirith only sees `terminal` commands. `execute_code`, file writes and the
  browser do not pass through it.

## Disclosure

- Runs a local `tirith` executable on every terminal command (roughly 0.2 to 0.8s each).
- With `offline: false`, tirith contacts OSV, deps.dev, ecosyste.ms and (if you
  configured a key) Google Safe Browsing, and refreshes its threat database.
- No telemetry and no self-update. The plugin reads only its own settings.

## Development

```bash
python -m pytest -q
```

The scan logic (`tirith_scan.py`) has no Hermes imports. Tests use a fake tirith
executable, so no real binary is needed.

## Maintainers

Nous Research publishes this plugin. We have offered it to the tirith project
upstream; if they adopt it, this repository will point there.
