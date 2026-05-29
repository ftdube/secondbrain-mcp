# SecondBrain MCP — Agent Instructions

## What this is
Self-hosted MCP server giving Claude mobile access to an Obsidian vault via 4 tools:
`get_overview()` · `search(query)` · `read_note(path)` · `note(title, content)`

Phase 1a: FTS5 keyword search only. Phase 1b adds ONNX embeddings + RRF hybrid search.

## Hard rules
- **4 tools** — do not add tools without deliberate design decision; each tool costs ~250 tokens per session
- **FTS5-only in Phase 1a** — no embeddings, no sqlite-vec, no ONNX imports
- **`readOnlyRootFilesystem: true`** in K8s — server.py must not write outside `DB_PATH`, `OUTBOX_PATH`, and `/tmp`
- **AUTH_PUBLIC paths** (`/health`, `/reindex`, `/.well-known/oauth-protected-resource`) always skip JWT validation — do not remove these; extras are added via `AUTH_PUBLIC_EXTRA` env var
- **`note` writes to outbox only** — never writes directly to the vault; push-sync sidecar handles the git commit/push independently

## Non-obvious
- `mcp.http_app()` is the fastmcp 2.x method for the ASGI app. If missing in the installed version, try `mcp.streamable_http_app()` then `mcp.sse_app()` — the method name varies across minor versions
- Starlette lifespan must call `async with mcp_asgi.lifespan(app)` to initialize FastMCP's internal task group — omitting this causes 500s on all tool calls. `mcp_asgi.router.lifespan_context` does not exist in this version
- FTS5 `snippet()` column index 2 = body (0=path UNINDEXED, 1=heading, 2=body) — if the schema changes, update the index in the snippet call
- The vault watcher polls every 30s; git-sync runs every 5m — changes appear within 30s of a sync, no exechook needed
- `PyJWKClient(cache_keys=True)` caches Dex's signing keys in memory — a Dex key rotation requires a pod restart to pick up new keys
- FTS5 query errors are caught and retried as a quoted phrase — this is intentional, not a bug
- Cloudflare blocks in-cluster requests to the public Dex URL — OIDC discovery is skipped entirely; `DEX_JWKS_URI` points directly to the in-cluster JWKS endpoint (e.g. `http://dex.dex.svc.cluster.local:5556/keys`)
- `WWW-Authenticate` must include `resource_metadata="<MCP_BASE_URL>/.well-known/oauth-protected-resource"` — without it Claude.ai cannot discover the OAuth endpoint from a 401 and will not initiate the PKCE flow
- git-sync (official image) maintains a `vault/` symlink inside the mounted volume pointing to a `.git-sync/<sha>/` worktree — server.py reads from `VAULT_PATH/vault` with fallback to `VAULT_PATH` for local dev; never index via the raw mount root or `.git-sync/` paths will appear alongside canonical paths. `GITSYNC_LINK=vault` must be set or the symlink name defaults to the repo name and the path resolution breaks
- push-sync sidecar maintains its own independent `git clone` of the vault repo — it does not share the git-sync volume; it pulls before each push to avoid conflicts
- SSH key for push-sync must be mounted with mode `0600`; K8s Secret volumes default to `0644` which SSH rejects — set `defaultMode: 0400` on the secret volume mount

## Local dev
```bash
pip install -r requirements.txt
VAULT_PATH=/path/to/vault \
DEX_ISSUER=https://dex.example.com \
MCP_CLIENT_ID=mcp-secondbrain \
MCP_BASE_URL=http://localhost:8000 \
python server.py
```
To skip auth locally, set `AUTH_PUBLIC_EXTRA=/mcp` (or whatever the MCP transport path is).

