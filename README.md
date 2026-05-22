# secondbrain-mcp

A self-hosted MCP server that gives the Claude mobile app (Android/iOS) access to an Obsidian vault. Files never leave your homelab — only queried excerpts reach Anthropic's servers.

## Why

Claude on desktop can navigate a vault via the filesystem MCP server. Mobile can't: the Claude app has no local filesystem access and the generic 11-tool filesystem server costs ~10k tokens per session. This server exposes exactly 3 tools, costs ~3k tokens per session, and runs on low-power hardware.

## How it works

```
Claude Mobile
  │ OAuth 2.1 / PKCE
  ▼
Dex (OIDC authorization server) ──► IdP
  │ JWT
  ▼
secondbrain-mcp (this server)
  │ reads
  ▼
emptyDir vault ◄── git-sync sidecar ◄── vault git repo ◄── Desktop Obsidian vault
```

Three tools:

| Tool | Returns |
|---|---|
| `get_overview()` | `context.md` + `_map.md` — called once per session |
| `search(query)` | Top 5 FTS5 excerpts (path + heading + ~200 chars) |
| `read_note(path)` | Full note by vault-relative path |

## Running locally

```bash
pip install -r requirements.txt

VAULT_PATH=/path/to/your/vault \
DEX_ISSUER=https://dex.example.com \
MCP_CLIENT_ID=mcp-secondbrain \
MCP_BASE_URL=http://localhost:8000 \
python server.py
```

Or with Docker Compose (set `VAULT_PATH` to your vault directory):

```bash
VAULT_PATH=/path/to/vault docker compose up
```

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `VAULT_PATH` | yes | Path to the Obsidian vault directory |
| `DEX_ISSUER` | yes | Dex OIDC issuer URL (e.g. `https://dex.example.com`) |
| `MCP_CLIENT_ID` | yes | OAuth client ID registered in Dex |
| `MCP_BASE_URL` | yes | Public base URL of this server (for OAuth resource metadata) |
| `DB_PATH` | no | SQLite database path (default: `/data/index.db`) |

## Endpoints

| Path | Auth | Description |
|---|---|---|
| `/` | Bearer JWT | MCP endpoint (streamable HTTP) |
| `/health` | none | Health check — `{"status": "ok"}` |
| `/reindex` | none | POST — rebuild FTS5 index from vault |
| `/.well-known/oauth-protected-resource` | none | OAuth 2.1 resource metadata |

## Deployment

This server is designed to run in Kubernetes alongside Dex.

The `git-sync` sidecar polls a git repo every 5 minutes and calls `POST /reindex` on each sync. The server also polls vault mtime every 30 seconds as a fallback.

## Auth

Claude.ai mobile requires OAuth 2.1 with PKCE — static bearer tokens are not supported in the mobile UI. This server delegates authentication to [Dex](https://github.com/dexidp/dex), a self-hosted OIDC provider. Dex connects to GitHub or Google as the upstream IdP.

The Claude.ai redirect URI (`https://claude.ai/api/mcp/auth_callback`) must be registered in the Dex static client config.

## License

MIT
