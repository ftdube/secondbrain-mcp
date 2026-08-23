# Business Requirements Document — SecondBrain MCP Server

## Document Control

| Field | Value |
|---|---|
| Document title | Business Requirements Document — SecondBrain MCP Server |
| Document version | 1.4 (Draft) |
| System / API version documented | 1.1.0 |
| Date | 2026-08-23 |
| Author | Claude Code, on behalf of the repository owner |
| Classification | Public (repository is open-source; see §6 for redaction policy) |
| Related artifacts | [`agents.md`](agents.md), [`README.md`](README.md), [`next-steps.md`](next-steps.md) |

### Revision History

| Version | Date | Author | Summary of changes |
|---|---|---|---|
| 1.0 | 2026-08-23 | Claude Code | Initial issue. Covers the Phase 1a service (`get_overview`, `search`, `read_note`, `note`) plus `propose_edit` (including F8 multi-file atomic proposals), authentication, and common cross-tool requirements. |
| 1.1 | 2026-08-23 | Claude Code | Coverage audit: added §9.9 (Indexing & Chunking, `IDX`) to give the previously-untraced `_iter_chunks`/`build_index` behavior its own requirement IDs; reworked §16 RTM into an index pointing at inline `# BRD:` traceability comments now present in every `tests/test_*.py` test function; added OI-7..OI-10 for coverage gaps found during the audit (counters never asserted, the primary vault-symlink branch never exercised, `get_overview`'s exact heading/separator format never asserted, wholesale-reindex-clears-stale-rows never proven). No requirement's *content* changed — this revision only adds requirements and corrects traceability claims. |
| 1.2 | 2026-08-23 | Claude Code | Resolved the `search` result-count discrepancy (RISK-1/OI-1): `server.py`'s docstring and `README.md` now say 10, matching the actual `LIMIT` and `FR-SRCH-2` — no runtime behavior changed. Added `NFR-PROP-10`, the Prometheus-counter requirement for `propose_edit` that was missing despite the counter existing in code since v1.1; updated §13's source reference accordingly. Added §9.10 Vault Path Blacklist (`BLK`, FR-BLK-1..5, NFR-BLK-1..3), a **not-yet-implemented** operator-requested capability to exclude configured vault subdirectories from `search` and `read_note`; flagged its interaction with `propose_edit` (deliberately out of scope) as OI-11 rather than resolving it unilaterally. |
| 1.3 | 2026-08-23 | Claude Code | Resolved OI-11 per operator follow-up: `propose_edit` now SHALL honor `VAULT_BLACKLIST` too (FR-BLK-5 rewritten from "explicitly out of scope" to a requirement). Directed enforcement into the `_resolve_in_vault` helper shared by `read_note` and `propose_edit` (NFR-BLK-3 rewritten) rather than adding a second, independent check — same behavior, one implementation instead of two that could drift apart. |
| 1.4 | 2026-08-23 | Claude Code | Resolved every remaining open issue (OI-2 through OI-10): added `read_note`'s `READ_MAX_CHARS` truncation cap (FR-READ-4, NFR-READ-2 rewritten from a "gap" callout to a positive requirement); added a non-blocking `flock` lock to `scripts/apply_proposals.py` guarding the whole run (RISK-7 resolved); added `tests/test_auth.py` covering `BearerAuthMiddleware` end-to-end against a real RSA-signed JWT (RISK-8 resolved) plus a smoke test pinning the `/mcp` mount path; added a `note` test section (FR-NOTE-1..5); added delta-based Prometheus counter tests for every tool; added tests for the previously-unexercised primary `VAULT_PATH/vault` branch (`read_note` and `build_index` each have their own copy of that fallback); added an exact-format `get_overview` test; added a test proving `build_index`'s wholesale rebuild actually clears a prior run's rows. §16 RTM rewritten again to reflect the new coverage state. 69 tests now pass, up from 39 in v1.0. |

### Approval

| Role | Name | Date | Signature |
|---|---|---|---|
| Product Owner | *(repository owner)* | | |
| Technical Reviewer | | | |

This is a solo-maintainer, self-hosted personal project rather than an enterprise program; the approval block is retained for structural completeness and to leave a record of intentional trade-off ownership if the project ever grows beyond a single maintainer.

---

## 1. Executive Summary

SecondBrain MCP is a self-hosted [Model Context Protocol](https://modelcontextprotocol.io) (MCP) server that gives the Claude mobile and desktop apps read, keyword-search, and gated-write access to a personal Obsidian-format knowledge vault, without exposing a generic filesystem interface and without replicating the vault's contents off the operator's own infrastructure.

The service is deliberately minimal: five MCP tools, a SQLite FTS5 keyword index, and OAuth 2.1/PKCE authentication delegated to a self-hosted Dex instance. This document formalizes the business and product requirements behind that design and states them as testable functional (FR) and non-functional (NFR) requirements per tool.

This revision (v1.1.0) adds the fifth tool, `propose_edit` — a gated, human-reviewed pipeline for editing *existing* vault notes, closing a capability gap left by the original four read/create-only tools.

## 2. Business Background & Problem Statement

The operator maintains a personal knowledge base ("vault") as a tree of Markdown files, edited primarily through Obsidian on desktop. Claude on desktop already has filesystem access to this vault via a generic MCP filesystem server. Claude's **mobile app has no local filesystem** — it can only reach tools exposed by a remote MCP server the operator controls.

Two options were considered for mobile access:

1. **Reuse a generic filesystem MCP server**, exposing ~11 tools (read/write/list/move/search/etc.) — the path of least engineering effort.
2. **Build a small, purpose-fit server** exposing only the operations the vault workflow actually needs.

Option 1 was rejected: the generic 11-tool surface costs approximately 10,000 tokens of every session's context before a single query is asked, and exposes write/delete/move operations with no review gate — an unacceptable risk for a vault that also holds financial, health, and career records. Option 2 — this project — costs roughly 3,500 tokens per session (five tools) and adds no capability the vault workflow does not explicitly need.

## 3. Goals & Objectives

| # | Goal | Measure |
|---|---|---|
| G1 | Give Claude mobile read + search access to the vault | `get_overview`, `search`, `read_note` implemented and deployed |
| G2 | Let Claude mobile capture new information without risking existing notes | `note` tool, writes to an outbox, never the live vault |
| G3 | Minimize per-session token overhead versus a generic filesystem MCP server | ≤ ~3.5k tokens/session for tool schemas (vs. ~10k generic) |
| G4 | Keep vault content from being bulk-replicated off the operator's infrastructure | Only bounded, per-call excerpts leave the environment (see §12) |
| G5 | Allow AI-drafted edits to *existing* notes without unreviewed mutation risk | `propose_edit`, gated by human review and a model-free apply step |
| G6 | Run on modest self-hosted hardware | Phase 1a footprint ≈ 80 MB RAM (see `next-steps.md` phase table) |

## 4. Scope

### 4.1 In Scope (this revision, v1.1.0)

- Five MCP tools: `get_overview`, `search`, `read_note`, `note`, `propose_edit`.
- FTS5 (SQLite) keyword search over the vault, chunked at heading boundaries.
- OAuth 2.1 / PKCE authentication via a self-hosted Dex OIDC provider.
- Outbox-mediated writes (`note`, `propose_edit`) delivered to the vault git repository by an independent sidecar (push-sync), never by the MCP server process itself.
- A gated, human-reviewed, model-free pipeline for applying proposed edits (`scripts/apply_proposals.py`, `make proposals` / `make apply-proposals`).
- Operational HTTP endpoints: health check, Prometheus metrics, manual reindex trigger, OAuth protected-resource metadata.

### 4.2 Out of Scope (this revision)

| Item | Why |
|---|---|
| Semantic / embedding-based search (ONNX, sqlite-vec, RRF hybrid) | Deferred to Phase 1b; triggered only if the FTS5 miss-rate metric crosses threshold (§9.4, §15) |
| Vector database (Qdrant), reranking (Ollama) | Phase 2a/2b; triggered by scale or quality thresholds not yet met |
| Multi-user / multi-tenant access control | Current deployment model is single-operator; see RISK-6 |
| Non-Obsidian vault formats | Vault is assumed to be a Markdown tree with Obsidian conventions (wikilinks, `_map.md`, `context.md`) |
| Non-Dex identity providers | Auth is delegated wholesale to one self-hosted Dex instance |
| Deleting or moving existing notes via any tool | No tool in this service can delete or rename vault content; `propose_edit` can only transform existing text in place |
| Direct vault mutation by the MCP server process | All mutation is mediated by outbox + sidecar (`note`) or outbox + human-run script (`propose_edit`) |
| Real-time collaboration / concurrent-editor conflict resolution beyond `git apply --3way`'s own drift detection | Out of scope; see RISK-7 |

## 5. Stakeholders & Roles

| Role | Who | Interest |
|---|---|---|
| Product Owner / Operator | The vault's owner, who also self-hosts and maintains the service | Wants mobile access without compromising vault integrity or privacy |
| End User | Same person, acting through the Claude mobile/desktop app | Wants fast, low-friction recall and capture of personal notes |
| System Administrator / SRE | Same person, wearing an operations hat | Wants the service to run unattended on modest hardware with clear failure signals |
| Upstream platform | Anthropic (Claude.ai, Claude mobile/desktop apps) | Defines the MCP protocol and OAuth discovery contract this server must satisfy |
| Identity provider | Self-hosted Dex instance | Issues and signs the JWTs this server validates |

In this project the first three rows are the same individual; the roles are kept distinct in this document because the requirements each role cares about are genuinely different (product fit vs. UX vs. operability), and separating them keeps the requirements traceable if the project ever gains a second maintainer.

## 6. Assumptions & Constraints

- **A1.** The vault is a single Obsidian-format Markdown tree, version-controlled in a single git repository, with an existing `_map.md` and `context.md` at its root.
- **A2.** The operator has one shared Claude subscription (Pro-tier or similar) covering Claude Code, Claude.ai chat, and Cowork; no `ANTHROPIC_API_KEY` is used, so there is no separate API-billed usage pool. This directly informs NFR-PROP-5 and the retracted "quota savings" rationale recorded in `next-steps.md`.
- **A3.** The deployment target is a small self-hosted Kubernetes cluster (or Docker Compose for local dev), not a managed cloud platform.
- **A4.** Cloudflare (or an equivalent edge proxy) sits in front of the public Dex hostname and blocks in-cluster requests to it, which is why `DEX_JWKS_URI` must point at an in-cluster address rather than relying on OIDC discovery (NFR-AUTH-3).
- **A5.** There is exactly one authenticated principal in practice; the system does not need per-note authorization (see NFR-AUTH-7, RISK-6).
- **C1 (constraint).** `readOnlyRootFilesystem: true` is set on the server's Kubernetes pod; the server process may write only to `DB_PATH`, `OUTBOX_PATH`, and `/tmp`.
- **C2 (constraint).** The server container image must not contain a `git` binary or shell out to one (NFR-COM-3, NFR-PROP-1) — this keeps the blast radius of a server-process compromise to "read the vault mirror, write to an outbox," not "push to the vault's git history."
- **C3 (constraint).** Claude's mobile app UI cannot accept a manually-entered static bearer token, so OAuth 2.1 with PKCE is mandatory, not merely preferred (NFR-AUTH-4).

## 7. Glossary

| Term | Meaning |
|---|---|
| MCP | Model Context Protocol — the JSON-RPC-based protocol Claude clients use to discover and call tools on a remote server |
| Vault | The Obsidian-format Markdown tree this service reads from and proposes edits to |
| Effective vault root | `VAULT_PATH/vault` if that path exists (the git-sync symlink target), else `VAULT_PATH` itself |
| Chunk | A contiguous span of one note's text between two H1–H3 headings, the unit indexed by FTS5 |
| FTS5 | SQLite's built-in full-text search virtual table module, used here with `porter unicode61` tokenization |
| Outbox | A local, writable directory (`OUTBOX_PATH`) where `note` and `propose_edit` stage artifacts for an independent sidecar to pick up |
| git-sync | Read-side sidecar (official `registry.k8s.io/git-sync` image) that mirrors the vault git repo into a volume the server reads from |
| push-sync | Write-side sidecar (this repo, `sidecars/`) that watches the outbox, commits its contents to the vault git repo, and pushes |
| Proposal | A `Proposals/*.patch.md` artifact emitted by `propose_edit`: a rationale plus a git-format diff, awaiting human review and out-of-band application |
| Dex | Self-hosted OIDC identity provider this service delegates authentication to |
| PKCE | Proof Key for Code Exchange — the OAuth 2.1 extension required for public (non-confidential) clients like a mobile app |
| RS256 | The asymmetric JWT signing algorithm this server requires (rejects any other `alg`) |

## 8. System Context & Architecture Overview

```
Claude Mobile / Desktop
  │ OAuth 2.1 / PKCE
  ▼
Dex (OIDC authorization server) ──► upstream IdP (GitHub / Google)
  │ issues JWT
  ▼
secondbrain-mcp (this server)
  │ reads                    │ writes to outbox
  ▼                          ▼
vault volume (read-only)   outbox volume
  ▲                          │
git-sync sidecar        push-sync sidecar ──► routes *.patch.md → Proposals/, else → Inbox/
  │                          │
  └────────── vault git repository ──────────┘ ◄── also edited directly via desktop Obsidian
                    │
                    ▼ (out of band, human/cron-triggered, zero model tokens)
          scripts/apply_proposals.py  (git apply --3way, check-then-apply)
```

Component responsibilities are strictly separated by design (this separation is itself a requirement — see NFR-COM-3, NFR-PROP-1, NFR-PROP-5):

| Component | Responsibility | May write to the vault git repo? |
|---|---|---|
| `server.py` (this repo) | Serve MCP tools + auth + FTS5 index over HTTP | No |
| git-sync sidecar | Mirror the vault repo into a read-only volume | No (it *is* the source of the mirror, but pulls only) |
| push-sync sidecar | Commit/push outbox contents | Yes — the only in-cluster component that pushes |
| `scripts/apply_proposals.py` | Apply reviewed proposal diffs to a local vault clone | Yes, but runs on the operator's machine/cron, not in-cluster |

## 9. Functional & Non-Functional Requirements

### 9.1 Numbering Convention

Each requirement has a stable ID of the form `FR-<AREA>-<n>` or `NFR-<AREA>-<n>`. `propose_edit` requirements additionally carry their original ID from the source vault design note (`F1`–`F8`, `N1`–`N9`) in parentheses for traceability, since that note predates this document and is referenced from `next-steps.md`. Priority uses MoSCoW (Must / Should / Could). Status reflects the state of this codebase as of v1.1.0, not aspiration.

### 9.2 Common / Cross-Tool Requirements (`COM`)

**Functional**

| ID | Requirement | Priority | Status |
|---|---|---|---|
| FR-COM-1 | Every tool argument that names a vault path SHALL be resolved strictly inside the effective vault root; traversal (`..`) and symlink escape SHALL be rejected. | Must | Implemented |
| FR-COM-2 | Every tool SHALL return a plain UTF-8 string for both success and failure outcomes; no tool SHALL raise an unhandled exception to the MCP client. | Must | Implemented |
| FR-COM-3 | Write-path tools (`note`, `propose_edit`) SHALL write only to `OUTBOX_PATH`. No tool SHALL write to `VAULT_PATH` or invoke `git`. | Must | Implemented |
| FR-COM-4 | The effective vault root SHALL be `VAULT_PATH/vault` when that path exists, else `VAULT_PATH` itself. | Must | Implemented |

**Non-Functional**

| ID | Requirement | Priority | Status |
|---|---|---|---|
| NFR-COM-1 | The server SHALL expose no more than five MCP tools at a time; adding a sixth requires a deliberate, documented design decision, since each tool definition costs ~250 tokens of every session's context and token minimization is this project's core value proposition (§2, G3). | Must | Implemented (`agents.md` hard rule) |
| NFR-COM-2 | `server.py` SHALL write only to `DB_PATH`, `OUTBOX_PATH`, and `/tmp`, remaining compatible with `readOnlyRootFilesystem: true`. | Must | Implemented |
| NFR-COM-3 | `server.py` SHALL contain no `git` subprocess calls or git library usage. | Must | Implemented |
| NFR-COM-4 | Every tool call SHALL increment a dedicated Prometheus counter `mcp_<tool>_total`, scraped from `/metrics` without authentication. | Must | Implemented |
| NFR-COM-5 | Read-path tools SHALL reflect the vault state as of the last successful reindex. Worst-case staleness ≈ git-sync pull interval (5 min) + vault-watcher poll interval (30 s) ≈ 5.5 minutes; near-zero after a manual `POST /reindex`. | Should | Implemented |

### 9.3 `get_overview()` (`OVW`)

**Functional**

| ID | Requirement | Priority | Status |
|---|---|---|---|
| FR-OVW-1 | The tool SHALL take no arguments and return the concatenated contents of `context.md` and `_map.md` from the effective vault root. | Must | Implemented |
| FR-OVW-2 | Each included file SHALL be preceded by a `## <filename>` heading; when both are present, sections SHALL be joined with `\n\n---\n\n`. | Must | Implemented |
| FR-OVW-3 | If only one file exists, only that file's section SHALL be returned. | Must | Implemented |
| FR-OVW-4 | If neither file exists, the tool SHALL return the literal string `"Vault unavailable."` and MUST NOT raise. | Must | Implemented |

**Non-Functional**

| ID | Requirement | Priority | Status |
|---|---|---|---|
| NFR-OVW-1 | `get_overview` is intended to be called at most once per session; this is a client-side calling convention for token-budget planning, not server-enforced. | Should | Documented convention |
| NFR-OVW-2 | Each call increments `mcp_overviews_total`; response size increments `mcp_overview_chars_total`. | Must | Implemented |
| NFR-OVW-3 | Subject to NFR-COM-5 (freshness bound). | Must | Implemented |

### 9.4 `search(query)` (`SRCH`)

**Functional**

| ID | Requirement | Priority | Status |
|---|---|---|---|
| FR-SRCH-1 | The tool SHALL accept a single free-text `query` string and match it against the FTS5 `chunks_fts` table using `porter unicode61` tokenization. | Must | Implemented |
| FR-SRCH-2 | Matching rows SHALL be ordered by FTS5 `rank` and limited to at most **10** results per call. | Must | Implemented |
| FR-SRCH-3 | Each result SHALL surface the note's vault-relative path, the heading of the containing chunk, and a ~30-token snippet with the match ellipsized (`…`). | Must | Implemented |
| FR-SRCH-4 | If the raw query is not valid FTS5 syntax, the tool SHALL retry once with the query wrapped in double quotes as a literal phrase. | Must | Implemented |
| FR-SRCH-5 | If zero rows match after any retry, the tool SHALL return the literal string `"No results."`. | Must | Implemented |

**Non-Functional**

| ID | Requirement | Priority | Status |
|---|---|---|---|
| NFR-SRCH-1 | `search` SHALL execute entirely against the local SQLite FTS5 index; no network call in the query path. | Must | Implemented |
| NFR-SRCH-2 | Each call increments `mcp_searches_total`; response size increments `mcp_search_chars_total`; a zero-result response additionally increments `mcp_search_misses_total`. | Must | Implemented |
| NFR-SRCH-3 | `mcp_search_misses_total / mcp_searches_total` is the designated trigger metric for the Phase 1b hybrid-search decision (alert threshold: >20% miss rate over a rolling 7 days). | Must | Implemented (metric); Phase 1b itself is out of scope (§4.2) |
| NFR-SRCH-4 | Malformed FTS5 query syntax SHALL NOT raise an unhandled `sqlite3.OperationalError` to the client. | Must | Implemented |
| NFR-SRCH-5 | Subject to NFR-COM-5 (freshness bound). | Must | Implemented |

### 9.5 `read_note(path)` (`READ`)

**Functional**

| ID | Requirement | Priority | Status |
|---|---|---|---|
| FR-READ-1 | The tool SHALL accept a single vault-relative `path` and return the full raw text of that file. | Must | Implemented |
| FR-READ-2 | An out-of-bounds path (per FR-COM-1) SHALL return `"Access denied: {path}"`. | Must | Implemented |
| FR-READ-3 | An in-bounds path that does not exist SHALL return `"Not found: {path}"`. | Must | Implemented |
| FR-READ-4 | Responses SHALL be capped at `READ_MAX_CHARS` (20,000) characters. Content beyond the cap SHALL be truncated with an explicit `\n\n...(truncated, {N} bytes total)` marker appended — never silently — where `{N}` is the full file's UTF-8-encoded byte length. No pagination is offered; a truncated read has no way to fetch the remainder. | Must | Implemented (resolved in document v1.4 — see OI-2) |

**Non-Functional**

| ID | Requirement | Priority | Status |
|---|---|---|---|
| NFR-READ-1 | Each call increments `mcp_reads_total`; response size increments `mcp_read_chars_total`. | Must | Implemented |
| NFR-READ-2 | The size cap in FR-READ-4 exists specifically to bound one call's contribution to a session's token budget — protecting NFR-COM-1's token-minimization goal from a single oversized note, not from `read_note` usage in aggregate. | Should | Implemented |
| NFR-READ-3 | Subject to NFR-COM-5 (freshness bound). | Must | Implemented |

### 9.6 `note(title, content)` (`NOTE`)

**Functional**

| ID | Requirement | Priority | Status |
|---|---|---|---|
| FR-NOTE-1 | The tool SHALL accept `title` and `content` strings and write `# {title}\n\n{content}\n` to a file in `OUTBOX_PATH`. | Must | Implemented |
| FR-NOTE-2 | The filename SHALL be derived from `title`: strip characters outside `[\w\s-]`, collapse whitespace to single hyphens, truncate to 80 characters, default to `untitled` if empty, append `.md`. | Must | Implemented |
| FR-NOTE-3 | If the computed filename already exists in the outbox, the tool SHALL append a `-{YYYYMMDD-HHMMSS}` suffix rather than overwrite. | Must | Implemented |
| FR-NOTE-4 | The tool SHALL NOT write to `VAULT_PATH` or the vault git repository directly (FR-COM-3); push-sync commits the file under `NOTE_INBOX/` (default `Inbox/`). | Must | Implemented |
| FR-NOTE-5 | The tool SHALL return `"Saved to inbox: {filename}"` with the actual (possibly suffixed) filename. | Must | Implemented |

**Non-Functional**

| ID | Requirement | Priority | Status |
|---|---|---|---|
| NFR-NOTE-1 | The outbox → git handoff is asynchronous: push-sync polls every `PUSH_SYNC_INTERVAL` seconds (default 10s). A note is not guaranteed to be in vault git history the instant the tool call returns. | Must | Implemented |
| NFR-NOTE-2 | Each call increments `mcp_notes_total`. | Must | Implemented |
| NFR-NOTE-3 | `OUTBOX_PATH` SHALL be a writable volume distinct from the read-only application root. | Must | Implemented (K8s manifest responsibility) |
| NFR-NOTE-4 | Unlike `propose_edit`, repeated `note` calls with the same title intentionally produce separate timestamped files, not a deduplicated update — each call is a new draft. | Must (by design) | Implemented |

### 9.7 `propose_edit(edits, rationale)` (`PROP`)

This is the most recently added, and most heavily specified, tool. Its requirements originate from a dedicated design note (F1–F8 functional, N1–N7 non-functional) drafted before implementation began; N8 and N9 were added *during* implementation after two real correctness defects were found and fixed. Original IDs are shown in parentheses.

**Functional**

| ID | Requirement | Priority | Status |
|---|---|---|---|
| FR-PROP-1 (F1) | Signature SHALL be `propose_edit(edits: list[{path, old, new}], rationale: str)`. Edits sharing a `path` SHALL apply to that note in the given order. | Must | Implemented |
| FR-PROP-2 (F2) | For each edit, `old` SHALL match the note's *current* content exactly once; zero or multiple matches SHALL fail the entire proposal (see FR-PROP-8) rather than apply ambiguously. | Must | Implemented |
| FR-PROP-3 (F3) | The tool SHALL emit one git-format unified diff per changed file (`diff --git`, `index` line, unified hunks), concatenated into one artifact when more than one file changed. | Must | Implemented |
| FR-PROP-4 (F4) | The artifact SHALL be written to `OUTBOX_PATH` as `<slug>-<digest>.patch.md` (rationale header + fenced ` ```diff ` block); push-sync SHALL route `*.patch.md` to `PROPOSALS_DIR` (default `Proposals/`) instead of `NOTE_INBOX`. | Must | Implemented |
| FR-PROP-5 (F5) | Review/apply SHALL happen out of band via `make proposals` (dry-run) and `make apply-proposals` (real apply), both wrapping `scripts/apply_proposals.py`. | Must | Implemented |
| FR-PROP-6 (F6) | If any target path does not already exist, the tool SHALL fail with a message directing the caller to `note`, never silently creating the file. | Must | Implemented |
| FR-PROP-7 (F7) | The artifact filename SHALL be a deterministic hash of `(changed relative paths, resulting content)`; a byte-identical repeat call SHALL return `"Already proposed (unchanged): {filename}"` instead of duplicating. | Must | Implemented |
| FR-PROP-8 (F8) | Edits spanning multiple paths in one call SHALL be reviewed and applied as one coherent, atomic unit — every changed file is written, or none are. | Must | **Implemented in this revision** |

**Non-Functional**

| ID | Requirement | Priority | Status |
|---|---|---|---|
| NFR-PROP-1 (N1) | `server.py` SHALL contain no git subprocess calls or git library usage; diffing is a pure function of `(current content, edits)` via `difflib`. | Must | Implemented |
| NFR-PROP-2 (N2) | No step in this pipeline SHALL mutate the live vault tree or perform a destructive revert from within the MCP server process. | Must | Implemented |
| NFR-PROP-3 (N3) | The diff SHALL apply cleanly via `git apply --3way` when its target region is unchanged since drafting, and SHALL be rejected cleanly (non-zero exit, no mutation, no conflict markers) — never silently merged — when the target region has drifted. *Refined by NFR-PROP-9.* | Must | Implemented |
| NFR-PROP-4 (N4) | Token cost SHALL be bounded to one tool definition (~250 tokens/session); the outbox → push-sync transport is reused verbatim. | Must | Implemented |
| NFR-PROP-5 (N5) | Applying a proposal SHALL consume zero model tokens — a plain script invocation, never a reasoning turn. `agents.md` codifies this as a hard rule. | Must | Implemented |
| NFR-PROP-6 (N6) | All target paths SHALL be resolved per FR-COM-1 (traversal/symlink-safe). | Must | Implemented |
| NFR-PROP-7 (N7) | No full-vault replication or additional off-box copy SHALL be introduced by this feature. | Must | Implemented |
| NFR-PROP-8 (N8, new) | Multi-file atomicity (FR-PROP-8) SHALL be enforced at the application level: `apply_proposals.py` SHALL always run a full-patch dry-run `check()` before `apply_one()`, and skip the real apply entirely on any check failure. `git apply` itself does **not** guarantee cross-file atomicity within one patch — verified: a bare `git apply --3way` on a patch with one drifted file among several mutates the earlier, non-drifted files before failing on the later one. | Must | Implemented; regression-tested |
| NFR-PROP-9 (N9, new) | The diff's `index` line SHALL use a dummy `0000000..0000000` blob pair, never a real git blob hash. A real hash lets `git apply --3way` locate the historical blob and attempt a genuine content merge on drift — verified this silently writes `<<<<<<<` conflict markers into the note while `--check` reports success (false-clean). The dummy hash forces plain context matching, trading 3-way merge resilience for safety. | Must | Implemented; regression-tested |
| NFR-PROP-10 (new) | Each call SHALL increment a dedicated Prometheus counter `mcp_propose_edits_total`, consistent with every other tool's NFR-COM-4 instance (NFR-OVW-2, NFR-SRCH-2, NFR-READ-1, NFR-NOTE-2). This requirement was missing from document v1.0/v1.1 despite the counter already existing in code since `propose_edit` was first built — added here to close that documentation gap, not to change behavior. | Must | Implemented (counter has existed since v1.1; test coverage added in v1.4) |

### 9.8 Authentication (`AUTH`)

**Functional**

| ID | Requirement | Priority | Status |
|---|---|---|---|
| FR-AUTH-1 | Every HTTP request to a path not in the public allowlist SHALL require an `Authorization: Bearer <JWT>` header. | Must | Implemented |
| FR-AUTH-2 | The public allowlist SHALL always include `/health`, `/metrics`, `/reindex`, and `/.well-known/oauth-protected-resource`; operators MAY extend it (local dev only) via the comma-separated `AUTH_PUBLIC_EXTRA` env var. | Must | Implemented |
| FR-AUTH-3 | Bearer tokens SHALL be validated as RS256 JWTs with `audience == MCP_CLIENT_ID` and `issuer == DEX_ISSUER`, using the signing key resolved from `DEX_JWKS_URI`. | Must | Implemented |
| FR-AUTH-4 | A missing/malformed `Authorization` header SHALL yield `401` with a `WWW-Authenticate` header containing `Bearer realm="<MCP_BASE_URL>"` and `resource_metadata="<MCP_BASE_URL>/.well-known/oauth-protected-resource"`. | Must | Implemented |
| FR-AUTH-5 | A present-but-invalid token SHALL yield `401` with body `{"error": "invalid token"}`, without echoing token contents or validation internals. | Must | Implemented |
| FR-AUTH-6 | `GET /.well-known/oauth-protected-resource` SHALL return `{"resource", "authorization_servers", "bearer_methods_supported"}` and SHALL itself remain unauthenticated. | Must | Implemented |

**Non-Functional**

| ID | Requirement | Priority | Status |
|---|---|---|---|
| NFR-AUTH-1 | The server SHALL NOT implement its own credential store, session mechanism, or password handling; identity is wholly delegated to Dex. | Must | Implemented |
| NFR-AUTH-2 | JWKS signing keys SHALL be cached in-process (`cache_keys=True`); a Dex key rotation is only picked up on the next process restart. Documented limitation, not a defect. | Must | Implemented (documented in `agents.md`) |
| NFR-AUTH-3 | OIDC discovery SHALL be skipped entirely; `DEX_JWKS_URI` SHALL point directly at the in-cluster JWKS endpoint, because the deployment's edge network blocks in-cluster requests to the public Dex hostname (A4). | Must | Implemented |
| NFR-AUTH-4 | Only OAuth 2.1 with PKCE SHALL be supported for the Claude.ai client; static long-lived bearer tokens are out of scope (C3). | Must | Implemented |
| NFR-AUTH-5 | Any path not explicitly in `AUTH_PUBLIC` SHALL default to requiring authentication (allowlist, not denylist). | Must | Implemented |
| NFR-AUTH-6 | Authentication failures SHALL be logged with enough context to debug (path, truncated Authorization-header prefix) but SHALL NOT log full tokens. | Must | Implemented |
| NFR-AUTH-7 | **Gap:** the system implements authentication (who you are) but no per-note or per-tool authorization (what you may touch); any principal with a valid `MCP_CLIENT_ID`-audienced token has full read/propose access to the entire vault. Acceptable under the current single-user model (A5). | Should (for current scale) | Not implemented — see RISK-6 |

### 9.9 Indexing & Chunking (`IDX`)

Added in this revision (v1.1 of this document): `_iter_chunks` and `build_index` had dedicated test coverage from the start but no corresponding requirement IDs until this coverage audit. They underpin `search` (FR-SRCH-1, FR-SRCH-3) rather than being independently invoked by any MCP tool, so they get their own subsection instead of being folded into `SRCH`.

**Functional**

| ID | Requirement | Priority | Status |
|---|---|---|---|
| FR-IDX-1 | Each note SHALL be split into chunks at H1–H3 markdown heading boundaries (`^#{1,3} `); a chunk's heading label SHALL be the nearest preceding heading, or empty for content before the first heading. | Must | Implemented |
| FR-IDX-2 | A chunk's body SHALL include the heading line that introduces it (the chunk starts at the heading itself, not the line after it). | Must | Implemented |
| FR-IDX-3 | Headings of level H4 or deeper SHALL NOT be treated as chunk boundaries; they remain part of the enclosing chunk's body. | Must | Implemented |
| FR-IDX-4 | Notes under any directory literally named `Chat Archive` SHALL be excluded from indexing (they remain readable via `read_note`/`propose_edit` — see §10). | Must | Implemented |
| FR-IDX-5 | Re-indexing SHALL be wholesale (drop and rebuild the FTS5 table from a full vault re-scan), not incremental. | Must | Implemented (regression-tested as of v1.4 — see OI-10) |

### 9.10 Vault Path Blacklist (`BLK`)

Added in document v1.2, proposed by the operator: today, `Chat Archive` directories are the only excluded content, and that exclusion only applies to indexing (FR-IDX-4) — `read_note` and `propose_edit` can still read anything under `Chat Archive`, per §10's existing note that "indexing exclusion is not an access-control boundary." This section specifies a general, operator-configured blacklist that closes that gap for a configurable set of subdirectories, for `search`, `read_note`, and `propose_edit`. **Not yet implemented** — this is a requirements-only addition in this revision, scoped and written to be built against.

**Functional**

| ID | Requirement | Priority | Status |
|---|---|---|---|
| FR-BLK-1 | The server SHALL support an operator-configured list of vault-relative directory prefixes — proposed as a comma-separated `VAULT_BLACKLIST` environment variable, mirroring the existing `AUTH_PUBLIC_EXTRA` convention (FR-AUTH-2) — that are excluded from indexing, `read_note`, and `propose_edit`. | Must | Not implemented — proposed |
| FR-BLK-2 | `search` SHALL NOT return excerpts from any note under a blacklisted prefix. Enforcement SHALL happen at index-build time (the note is never indexed), the same mechanism `FR-IDX-4` already uses for `Chat Archive` — `VAULT_BLACKLIST` is additive to, not a replacement for, the existing hardcoded `Chat Archive` exclusion. | Must | Not implemented — proposed |
| FR-BLK-3 | `read_note` SHALL return `"Access denied: {path}"` — the same response `FR-READ-2` already uses for an out-of-bounds path — for any in-bounds path under a blacklisted prefix, rather than the file's content. Reusing that exact message is deliberate: a blacklisted path and a genuinely out-of-bounds path SHOULD be indistinguishable to the caller. | Must | Not implemented — proposed |
| FR-BLK-4 | Blacklist entries SHALL be matched as a path-segment prefix against the note's path relative to the effective vault root — e.g. an entry of `Health/Psychology` excludes everything under `Health/Psychology/`, but SHALL NOT exclude a sibling like `Health/PsychologyNotes.md`. | Must | Not implemented — proposed |
| FR-BLK-5 | `propose_edit` SHALL also honor the blacklist: a blacklisted path SHALL be treated as out-of-bounds by the same shared path-resolution step `read_note` and `propose_edit` already both call (`_resolve_in_vault`, FR-COM-1), returning `"Access denied: {path}"` — consistent with FR-BLK-3, and *not* fully proposable as an earlier draft of this requirement had it. See NFR-BLK-3 for why this belongs in the shared helper rather than duplicated per tool. | Must | Not implemented — proposed |

**Non-Functional**

| ID | Requirement | Priority | Status |
|---|---|---|---|
| NFR-BLK-1 | Blacklist configuration changes SHALL take effect on the next reindex, consistent with the existing freshness bound (NFR-COM-5) — no separate config-reload mechanism is required since reindexing already runs on a schedule and on `POST /reindex`. | Should | Not implemented — proposed |
| NFR-BLK-2 | An empty or unset `VAULT_BLACKLIST` SHALL be exactly equivalent to today's behavior (only the hardcoded `Chat Archive` exclusion applies) — the feature SHALL be backward compatible by default. | Must | Not implemented — proposed |
| NFR-BLK-3 | Blacklist filtering SHALL be implemented as an extension of `_resolve_in_vault` itself (the function backing FR-COM-1), applied *after* the existing traversal-safe path resolution succeeds — never as a replacement for it, and never in a way that weakens FR-COM-1's traversal/symlink-escape guarantee. Placing it in the shared helper, rather than duplicating a check inside `read_note` and `propose_edit` separately, is what makes FR-BLK-5 fall out for free instead of needing its own independent enforcement path that could drift out of sync with FR-BLK-3. | Must | Not implemented — proposed |

## 10. Data Requirements

| Data | Location | Format | Notes |
|---|---|---|---|
| Vault notes | Effective vault root, recursive | Markdown, UTF-8 (decoded with `errors="replace"`) | Directories named `Chat Archive` are excluded from the FTS5 index but remain readable via `read_note`/`propose_edit` — indexing exclusion is not an access-control boundary |
| FTS5 index | `DB_PATH` (SQLite file) | `chunks_fts(path UNINDEXED, heading, body)`, `porter unicode61` tokenizer | Rebuilt wholesale (`DROP` + `CREATE` + full re-scan) on every (re)index; not incremental |
| Outbox artifacts | `OUTBOX_PATH` | `*.md` (notes) or `*.patch.md` (proposals) | Transient — removed from the outbox once push-sync has committed and pushed them |
| Proposals queue | `Proposals/` in the vault git repo | `*.patch.md`: rationale header + fenced git diff | Removed by `scripts/apply_proposals.py` on successful apply; left in place (never partially consumed) when stale |

## 11. Interface Requirements

### 11.1 HTTP / REST Endpoints

| Path | Method | Auth | Purpose |
|---|---|---|---|
| `/health` | GET | None | Liveness/readiness probe target |
| `/metrics` | GET | None | Prometheus scrape target (text exposition format) |
| `/reindex` | POST | None (by design — see RISK-3) | Force a synchronous FTS5 rebuild |
| `/.well-known/oauth-protected-resource` | GET | None | OAuth 2.0 Protected Resource Metadata (RFC 9728), enabling client-side OAuth discovery |
| `/mcp` *(exact path is fastmcp-version-dependent — see OI-5)* | POST (+ SSE) | Bearer JWT | The MCP JSON-RPC 2.0 endpoint; multiplexes `initialize`, `tools/list`, `tools/call`, etc. |

### 11.2 MCP Tool-Call Surface

All five tools are invoked through a single transport endpoint using the MCP `tools/call` JSON-RPC method, not as individually routable REST resources. `params.name` selects the tool; `params.arguments` carries its arguments, shaped per §9.3–9.7. Tool results are returned as an MCP content-block array (`{"content": [{"type": "text", "text": "..."}]}`), where the request-specific FR sections above define the semantic contract of the `text` field.

### 11.3 API Versioning Strategy

This service's HTTP surface is a mix of (a) fixed-convention operational endpoints, (b) one spec-mandated well-known path, and (c) a JSON-RPC-multiplexed capability surface — each warrants a different versioning treatment rather than a single blanket `/v1/` prefix:

| Surface | Versioning approach | Rationale |
|---|---|---|
| `/health`, `/metrics` | **Unversioned, stable path forever.** | Kubernetes probes and Prometheus scrape configs expect fixed paths; versioning them would break external tooling on every release for no benefit. |
| `/.well-known/oauth-protected-resource` | **Unversioned, fixed by spec.** | RFC 9728 defines this exact path; it is not this service's to version. |
| `/reindex` | **Unversioned.** | Internal operational trigger, not a public data contract. |
| MCP tool surface (`tools/list` / `tools/call`) | **Versioned per-tool, additively.** Adding a tool (like `propose_edit` in this revision) is a MINOR bump. A breaking change to an existing tool's arguments or return contract would ship as a **new tool name** (e.g. `propose_edit_v2`) rather than mutate the existing contract, so already-deployed clients never silently break. | MCP has no native URL-path versioning; the tool name *is* the addressable unit. |
| This document | **Semantic versioning via the "System / API version documented" field in Document Control.** MAJOR for any breaking tool contract change or tool removal; MINOR for an additive tool or field; PATCH for description/documentation fixes with no behavior change. | Gives operators and reviewers a single number to diff against when the service changes. |

Under this policy: **v1.0.0** denotes the original four-tool Phase 1a service (already deployed per `next-steps.md`); **v1.1.0** — this revision — adds `propose_edit` (including F8) as a strictly additive, non-breaking capability. No existing tool's contract changed.

Separately, the **MCP protocol version** itself (negotiated during the `initialize` handshake, e.g. a dated string such as `2025-06-18`) is orthogonal to this service's own version number and is determined by the installed `fastmcp`/MCP SDK version, not by this document — the two SHOULD NOT be conflated in future revisions.

## 12. Security & Compliance Requirements

This section consolidates and cross-references §9.2 and §9.8; only requirements not already stated there are new.

| ID | Requirement | Priority | Status |
|---|---|---|---|
| NFR-SEC-1 | The system SHALL NOT bulk-replicate vault content off the self-hosted environment; only per-call tool results (bounded by FR-SRCH-2 and, as of document v1.4, FR-READ-4) leave the environment boundary. | Must | Implemented (core privacy claim, §2) |
| NFR-SEC-2 | Secrets (the push-sync SSH deploy key) SHALL be mounted with `defaultMode: 0400`; the default Kubernetes Secret volume mode (`0644`, world-readable) is rejected by SSH and MUST NOT be relied upon. | Must | Implemented (documented gotcha, `agents.md`) |
| NFR-SEC-3 | No secret material SHALL be committed to this repository; `.env.example` SHALL contain placeholders only. | Must | Implemented |
| NFR-SEC-4 | See FR-COM-1 / NFR-PROP-6 for path-traversal and symlink-escape rejection, applied uniformly to every tool that accepts a vault path. | Must | Implemented |
| NFR-SEC-5 | See §9.8 in full for authentication requirements; see NFR-AUTH-7 for the accepted authorization gap. | Must | Implemented (with documented gap) |

## 13. Observability & Monitoring Requirements

| Metric | Type | Source requirement |
|---|---|---|
| `mcp_overviews_total`, `mcp_overview_chars_total` | Counter | NFR-OVW-2 |
| `mcp_searches_total`, `mcp_search_chars_total`, `mcp_search_misses_total` | Counter | NFR-SRCH-2, NFR-SRCH-3 |
| `mcp_reads_total`, `mcp_read_chars_total` | Counter | NFR-READ-1 |
| `mcp_notes_total` | Counter | NFR-NOTE-2 |
| `mcp_propose_edits_total` | Counter | NFR-PROP-10 |

All counters are exposed unauthenticated at `/metrics` (NFR-COM-4) for Prometheus scraping; no dashboards or alerting rules are defined by this document beyond the Phase 1b trigger already specified in `next-steps.md` (NFR-SRCH-3).

## 14. Risk Register

| ID | Risk | Likelihood | Impact | Mitigation / Status |
|---|---|---|---|---|
| RISK-1 | *(Resolved in document v1.2)* `search`'s own docstring/README claimed "top 5" results while the implemented `LIMIT` was 10. | — | — | **Resolved** — docstring (`server.py`) and `README.md` now say 10, matching `FR-SRCH-2` and the actual `LIMIT`. No runtime behavior changed. |
| RISK-2 | *(Resolved in document v1.4)* `read_note` had no size cap; one very large note could consume a disproportionate share of a session's token budget. | — | — | **Resolved** — `read_note` now caps responses at `READ_MAX_CHARS` (20,000 chars) with an explicit truncation marker (FR-READ-4, NFR-READ-2). |
| RISK-3 | `/reindex` is intentionally unauthenticated; if `MCP_BASE_URL` were ever exposed without the existing OAuth-fronted ingress, any anonymous caller could trigger repeated reindex load. | Low | Low (rebuild cost only, no data exposure) | Keep `/reindex` behind the existing ingress; do not expose it as a separate public route |
| RISK-4 | JWKS keys are cached in-process; a Dex signing-key rotation without a coordinated pod restart causes a window of `401`s for every client. | Low (infrequent rotation) | Medium (full-service outage until restart) | Documented operational runbook step in `agents.md` |
| RISK-5 | Multi-file proposal atomicity (FR-PROP-8) depends entirely on `apply_proposals.py`'s check-before-apply discipline, not on `git` itself. A future edit calling `apply_one()` without a preceding `check()` would silently reintroduce partial-apply risk. | Low | High (could corrupt vault notes) | NFR-PROP-8 + regression test `test_multi_file_patch_atomic_when_one_file_drifted`; documented as a hard invariant in `agents.md` |
| RISK-6 | No per-note authorization exists; any authenticated principal can read or propose edits to the entire vault. | N/A under current single-user model | High if the deployment model ever becomes multi-user | Explicitly out of scope (§4.2); revisit if multi-user support is ever pursued |
| RISK-7 | *(Resolved in document v1.4)* Concurrent `apply-proposals` runs were not guarded; two overlapping invocations (e.g. a cron job and a manual run) could interleave `check()`/`apply()` steps across processes. | — | — | **Resolved** — `scripts/apply_proposals.py` now takes an exclusive, non-blocking `flock` on `<repo>/.apply_proposals.lock` for the whole run; a second concurrent invocation exits immediately (code 3) without touching any patch or note (OI-3). |
| RISK-8 | *(Resolved in document v1.4)* The authentication middleware (`BearerAuthMiddleware`, JWT validation, public-path allowlist) had no automated test coverage. | — | — | **Resolved** — `tests/test_auth.py` now covers FR-AUTH-1..6 and NFR-AUTH-5/6 against the real `BearerAuthMiddleware` class, using a generated RSA keypair and a mocked `PyJWKClient` (OI-4). |

## 15. Success Metrics / KPIs & Acceptance Criteria

- **Token budget:** tool-schema overhead SHALL stay ≤ ~3.5k tokens/session (five tools), against a generic-filesystem-MCP baseline of ~10k tokens (G3).
- **Search quality gate:** rolling 7-day `mcp_search_misses_total / mcp_searches_total` SHALL stay ≤ 20%; crossing this threshold is the sole documented trigger for starting Phase 1b work (out of scope for this revision).
- **Acceptance criteria for v1.1.0:** every FR/NFR row in §9.7 (`propose_edit`) and the multi-file addition in particular (FR-PROP-8, NFR-PROP-8, NFR-PROP-9) has a passing automated regression test (see §16); `ruff` reports no new lint findings versus the pre-`propose_edit` baseline; the model-free-apply gate (NFR-PROP-5) is codified in `agents.md`, not merely in this document.

## 16. Requirements Traceability Matrix (RTM)

**As of document v1.1, the fine-grained mapping lives inline in the test files themselves**, as a `# BRD: <ID>[, <ID>...]` comment directly above every `test_*` function in `tests/test_server.py` and `tests/test_apply_proposals.py` — run `grep -n "# BRD:" tests/test_*.py` for the authoritative, line-numbered list. Duplicating that mapping into this table as well was tried in document v1.0 and rejected on the second pass: a hand-maintained copy of test-to-requirement mappings drifts from the actual test suite the moment either changes, silently. This table is instead a coverage *summary*, checked against the inline comments as of this revision.

| Area | IDs with automated coverage | IDs with **no** automated coverage |
|---|---|---|
| `COM` | FR-COM-1, FR-COM-3, FR-COM-4 (both branches, as of v1.4), NFR-COM-4 (as of v1.4) | FR-COM-2 (no test isolates "never raises, always returns str" as its own assertion — implicitly true wherever the full suite passes); NFR-COM-1, NFR-COM-2, NFR-COM-3, NFR-COM-5 (process/deployment properties, not unit-testable in isolation) |
| `IDX` | FR-IDX-1, FR-IDX-2, FR-IDX-3, FR-IDX-4, FR-IDX-5 (as of v1.4) | *(none)* |
| `OVW` | FR-OVW-1, FR-OVW-2 (exact format, as of v1.4), FR-OVW-3, FR-OVW-4, NFR-OVW-2 (as of v1.4) | NFR-OVW-1, NFR-OVW-3 (calling-convention/freshness properties, not unit-testable in isolation) |
| `SRCH` | FR-SRCH-1, FR-SRCH-4, FR-SRCH-5, NFR-SRCH-2 (as of v1.4) | FR-SRCH-2 (exact 10-row limit), FR-SRCH-3 (exact snippet shape) — no test indexes >10 matching notes to exercise the cap; NFR-SRCH-3 (a product-policy statement, not something a unit test asserts) |
| `READ` | FR-READ-1, FR-READ-2, FR-READ-3, FR-READ-4 (as of v1.4), NFR-READ-1 (as of v1.4) | NFR-READ-2, NFR-READ-3 (rationale/freshness statements, not independently testable beyond FR-READ-4's own test) |
| `NOTE` | FR-NOTE-1..5, NFR-NOTE-2, NFR-NOTE-4 (all as of v1.4) | NFR-NOTE-1 (async push-sync handoff timing — would need a push-sync test double), NFR-NOTE-3 (K8s manifest responsibility, not unit-testable) |
| `PROP` | FR-PROP-1, FR-PROP-2, FR-PROP-3, FR-PROP-4, FR-PROP-6, FR-PROP-7, FR-PROP-8, NFR-PROP-2, NFR-PROP-3, NFR-PROP-8, NFR-PROP-9, NFR-PROP-10 (as of v1.4) | NFR-PROP-1, NFR-PROP-4, NFR-PROP-5, NFR-PROP-6, NFR-PROP-7 (process/architecture properties, not unit-testable in isolation) |
| `AUTH` | FR-AUTH-1..6, NFR-AUTH-5, NFR-AUTH-6 (all as of v1.4, `tests/test_auth.py`) | NFR-AUTH-1, NFR-AUTH-2, NFR-AUTH-3, NFR-AUTH-4, NFR-AUTH-7 (deployment/protocol/architecture facts, not unit-testable against this codebase alone) |
| `BLK` | *(none — not yet implemented)* | FR-BLK-1..5, NFR-BLK-1..3 — no code exists yet to test; see §9.10 |

RISK-5's mitigation cites `test_multi_file_patch_atomic_when_one_file_drifted` by name; that reference and the ones in `agents.md`/`next-steps.md` remain accurate as of this revision (verified while writing it, not just carried forward). The `OI-3` fix added `test_main_rejects_concurrent_run_without_touching_anything`, which now grounds RISK-7's resolution the same way.

## 17. Open Issues & Recommendations

| ID | Issue | Recommendation |
|---|---|---|
| OI-1 | *(Resolved in document v1.2)* `search`'s docstring and `README.md` said "top 5"; code returns up to 10. | **Resolved** — updated the docstring and `README.md` to say 10 (kept the existing `LIMIT`, since the token-budget-vs-recall tradeoff of changing it is a separate product decision, not a documentation fix). |
| OI-2 | *(Resolved in document v1.4)* `read_note` had no size cap (NFR-READ-2, RISK-2). | **Resolved** — added `READ_MAX_CHARS = 20_000` and an explicit `"...(truncated, N bytes total)"` marker (FR-READ-4). Regression-tested: `test_read_note_truncates_large_files`, `test_read_note_under_cap_not_truncated`. |
| OI-3 | *(Resolved in document v1.4)* `apply_proposals.py` had no concurrency guard (RISK-7). | **Resolved** — added a non-blocking `flock`-based lock (`_lock()`) covering the whole run; a second concurrent invocation exits with code 3 and touches nothing. Regression-tested: `test_main_rejects_concurrent_run_without_touching_anything`. |
| OI-4 | *(Resolved in document v1.4)* `BearerAuthMiddleware` / JWT validation had zero automated test coverage (RISK-8). | **Resolved** — `tests/test_auth.py` exercises the real middleware class against a minimal test app (not the full `server.app`, to avoid dragging in the FTS5/vault-watcher lifespan): missing/malformed header, wrong signature, wrong audience, wrong issuer, expired token, the public-path allowlist (including `AUTH_PUBLIC_EXTRA`-style extension), and the truncated-header log line. |
| OI-5 | *(Resolved in document v1.4)* The exact MCP transport mount path (referred to in §11.1 as `/mcp`) was not pinned by any test. | **Resolved** — `test_mcp_asgi_mounted_at_expected_path` asserts `/mcp` is among `server.mcp_asgi.routes`; confirmed against the actually-installed `fastmcp` 3.4.7 before writing the assertion, not guessed. |
| OI-6 | *(Resolved in document v1.4)* `note` had no dedicated automated test. | **Resolved** — added a `note` test section covering FR-NOTE-1..5: outbox write + content shape, filename sanitization, the empty-after-sanitization → `untitled` case, the 80-char truncation, and the collision → timestamp-suffix behavior. |
| OI-7 | *(Resolved in document v1.4)* No automated test asserted a Prometheus counter increment. | **Resolved** — added delta-based tests (`Counter._value.get()` before/after) for every counter: `mcp_overviews_total`, `mcp_searches_total` (+ the miss counter), `mcp_reads_total`, `mcp_notes_total`, `mcp_propose_edits_total`, and their `_chars_total` companions where applicable. |
| OI-8 | *(Resolved in document v1.4)* No test exercised the primary `VAULT_PATH/vault` branch (the git-sync symlink target) of the effective-vault-root resolution. | **Resolved** — added `test_read_note_prefers_nested_vault_dir` and `test_build_index_prefers_nested_vault_dir`, each creating a nested `VAULT_PATH/vault/` and confirming *that* path — not the outer one — is what gets read from. |
| OI-9 | *(Resolved in document v1.4)* `get_overview`'s exact `## <filename>` heading and `\n\n---\n\n` separator formatting (FR-OVW-2) was not asserted by any test. | **Resolved** — added `test_get_overview_exact_format`, asserting the full string exactly rather than substring containment; the original weaker test is kept alongside it as a readable smoke test. |
| OI-10 | *(Resolved in document v1.4)* FR-IDX-5 (wholesale, non-incremental reindex) had no test proving a *second* `build_index` call actually clears rows from a prior run. | **Resolved** — added `test_build_index_second_call_clears_stale_rows`: indexes vault A, then vault B into the same DB, and asserts vault A's row is gone, not just uncounted. |
| OI-11 | *(Resolved in document v1.3)* An earlier draft of §9.10 deliberately excluded `propose_edit` from `VAULT_BLACKLIST` enforcement, which would have let a note be simultaneously hidden from `read_note`/`search` yet still editable via `propose_edit`. | **Resolved** — operator confirmed `propose_edit` should also honor the blacklist. FR-BLK-5 now requires it, enforced via the same shared `_resolve_in_vault` helper `read_note` already uses (NFR-BLK-3), so both tools inherit one implementation instead of two that could drift apart. |

## 18. Appendices

### Appendix A — Related Documents

- [`agents.md`](agents.md) — hard rules and non-obvious operational gotchas (token-budget-constrained, kept minimal by design; this document is the expanded, unconstrained counterpart)
- [`README.md`](README.md) — user-facing setup and architecture summary
- [`next-steps.md`](next-steps.md) — phase roadmap, trigger conditions, and the `propose_edit` implementation history (including both correctness fixes referenced in NFR-PROP-8/9)
- The original `propose_edit` design note (vault `Inbox/propose_edit-pipeline---concept-requirements-validation.md`) — the source of the F1–F8/N1–N7 requirement IDs preserved in §9.7

### Appendix B — Out-of-Band Design Decisions Superseded by This Document

None. This is the first BRD issued for this service; all prior requirements existed only as the source design note (Appendix A) and inline code comments.
