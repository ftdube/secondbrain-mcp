# SecondBrain MCP

Self-hosted MCP server giving Claude mobile access to an Obsidian vault via 5 tools:
`get_overview()` · `search(query)` · `read_note(path, offset=0)` · `note(title, content)` · `propose_edit(edits, rationale)`

[`BRD.md`](BRD.md) defines every `FR-*`/`NFR-*` ID below and holds the rationale this file omits. Rebuild: [`REBUILD.md`](REBUILD.md).

## Hard rules
- **5 tools** — do not add one without a deliberate design decision; each costs ~250 tokens per session (NFR-COM-1)
- **FTS5 only until Phase 1b** — no embeddings, no sqlite-vec, no ONNX imports
- **`readOnlyRootFilesystem: true`** in K8s — `server.py` must not write outside `DB_PATH`, `OUTBOX_PATH` and `/tmp`
- **Public auth paths** (FR-AUTH-2) always skip JWT validation — do not remove them; extras go in the `AUTH_PUBLIC_EXTRA` env var
- **`note` writes to the outbox only**, never the vault; the push-sync sidecar commits and pushes
- **`propose_edit` never touches the vault or git** — it emits a diff to the outbox; push-sync routes `*.patch.md` to `Proposals/`
- **Applying a proposal is a command, never a conversation** — run `make apply-proposals`. Never read, reason about, or hand-apply a `Proposals/*.patch.md` file yourself (NFR-PROP-5)
- **Never call `apply_one()` without a preceding clean `check()` on the same patch** — `git apply` is not atomic across files; this is what makes multi-file proposals atomic (NFR-PROP-8, RISK-5)
- **`propose_edit`'s diff `index` line stays the dummy `0000000..0000000`** — a real blob hash lets `--3way` merge drift into conflict markers while `--check` reports clean (NFR-PROP-9). Creates are guarded separately: `apply_proposals.py` rejects a create whose target exists (NFR-PROP-11)
- **`BRD.md` is a requirements document, not a log** — current requirements and status only. Risks go in `RISKS.md`, backlog in GitHub Issues. Git history and PRs are the log

## Non-obvious
- The Starlette lifespan must run `async with mcp_asgi.lifespan(app)` to start FastMCP's task group — without it every tool call returns 500
- FTS5 `snippet()` column index 2 = body (0 = path UNINDEXED, 1 = heading) — update the index if the schema changes
- FTS5 query errors are caught and retried as a quoted phrase — intentional, not a bug
- A Dex key rotation needs a pod restart: JWKS keys are cached in-process (NFR-AUTH-2)
- OIDC discovery is skipped; `DEX_JWKS_URI` points at the in-cluster JWKS endpoint (NFR-AUTH-3)
- `WWW-Authenticate` must carry `resource_metadata="<MCP_BASE_URL>/.well-known/oauth-protected-resource"`, or Claude.ai cannot discover the OAuth endpoint from a 401 (FR-AUTH-4)
- git-sync maintains a `vault/` symlink to a `.git-sync/<sha>/` worktree; `server.py` reads `VAULT_PATH/vault`, falling back to `VAULT_PATH` for local dev. Never index the raw mount root, or `.git-sync/` paths appear alongside canonical ones. `GITSYNC_LINK=vault` must be set, or the symlink takes the repo's name and path resolution breaks
- push-sync keeps its own `git clone` of the vault repo, not the git-sync volume, and pulls before each push
- K8s Secret volumes default to `0644`, which SSH rejects: mount the push-sync key with `defaultMode: 0400` (NFR-SEC-2)
- `VAULT_BLACKLIST` is enforced only in `_resolve_in_vault` and matches by path segment, with leading slashes stripped (FR-BLK-4) — a privacy control, so a silent non-match is the failure to fear

## Contributing

What an outside contributor must follow that CI does not enforce:

- Branch from `main` as `feature/<name>`, `fix/<name>` or `docs/<name>`, then open a pull request.
- Never commit secrets. CI's `secrets` job scans all of history, but by then a pushed secret is already public: rotate it, since rewriting history does not take it back.
- No personal identifiers (domains, hostnames, usernames, emails, IPs) or personal infrastructure in any file except the repository's ownership metadata (`.github/CODEOWNERS`, `LICENSE`); deployment specifics arrive through environment variables.
- Requirements and their rationale go in [`BRD.md`](BRD.md), risks in [`RISKS.md`](RISKS.md), deferred work in [`next-steps.md`](next-steps.md) with the condition that triggers it, and the backlog in GitHub Issues.
- One-time setup goes in [`REBUILD.md`](REBUILD.md). This file holds only hard rules and non-obvious gotchas, under 1,600 tokens (words × 1.33).
- Each fact lives in one file; link to it rather than copying it.
- Code comments only when the why is non-obvious; no multi-line docstrings.
