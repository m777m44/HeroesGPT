> **Unmaintained — looking for an owner.** Hermes Agent removes its bundled `retaindb` memory provider from core on **October 15, 2026**. This repo is a standalone copy of that provider, kept by Nous Research only so someone can take it over: Nous does not maintain it, publish fixes for it, or list it in the Hermes plugin catalog. We've asked RetainDB to take it over (https://github.com/RetainDB/RetainDB/issues/3). RetainDB or anyone else who wants to own it: open an issue here and we'll help with the handoff (repo transfer or fork, plus the catalog entry that lets `hermes update` move existing users onto your plugin). See [HANDOFF.md](HANDOFF.md).

# RetainDB Memory Provider

Cloud memory API with hybrid search (Vector + BM25 + Reranking) and 7 memory types.

## Requirements

- RetainDB account ($20/month) from [retaindb.com](https://www.retaindb.com)
- `requests` (declared in `pyproject.toml`; `hermes plugins install` puts it in the Hermes venv, and Hermes core already ships it)

## Setup

```bash
hermes memory setup    # select "retaindb"
```

Or manually:
```bash
hermes config set memory.provider retaindb
echo "RETAINDB_API_KEY=your-key" >> ~/.hermes/.env
```

## Config

All config via environment variables in `.env`:

| Env Var | Default | Description |
|---------|---------|-------------|
| `RETAINDB_API_KEY` | (required) | API key |
| `RETAINDB_BASE_URL` | `https://api.retaindb.com` | API endpoint |
| `RETAINDB_PROJECT` | auto (profile-scoped) | Project identifier |

## Tools

| Tool | Description |
|------|-------------|
| `retaindb_profile` | User's stable profile |
| `retaindb_search` | Semantic search |
| `retaindb_context` | Task-relevant context |
| `retaindb_remember` | Store a fact with type + importance |
| `retaindb_forget` | Delete a memory by ID |
