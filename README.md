# secondbrain-mcp

A self-hosted MCP server that gives the Claude mobile app (Android/iOS) access to an Obsidian vault. Files never leave your homelab — only queried excerpts reach Anthropic's servers.

## Why

Claude on desktop can navigate a vault via the filesystem MCP server. Mobile can't: the Claude app has no local filesystem access and the generic 11-tool filesystem server costs ~10k tokens per session. This server exposes exactly 5 tools, costs ~3.5k tokens per session, and runs on low-power hardware.

## How it works

```
Claude Mobile
  │ OAuth 2.1 / PKCE
  ▼
Dex (OIDC authorization server) ──► IdP
  │ JWT
  ▼
secondbrain-mcp (this server)
  │ reads                  │ writes to outbox
  ▼                        ▼
vault volume          outbox volume
  ▲                        │
git-sync sidecar      push-sync sidecar
  │                        │
  └──────── vault git repo ┘ ◄── Desktop Obsidian vault
```

Five tools:

| Tool | Returns |
|---|---|
| `get_overview()` | `context.md` + `_map.md` — called once per session |
| `search(query)` | Top 5 FTS5 excerpts (path + heading + ~200 chars) |
| `read_note(path)` | Full note by vault-relative path |
| `note(title, content)` | Saves a draft note to `Inbox/` for later review in Obsidian |
| `propose_edit(edits, rationale)` | Drafts a reviewable diff against one or more *existing* notes, saved to `Proposals/` — never writes the vault directly |

### Proposing edits to existing notes

`note` only creates new Inbox seeds — editing a structured note from Claude.ai (desktop or mobile) was previously off-limits on conflict/correctness grounds. `propose_edit` closes that gap safely: `edits` is an ordered list of `{path, old, new}` find/replace triples, applied in-process against the vault mirror (each anchor must match exactly once per note), and written as a single git-format diff — a `Proposals/*.patch.md` artifact — never mutating the vault or invoking git itself. Edits across multiple paths in one call become one atomic proposal: `scripts/apply_proposals.py` only applies it if *every* file in the patch checks clean, so it's all-or-nothing, never partially applied.

Proposals are applied out of band, model-free:

```bash
make proposals VAULT_REPO=/path/to/your/vault/clone        # dry-run: CLEAN vs STALE
make apply-proposals VAULT_REPO=/path/to/your/vault/clone  # git apply --3way, then delete applied patches
```

A stale proposal (the note drifted since drafting) is skipped, never force-applied or written with conflict markers. Applied edits land in the working tree uncommitted — review in Obsidian, then commit. See `agents.md` for the hard rule: applying a proposal is a command, never a conversation.

## Running locally

```bash
pip install -r requirements.txt

VAULT_PATH=/path/to/your/vault \
DEX_ISSUER=https://dex.example.com \
MCP_CLIENT_ID=mcp-secondbrain \
MCP_BASE_URL=http://localhost:8000 \
python server.py
```

Or with Docker Compose for local dev (vault mounted from host, no git required):

```bash
VAULT_PATH=/path/to/vault docker compose up mcp
```

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `VAULT_PATH` | yes | Path to the Obsidian vault directory |
| `DEX_ISSUER` | yes | Dex OIDC issuer URL (e.g. `https://dex.example.com`) |
| `MCP_CLIENT_ID` | yes | OAuth client ID registered in Dex |
| `MCP_BASE_URL` | yes | Public base URL of this server (for OAuth resource metadata) |
| `DB_PATH` | no | SQLite database path (default: `/data/index.db`) |
| `OUTBOX_PATH` | no | Directory where `note`/`propose_edit` write files for push-sync (default: `/outbox`) |
| `AUTH_PUBLIC_EXTRA` | no | Comma-separated paths to add to the public (no-auth) list |

## Endpoints

| Path | Auth | Description |
|---|---|---|
| `/` | Bearer JWT | MCP endpoint (streamable HTTP) |
| `/health` | none | Health check — `{"status": "ok"}` |
| `/metrics` | none | Prometheus metrics |
| `/reindex` | none | POST — rebuild FTS5 index from vault |
| `/.well-known/oauth-protected-resource` | none | OAuth 2.1 resource metadata |

## Monitoring

The `/metrics` endpoint exposes Prometheus counters. Point a Prometheus scrape job at it, then build Grafana panels from these metrics:

| Metric | Description |
|---|---|
| `mcp_overviews_total` | `get_overview` calls |
| `mcp_searches_total` | `search` calls |
| `mcp_reads_total` | `read_note` calls |
| `mcp_propose_edits_total` | `propose_edit` calls |
| `mcp_search_misses_total` | `search` calls that returned no results |
| `mcp_overview_chars_total` | Characters returned by `get_overview` |
| `mcp_search_chars_total` | Characters returned by `search` |
| `mcp_read_chars_total` | Characters returned by `read_note` |

**Useful PromQL**

Call volume:
```promql
rate(mcp_searches_total[5m])
```

Approximate tokens returned per tool (chars ÷ 4):
```promql
rate(mcp_search_chars_total[5m]) / 4
```

Search miss rate (useful for deciding when to upgrade to hybrid search):
```promql
rate(mcp_search_misses_total[1h]) / rate(mcp_searches_total[1h])
```

## Deployment

This server is designed to run in Kubernetes alongside Dex.

The `git-sync` sidecar polls the vault git repo every 5 minutes. The server detects changes by polling vault mtime every 30 seconds and reindexes automatically.

## Sidecars

**git-sync** uses the official [`registry.k8s.io/git-sync/git-sync`](https://github.com/kubernetes/git-sync) image. It clones the vault repo on startup and pulls every 5 minutes. The server detects the updated mtime and reindexes automatically.

**push-sync** is a small custom sidecar (`./sidecars`) built on `alpine/git`. It watches `OUTBOX_PATH` for files written by the `note` and `propose_edit` tools, routes `*.patch.md` files to `PROPOSALS_DIR/` (default `Proposals`) and everything else to `NOTE_INBOX/` (default `Inbox`) in the vault repo, commits, and pushes. This keeps git out of the main server container.

Both sidecars share `GIT_REPO_URL`, `GIT_BRANCH` (default: `main`), and the SSH key at `/ssh/id_ed25519` (configured via `SSH_KEY_PATH` in `.env`). See `compose.yaml` for the full configuration — it is the authoritative reference for sidecar env vars.

For local dev without a git repo, run only `docker compose up mcp`.

## Auth

Claude.ai mobile requires OAuth 2.1 with PKCE — static bearer tokens are not supported in the mobile UI. This server delegates authentication to [Dex](https://github.com/dexidp/dex), a self-hosted OIDC provider. Dex connects to GitHub or Google as the upstream IdP.

The Claude.ai redirect URI (`https://claude.ai/api/mcp/auth_callback`) must be registered in the Dex static client config.

## License

MIT
