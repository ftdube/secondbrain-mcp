# SecondBrain MCP — Agent Instructions

## What this is
Self-hosted MCP server giving Claude mobile access to an Obsidian vault via 3 tools:
`get_overview()` · `search(query)` · `read_note(path)`

Phase 1a: FTS5 keyword search only. Phase 1b adds ONNX embeddings + RRF hybrid search.

## Hard rules
- **3 tools only** — do not add tools without deliberate design decision; each tool costs ~250 tokens per session
- **FTS5-only in Phase 1a** — no embeddings, no sqlite-vec, no ONNX imports
- **`readOnlyRootFilesystem: true`** in K8s — server.py must not write outside `DB_PATH` and `/tmp`
- **AUTH_PUBLIC paths** (`/health`, `/reindex`, `/.well-known/oauth-protected-resource`) always skip JWT validation — do not remove these; extras are added via `AUTH_PUBLIC_EXTRA` env var

## Non-obvious
- `mcp.http_app()` is the fastmcp 2.x method for the ASGI app. If missing in the installed version, try `mcp.streamable_http_app()` then `mcp.sse_app()` — the method name varies across minor versions
- Starlette lifespan must call `async with mcp_asgi.lifespan(app)` to initialize FastMCP's internal task group — omitting this causes 500s on all tool calls. `mcp_asgi.router.lifespan_context` does not exist in this version
- FTS5 `snippet()` column index 2 = body (0=path UNINDEXED, 1=heading, 2=body) — if the schema changes, update the index in the snippet call
- The vault watcher polls every 30s; git-sync runs every 5m — changes appear within 30s of a sync, no exechook needed
- `PyJWKClient(cache_keys=True)` caches Dex's signing keys in memory — a Dex key rotation requires a pod restart to pick up new keys
- FTS5 query errors are caught and retried as a quoted phrase — this is intentional, not a bug

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

