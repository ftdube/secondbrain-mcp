# SecondBrain MCP — Agent Instructions

## What this is
Self-hosted MCP server giving Claude mobile access to an Obsidian vault via 5 tools:
`get_overview()` · `search(query)` · `read_note(path, offset=0)` · `note(title, content)` · `propose_edit(edits, rationale)`

Phase 1a: FTS5 keyword search only. Phase 1b adds ONNX embeddings + RRF hybrid search.

## Hard rules
- **5 tools** — do not add tools without deliberate design decision; each tool costs ~250 tokens per session
- **FTS5-only in Phase 1a** — no embeddings, no sqlite-vec, no ONNX imports
- **`readOnlyRootFilesystem: true`** in K8s — server.py must not write outside `DB_PATH`, `OUTBOX_PATH`, and `/tmp`
- **AUTH_PUBLIC paths** (`/health`, `/reindex`, `/.well-known/oauth-protected-resource`) always skip JWT validation — do not remove these; extras are added via `AUTH_PUBLIC_EXTRA` env var
- **`note` writes to outbox only** — never writes directly to the vault; push-sync sidecar handles the git commit/push independently
- **`propose_edit` never touches the vault or git** — it emits a diff to the outbox; push-sync routes `*.patch.md` to `Proposals/`
- **Applying a proposal is a command, never a conversation** — run `make apply-proposals` (→ `scripts/apply_proposals.py`, `git apply --3way`). Never read, reason about, or hand-apply a `Proposals/*.patch.md` file yourself

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
- SSH key for push-sync: K8s Secret volumes default to `0644` (world-readable), which SSH rejects — set `defaultMode: 0400` on the secret volume mount
- `propose_edit`'s diff `index` line is always a dummy `0000000..0000000`, never a real git blob hash — a real hash lets `git apply --3way` find the historical blob and do a genuine content merge, which can silently write conflict markers on drift while `--check` reports it clean (verified: real hash + drifted target line = false-clean check, corrupted file on real apply). Dummy hash forces plain context matching: drift is rejected cleanly instead of merged
- Multi-file proposals (F8) are atomic *only* because `scripts/apply_proposals.py` always runs `check()` (`git apply --3way --check`) before `apply_one()` and skips the apply entirely if check fails — `git apply` itself is NOT atomic across files in one patch (verified: with one drifted file among several, a bare `git apply` on the whole patch still mutates the earlier, non-drifted files before failing on the later one). Never call `apply_one()` without a preceding clean `check()` on the same patch
- `VAULT_BLACKLIST` lives entirely inside `_resolve_in_vault` (not duplicated per-tool) and matches by path *segment* (`Path(...).parts`), not raw string prefix, so `Health/Psychology` doesn't also catch `Health/PsychologyNotes.md`. Leading slashes are stripped from entries before matching — a typo'd `/Health/X` would otherwise silently match nothing, which matters because this is a privacy control

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

