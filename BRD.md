# Business Requirements Document — SecondBrain MCP Server

## Document Control

| Field | Value |
|---|---|
| Document title | Business Requirements Document — SecondBrain MCP Server |
| Document version | 1.12 (Draft) |
| System / API version documented | 1.3.1 |
| Date | 2026-08-23 |
| Author | Claude Code, on behalf of the repository owner |
| Classification | Public (repository is open-source; see §6 for redaction policy) |
| Related artifacts | [`agents.md`](agents.md), [`RISKS.md`](RISKS.md), [`README.md`](README.md), [`next-steps.md`](next-steps.md), [GitHub Issues](https://github.com/ftdube/secondbrain-mcp/issues) |

### Revision History

| Version | Date | Summary |
|---|---|---|
| 1.0 | 2026-08-23 | Initial issue: Phase 1a tools, `propose_edit`, auth, common requirements. |
| 1.1 | 2026-08-23 | Added §9.9 (IDX). Reworked RTM to point at inline test comments. |
| 1.2 | 2026-08-23 | Resolved RISK-1/OI-1 (search count discrepancy). Proposed §9.10 (BLK), not yet implemented. |
| 1.3 | 2026-08-23 | Resolved OI-11 — `propose_edit` honors the blacklist too. |
| 1.4 | 2026-08-23 | Resolved OI-2..OI-10 (read_note cap, apply lock, auth tests, etc). |
| 1.5 | 2026-08-23 | Added FR-READ-5 (`read_note` pagination), per PR review. |
| 1.6 | 2026-08-23 | Gap audit: OI-12..OI-19, NFR-SEC-6. |
| 1.7 | 2026-08-23 | Implemented §9.10 (BLK). System version → 1.2.0. |
| 1.8 | 2026-08-23 | Fixed RISK-9/OI-20 (blacklist leading-slash bug + branch coverage). |
| 1.9 | 2026-08-23 | Restructure: extracted risk register to `RISKS.md` (was §14); folded RTM (was §16) into a §9.1 traceability requirement; moved Open Issues (was §17) to GitHub Issues. Added the hard rule this revision itself follows — this document states requirements, not a session-by-session log. Full detail for every prior revision lives in git history and PR descriptions, not here. |
| 1.10 | 2026-08-23 | From real-world usage review: added FR-COM-5 (unambiguous `note`-vs-`propose_edit` boundary); reworked FR-PROP-1/2/6 and added FR-PROP-9 to let `propose_edit` create new files atomically within a diff instead of failing; amended FR-PROP-4 to add an informational `Drafted:` timestamp header. Implemented and regression-tested; system version → 1.3.0. |
| 1.11 | 2026-08-23 | Gap audit on the v1.10 work. Found and fixed a real corruption bug: added NFR-PROP-11 — a create-target drifted (independently created) between drafting and applying was silently 3-way-merged with `<<<<<<<` conflict markers written to disk while `check()` reported clean, because a create's `/dev/null` base doesn't need the historical-blob lookup that NFR-PROP-9's dummy hash blocks for edits; fixed in `apply_proposals.py` with an explicit existence pre-check. Also closed traceability gaps: tagged two untagged-but-already-covered tests (FR-NOTE-4, NFR-NOTE-4) and added NFR-COM-4/NFR-SRCH-1/NFR-SRCH-5/NFR-SEC-1..6 to the §9.1 excused list as pre-existing architectural facts. System version → 1.3.1 (bug fix, no tool contract change). |
| 1.12 | 2026-08-25 | Comparative gap audit against the sibling `vault-publisher` repo's BRD (same operator, same self-hosted cluster), requested to check for portable security/monitoring/uptime requirements. Added new §9.11 (OBS): FR-OBS-1 (`/health` readiness signal) and NFR-OBS-1 (reindex-staleness gauge), both Not implemented, tracked as [issue #59](https://github.com/ftdube/secondbrain-mcp/issues/59)/[#60](https://github.com/ftdube/secondbrain-mcp/issues/60); NFR-OBS-2 (RAM bound, Could) tracked as [issue #61](https://github.com/ftdube/secondbrain-mcp/issues/61). Added NFR-SEC-7 (§12) — `git-sync` currently shares `push-sync`'s read-write SSH key (`compose.yaml`, documented in `README.md`), giving the read-only sidecar unnecessary write credentials; Not implemented, tracked as [issue #58](https://github.com/ftdube/secondbrain-mcp/issues/58) and `RISKS.md` RISK-11. No system-version bump — documentation and backlog only, no code changed. |

Detail for versions 1.0–1.8 beyond this one-line summary lives in git history (`git log -- BRD.md`) and the PRs that shipped each change — not duplicated here, per the hard rule this revision introduces.

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

### 4.1 In Scope (system version 1.3.1 — see §11.3 for the version history)

- Five MCP tools: `get_overview`, `search`, `read_note`, `note`, `propose_edit`.
- FTS5 (SQLite) keyword search over the vault, chunked at heading boundaries.
- OAuth 2.1 / PKCE authentication via a self-hosted Dex OIDC provider.
- Outbox-mediated writes (`note`, `propose_edit`) delivered to the vault git repository by an independent sidecar (push-sync), never by the MCP server process itself.
- A gated, human-reviewed, model-free pipeline for applying proposed edits (`scripts/apply_proposals.py`, `make proposals` / `make apply-proposals`).
- Operational HTTP endpoints: health check, Prometheus metrics, manual reindex trigger, OAuth protected-resource metadata.
- An operator-configured `VAULT_BLACKLIST` excluding chosen vault subdirectories from indexing, `read_note`, and `propose_edit` (§9.10).

### 4.2 Out of Scope (system version 1.3.1)

| Item | Why |
|---|---|
| Semantic / embedding-based search (ONNX, sqlite-vec, RRF hybrid) | Deferred to Phase 1b; triggered only if the FTS5 miss-rate metric crosses threshold (§9.4, §14) |
| Vector database (Qdrant), reranking (Ollama) | Phase 2a/2b; triggered by scale or quality thresholds not yet met |
| Multi-user / multi-tenant access control | Current deployment model is single-operator; see `RISKS.md` RISK-6 |
| Non-Obsidian vault formats | Vault is assumed to be a Markdown tree with Obsidian conventions (wikilinks, `_map.md`, `context.md`) |
| Non-Dex identity providers | Auth is delegated wholesale to one self-hosted Dex instance |
| Deleting or moving existing notes via any tool | No tool in this service can delete or rename vault content; `propose_edit` can only transform existing text in place |
| Direct vault mutation by the MCP server process | All mutation is mediated by outbox + sidecar (`note`) or outbox + human-run script (`propose_edit`) |
| Real-time collaboration / concurrent-editor conflict resolution beyond `git apply --3way`'s own drift detection | Out of scope; see `RISKS.md` RISK-7 |

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
- **A5.** There is exactly one authenticated principal in practice; the system does not need per-note authorization (see NFR-AUTH-7, `RISKS.md` RISK-6).
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

Each requirement has a stable ID of the form `FR-<AREA>-<n>` or `NFR-<AREA>-<n>`. `propose_edit` requirements additionally carry their original ID from the source vault design note (`F1`–`F8`, `N1`–`N9`) in parentheses for traceability, since that note predates this document and is referenced from `next-steps.md`. Priority uses MoSCoW (Must / Should / Could). Status reflects the state of this codebase as of the system version in Document Control, not aspiration.

**Traceability requirement.** Every requirement in this section SHALL be traceable to either an inline `# BRD: <ID>[, <ID>...]` comment directly above a `test_*` function in `tests/test_server.py`/`tests/test_apply_proposals.py`/`tests/test_auth.py`, or an explicit note in this document for why it is not independently unit-testable (e.g. an architectural or deployment fact). Run `grep -rn "# BRD:" tests/test_*.py` for the current, authoritative mapping — this is deliberately not duplicated as a table in this document (a hand-maintained copy tried in document v1.0–v1.8 drifted from the actual suite the moment either changed, silently, and added nothing a live `grep` doesn't already answer). A requirement found untraceable and not yet excused becomes a [GitHub Issue](https://github.com/ftdube/secondbrain-mcp/issues), not a row in a BRD table.

As of document v1.12, the following are excused from that requirement as inherent architectural, deployment, or process facts rather than unit-testable behavior — asserting "runs on Kubernetes" or "delegates identity to Dex" isn't something a unit test proves: `NFR-COM-2`, `NFR-COM-3`, `NFR-COM-4` (umbrella statement instantiated, and independently tested, per tool as NFR-OVW-2/NFR-SRCH-2/NFR-READ-1/NFR-NOTE-2/NFR-PROP-10), `NFR-COM-5`, `NFR-OVW-1`, `NFR-OVW-3`, `NFR-SRCH-1` (no-network-call design fact), `NFR-SRCH-3`, `NFR-SRCH-5` (pure cross-reference to NFR-COM-5, same pattern as the already-excused NFR-READ-3), `NFR-READ-2`, `NFR-READ-3`, `NFR-NOTE-1`, `NFR-NOTE-3`, `NFR-PROP-1`, `NFR-PROP-4`, `NFR-PROP-5`, `NFR-PROP-6`, `NFR-PROP-7`, `NFR-AUTH-1`, `NFR-AUTH-3`, `NFR-AUTH-4`, `NFR-AUTH-7`, `NFR-BLK-1`, `NFR-BLK-2`, `NFR-BLK-3`, `NFR-SEC-1`..`NFR-SEC-7` (repo-hygiene/deployment/CI-pipeline facts, or pure cross-references to other requirements — `NFR-SEC-7` added document v1.12: credential provisioning is a K8s Secret/compose config fact, not unit-testable code behavior), `NFR-OBS-2` (added document v1.12: a live RAM ceiling requires a resource probe, not a unit test). This list exists so a future audit doesn't spend time re-deriving which NFRs fall in this bucket, or re-flagging one as a gap (three prior audits, in document v1.1, v1.6, and v1.11, each spent real effort re-examining this exact question) — remove an ID from it only when it becomes independently testable, not on a recurring review cadence.

`FR-OBS-1` and `NFR-OBS-1` (§9.11, added document v1.12) are deliberately **not** excused — both are ordinary `server.py` logic and SHALL get regression tests once implemented (tracked by their GitHub issues, not yet by a test since the code doesn't exist yet).

### 9.2 Common / Cross-Tool Requirements (`COM`)

**Functional**

| ID | Requirement | Priority | Status |
|---|---|---|---|
| FR-COM-1 | Every tool argument that names a vault path SHALL be resolved strictly inside the effective vault root; traversal (`..`) and symlink escape SHALL be rejected. | Must | Implemented |
| FR-COM-2 | Every tool SHALL return a plain UTF-8 string for both success and failure outcomes; no tool SHALL raise an unhandled exception to the MCP client. | Must | Implemented |
| FR-COM-3 | Write-path tools (`note`, `propose_edit`) SHALL write only to `OUTBOX_PATH`. No tool SHALL write to `VAULT_PATH` or invoke `git`. | Must | Implemented |
| FR-COM-4 | The effective vault root SHALL be `VAULT_PATH/vault` when that path exists, else `VAULT_PATH` itself. | Must | Implemented |
| FR-COM-5 (new, document v1.10) | `note` and `propose_edit` SHALL have mutually exclusive, unambiguous purposes stated in their tool descriptions, so the calling model has a single deciding test rather than a judgment call. **`note`** is for content not yet bound to a specific vault location — a capture, observation, or draft a human will triage and file later; the caller does not need to know, or commit to, where it belongs. **`propose_edit`** is for a deliberate, structured change to the vault's existing organization — edits to specific, already-identified note(s), and/or new note(s) at specific paths following the vault's existing conventions (FR-PROP-6) — expressed as a precise, reviewable diff. The test: if the caller can name the exact target path(s) and write the precise content without guessing, use `propose_edit`; if not, use `note`. | Must | Implemented — both tool docstrings state the boundary; see FR-PROP-6/9 for the mechanism that makes `propose_edit` capable of the "new note at a specific path" half of this test |

**Non-Functional**

| ID | Requirement | Priority | Status |
|---|---|---|---|
| NFR-COM-1 | The server SHALL expose no more than five MCP tools at a time; adding a sixth requires a deliberate, documented design decision, since each tool definition costs ~250 tokens of every session's context and token minimization is this project's core value proposition (§2, G3). | Must | Implemented (`agents.md` hard rule; regression-tested as of v1.6 — `test_exactly_five_tools_registered`) |
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
| FR-READ-4 | Responses SHALL be capped at `READ_MAX_CHARS` (20,000) characters per call. Content beyond the cap SHALL be truncated with an explicit marker appended — never silently — stating the full file's UTF-8-encoded byte size. Per FR-READ-5, the marker SHALL also state the offset to pass on the next call to continue reading. | Must | Implemented (resolved in document v1.4 — see OI-2) |
| FR-READ-5 (new, document v1.5) | `read_note` SHALL accept an optional `offset` integer parameter (default `0`), a **character** offset into the note's content — not a byte offset, since Python string slicing is always code-point-safe while a raw byte offset could split a multi-byte UTF-8 sequence. The response SHALL be up to `READ_MAX_CHARS` characters starting at `offset`. `offset < 0` SHALL be clamped to `0` rather than erroring (FR-COM-2). An `offset` at or beyond the content's length SHALL return an empty string, signaling "nothing more to read," not an error. | Must | Implemented |

**Non-Functional**

| ID | Requirement | Priority | Status |
|---|---|---|---|
| NFR-READ-1 | Each call increments `mcp_reads_total`; response size increments `mcp_read_chars_total`. | Must | Implemented |
| NFR-READ-2 | The size cap in FR-READ-4 exists specifically to bound one call's contribution to a session's token budget — protecting NFR-COM-1's token-minimization goal from a single oversized note, not from `read_note` usage in aggregate. | Should | Implemented |
| NFR-READ-3 | Subject to NFR-COM-5 (freshness bound). | Must | Implemented |

### 9.6 `note(title, content)` (`NOTE`)

Scope boundary with `propose_edit`: see FR-COM-5.

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

This is the most recently added, and most heavily specified, tool. Its requirements originate from a dedicated design note (F1–F8 functional, N1–N7 non-functional) drafted before implementation began; N8 and N9 were added *during* implementation after two real correctness defects were found and fixed. Original IDs are shown in parentheses. Scope boundary with `note`: see FR-COM-5.

**Functional**

| ID | Requirement | Priority | Status |
|---|---|---|---|
| FR-PROP-1 (F1) | Signature SHALL be `propose_edit(edits: list[{path, old, new}], rationale: str)`, where `old` is optional (defaults to `""`). Edits sharing a `path` SHALL apply to that note in the given order, with the first edit's starting content being the file's real current content if it exists, else `""` (see FR-PROP-6). | Must | Implemented; regression-tested |
| FR-PROP-2 (F2) | For each edit, `old` SHALL match the note's *current* content exactly once; zero or multiple matches SHALL fail the entire proposal (see FR-PROP-8) rather than apply ambiguously. (For a newly-created path per FR-PROP-6, current content starts as `""`, against which an omitted/empty `old` trivially matches once — no special-casing needed, this is the same rule.) | Must | Implemented |
| FR-PROP-3 (F3) | The tool SHALL emit one git-format unified diff per changed file (`diff --git`, `index` line, unified hunks), concatenated into one artifact when more than one file changed. | Must | Implemented |
| FR-PROP-4 (F4) | The artifact SHALL be written to `OUTBOX_PATH` as `<slug>-<digest>.patch.md` (a header containing `Drafted: {UTC timestamp}` and the rationale, followed by a fenced ` ```diff ` block); push-sync SHALL route `*.patch.md` to `PROPOSALS_DIR` (default `Proposals/`) instead of `NOTE_INBOX`. The timestamp is informational only (lets a human reviewer see how stale a pending proposal is) — it is never read back or used for staleness detection; drift detection is entirely `git apply --3way`'s content-matching (NFR-PROP-3). | Must | Implemented; regression-tested |
| FR-PROP-5 (F5) | Review/apply SHALL happen out of band via `make proposals` (dry-run) and `make apply-proposals` (real apply), both wrapping `scripts/apply_proposals.py`. | Must | Implemented |
| FR-PROP-6 (F6) | If a target path does not exist, the tool SHALL create it, but only if that path's first edit omits `old` (or passes `old=""`); the file's starting content is treated as `""` for FR-PROP-2's matching. If the first edit for a nonexistent path supplies a non-empty `old`, the tool SHALL fail loudly (content that specific can't legitimately match a file that isn't there) rather than silently doing nothing. Creation is still subject to FR-COM-1 (traversal/symlink-safe resolution) and the blacklist (NFR-BLK-3) like any other target path. | Must | Implemented; regression-tested (supersedes the v1.9 behavior of unconditionally failing and directing the caller to `note`; see FR-COM-5 for the now-explicit `note`-vs-`propose_edit` boundary that replaces that blanket redirect) |
| FR-PROP-7 (F7) | The artifact filename SHALL be a deterministic hash of `(changed relative paths, resulting content)`; a byte-identical repeat call SHALL return `"Already proposed (unchanged): {filename}"` instead of duplicating. | Must | Implemented |
| FR-PROP-8 (F8) | Edits spanning multiple paths in one call SHALL be reviewed and applied as one coherent, atomic unit — every changed or newly-created file is written, or none are. | Must | Implemented; regression-tested |
| FR-PROP-9 (new, document v1.10) | For a newly-created path (FR-PROP-6), the emitted diff SHALL use git's standard new-file headers — `new file mode 100644`, `--- /dev/null`, `+++ b/<path>` — rather than the two-sided header FR-PROP-3 describes for edits to existing files, so `git apply --3way` treats it as a creation rather than attempting to match context against a file that doesn't exist. | Must | Implemented; verified `git apply --3way --check`/apply accept this header format for a fresh file (empirical scratch-repo test) |

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
| NFR-PROP-11 (new, document v1.11) | For a create (FR-PROP-6/FR-PROP-9), `apply_proposals.py` SHALL reject a create-target that already exists on disk as drift, before the patch is ever handed to `git`. NFR-PROP-9's dummy-hash protection does **not** by itself extend to creates: a create's base is declared directly as `/dev/null` in the diff text rather than resolved via the index line's blob hash, so `git apply --3way` can always reconstruct an empty base and perform a genuine 3-way merge regardless of the dummy hash. Found in the post-implementation gap audit: without this guard, applying a proposal against an independently-created target silently wrote `<<<<<<<` conflict markers into the file on disk while `check()` reported it clean — the exact false-clean failure mode NFR-PROP-9 exists to prevent, now reopened for creates specifically. Verified against a real git repo before and after the fix. | Must | Implemented; regression-tested (`test_check_stale_when_create_target_already_exists`, `test_drifted_create_apply_never_writes_conflict_markers`) |

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
| NFR-AUTH-2 | JWKS signing keys SHALL be cached in-process (`cache_keys=True`); a Dex key rotation is only picked up on the next process restart. Documented limitation, not a defect. | Must | Implemented (documented in `agents.md`; caching mechanism regression-tested as of v1.6 — `test_jwks_client_is_cached_across_calls`) |
| NFR-AUTH-3 | OIDC discovery SHALL be skipped entirely; `DEX_JWKS_URI` SHALL point directly at the in-cluster JWKS endpoint, because the deployment's edge network blocks in-cluster requests to the public Dex hostname (A4). | Must | Implemented |
| NFR-AUTH-4 | Only OAuth 2.1 with PKCE SHALL be supported for the Claude.ai client; static long-lived bearer tokens are out of scope (C3). | Must | Implemented |
| NFR-AUTH-5 | Any path not explicitly in `AUTH_PUBLIC` SHALL default to requiring authentication (allowlist, not denylist). | Must | Implemented |
| NFR-AUTH-6 | Authentication failures SHALL be logged with enough context to debug (path, truncated Authorization-header prefix) but SHALL NOT log full tokens. | Must | Implemented |
| NFR-AUTH-7 | **Gap:** the system implements authentication (who you are) but no per-note or per-tool authorization (what you may touch); any principal with a valid `MCP_CLIENT_ID`-audienced token has full read/propose access to the entire vault. Acceptable under the current single-user model (A5). | Should (for current scale) | Not implemented — see `RISKS.md` RISK-6 |

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

Added as a requirements-only proposal in document v1.2; **implemented in document v1.7.** Before this, `Chat Archive` directories were the only excluded content, and that exclusion only applied to indexing (FR-IDX-4) — `read_note` and `propose_edit` could still read anything under `Chat Archive`, per §10's note that "indexing exclusion is not an access-control boundary." This section specifies a general, operator-configured blacklist that closes that gap for a configurable set of subdirectories, for `search`, `read_note`, and `propose_edit`.

**Functional**

| ID | Requirement | Priority | Status |
|---|---|---|---|
| FR-BLK-1 | The server SHALL support an operator-configured list of vault-relative directory prefixes — proposed as a comma-separated `VAULT_BLACKLIST` environment variable, mirroring the existing `AUTH_PUBLIC_EXTRA` convention (FR-AUTH-2) — that are excluded from indexing, `read_note`, and `propose_edit`. Entries SHALL have any leading `/` stripped before matching, since entries are relative by definition and a leading slash would otherwise silently match nothing (found and fixed same-day as the initial implementation — see `next-steps.md`). | Must | Implemented — `_parse_blacklist`; regression-tested: `test_parse_blacklist_strips_leading_slashes` |
| FR-BLK-2 | `search` SHALL NOT return excerpts from any note under a blacklisted prefix. Enforcement SHALL happen at index-build time (the note is never indexed), the same mechanism `FR-IDX-4` already uses for `Chat Archive` — `VAULT_BLACKLIST` is additive to, not a replacement for, the existing hardcoded `Chat Archive` exclusion. | Must | Implemented |
| FR-BLK-3 | `read_note` SHALL return `"Access denied: {path}"` — the same response `FR-READ-2` already uses for an out-of-bounds path — for any in-bounds path under a blacklisted prefix, rather than the file's content. Reusing that exact message is deliberate: a blacklisted path and a genuinely out-of-bounds path SHOULD be indistinguishable to the caller. | Must | Implemented |
| FR-BLK-4 | Blacklist entries SHALL be matched as a path-segment prefix against the note's path relative to the effective vault root — e.g. an entry of `Health/Psychology` excludes everything under `Health/Psychology/`, but SHALL NOT exclude a sibling like `Health/PsychologyNotes.md`. | Must | Implemented |
| FR-BLK-5 | `propose_edit` SHALL also honor the blacklist: a blacklisted path SHALL be treated as out-of-bounds by the same shared path-resolution step `read_note` and `propose_edit` already both call (`_resolve_in_vault`, FR-COM-1), returning `"Access denied: {path}"` — consistent with FR-BLK-3, and *not* fully proposable as an earlier draft of this requirement had it. See NFR-BLK-3 for why this belongs in the shared helper rather than duplicated per tool. | Must | Implemented — falls out of NFR-BLK-3's implementation, no `propose_edit`-specific code needed |

**Non-Functional**

| ID | Requirement | Priority | Status |
|---|---|---|---|
| NFR-BLK-1 | Blacklist configuration changes SHALL take effect on the next reindex, consistent with the existing freshness bound (NFR-COM-5) — no separate config-reload mechanism is required since reindexing already runs on a schedule and on `POST /reindex`. | Should | Implemented (holds by construction: `VAULT_BLACKLIST` is a module-level constant read once at process start, same as `AUTH_PUBLIC_EXTRA`) |
| NFR-BLK-2 | An empty or unset `VAULT_BLACKLIST` SHALL be exactly equivalent to today's behavior (only the hardcoded `Chat Archive` exclusion applies) — the feature SHALL be backward compatible by default. | Must | Implemented — the full pre-existing test suite (74 tests) passes unchanged with `VAULT_BLACKLIST` unset |
| NFR-BLK-3 | Blacklist filtering SHALL be implemented as an extension of `_resolve_in_vault` itself (the function backing FR-COM-1), applied *after* the existing traversal-safe path resolution succeeds — never as a replacement for it, and never in a way that weakens FR-COM-1's traversal/symlink-escape guarantee. Placing it in the shared helper, rather than duplicating a check inside `read_note` and `propose_edit` separately, is what makes FR-BLK-5 fall out for free instead of needing its own independent enforcement path that could drift out of sync with FR-BLK-3. | Must | Implemented exactly as specified — see `_resolve_in_vault` in `server.py` |

### 9.11 Observability & Operational Health (OBS)

Added in document v1.12, following a comparative gap audit against the sibling `vault-publisher` repo's BRD (same operator, same self-hosted RPi5 cluster) — see revision history. None of this section is implemented yet; each row is tracked by a GitHub issue rather than left as an unowned aspiration.

**Functional**

| ID | Requirement | Priority | Status |
|---|---|---|---|
| FR-OBS-1 | `GET /health` SHALL report, in addition to bare process liveness, whether at least one index build has completed successfully since process start (e.g. an `"indexed": true\|false` field alongside the existing `"status": "ok"`), so a Kubernetes readinessProbe distinct from a liveness probe can withhold traffic during the pre-first-index-build window rather than routing `search`/`read_note` calls against an empty index. Mirrors `vault-publisher` BRD.md §13's readiness/liveness split, added there specifically to gate its own pre-first-build window (its RISK-2). | Should | Not implemented — see [issue #59](https://github.com/ftdube/secondbrain-mcp/issues/59), `RISKS.md` RISK-12 |

**Non-Functional**

| ID | Requirement | Priority | Status |
|---|---|---|---|
| NFR-OBS-1 | The server SHALL expose a gauge metric (e.g. `mcp_last_reindex_timestamp_seconds`) recording the Unix timestamp of the last successful index build, so an abnormally large gap (git-sync outage, expired deploy key, vault-watcher crash) is visible to Prometheus/alerting rather than silently degrading `NFR-COM-5`'s freshness bound indefinitely — the same proactive-alert pattern `NFR-SRCH-3` already uses for search miss-rate. | Should | Not implemented — see [issue #60](https://github.com/ftdube/secondbrain-mcp/issues/60), `RISKS.md` RISK-13 |
| NFR-OBS-2 | Idle resident RAM SHOULD stay under 150 MB and peak RAM during a full reindex SHOULD stay under 500 MB — headroom around `G6`'s ~80 MB observed target, not a change to it. The Kubernetes Deployment SHOULD declare matching `resources.requests`/`resources.limits` once this service's own manifests exist, so an unbounded pod cannot starve neighbors on the same constrained cluster (compare `vault-publisher` BRD.md NFR-POLL-1/NFR-BUILD-1, motivated by the same RPi5 4GB cluster and its prior real starvation problem, §2 there). | Could | Not implemented — see [issue #61](https://github.com/ftdube/secondbrain-mcp/issues/61), `RISKS.md` RISK-14 |

## 10. Data Requirements

| Data | Location | Format | Notes |
|---|---|---|---|
| Vault notes | Effective vault root, recursive | Markdown, UTF-8 (decoded with `errors="replace"`) | Directories named `Chat Archive` are excluded from the FTS5 index only — still readable via `read_note`/`propose_edit`. `VAULT_BLACKLIST` entries (§9.10) are excluded from *both* indexing and `read_note`/`propose_edit` — an actual access-control boundary, not just an indexing exclusion |
| FTS5 index | `DB_PATH` (SQLite file) | `chunks_fts(path UNINDEXED, heading, body)`, `porter unicode61` tokenizer | Rebuilt wholesale (`DROP` + `CREATE` + full re-scan) on every (re)index; not incremental |
| Outbox artifacts | `OUTBOX_PATH` | `*.md` (notes) or `*.patch.md` (proposals) | Transient — removed from the outbox once push-sync has committed and pushed them |
| Proposals queue | `Proposals/` in the vault git repo | `*.patch.md`: rationale header + fenced git diff | Removed by `scripts/apply_proposals.py` on successful apply; left in place (never partially consumed) when stale |

## 11. Interface Requirements

### 11.1 HTTP / REST Endpoints

| Path | Method | Auth | Purpose |
|---|---|---|---|
| `/health` | GET | None | Liveness/readiness probe target |
| `/metrics` | GET | None | Prometheus scrape target (text exposition format) |
| `/reindex` | POST | None (by design — see `RISKS.md` RISK-3) | Force a synchronous FTS5 rebuild |
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

Under this policy: **v1.0.0** denotes the original four-tool Phase 1a service (already deployed per `next-steps.md`); **v1.1.0** adds `propose_edit` (including F8) as a strictly additive, non-breaking capability; **v1.2.0** adds `VAULT_BLACKLIST` (§9.10), also additive and non-breaking (NFR-BLK-2: unset is exactly prior behavior); **v1.3.0** lets `propose_edit` create new files (FR-PROP-6/9), additive; **v1.3.1** — current — is a bug fix only (NFR-PROP-11), no tool contract change. No existing tool's contract changed in any of these bumps. §9.11's new requirements (document v1.12) are not yet implemented and have not moved this number.

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
| NFR-SEC-6 (new, document v1.6) | CI SHALL run a filesystem vulnerability scan (currently `aquasecurity/trivy-action`) on every push and pull request, failing the build on any `CRITICAL` or `HIGH` severity finding; the `build` and `build-push-sync` image-publish jobs SHALL depend on this scan passing. This control existed in `.github/workflows/ci.yml` since before this document's first issue but was never itself documented as a requirement — found during the v1.6 gap audit. | Must | Implemented (`.github/workflows/ci.yml` `scan` job) — undocumented until now |
| NFR-SEC-7 (new, document v1.12) | The `git-sync` sidecar (read side, §8) SHALL use a credential scoped to read-only repository access, distinct from `push-sync`'s read-write deploy key; the two SHALL NOT share key material. Found during a comparative gap audit against `vault-publisher`'s `NFR-SEC-2` (its git-sync sidecar has no push access at all, by design, specifically to narrow blast radius on compromise): `compose.yaml` currently mounts one identical SSH key into both `git-sync` and `push-sync` via a shared YAML anchor (`x-ssh-key`), documented as intentional in `README.md`. If that key carries push rights, as it must for `push-sync` to function, `git-sync` unnecessarily holds write-capable credentials on disk even though §8's component table already states it never pushes (it "*is* the source of the mirror, but pulls only"). | Must | Implemented (PR #62 separates the keys via `GITSYNC_SSH_KEY_PATH` and provides generation instructions). Tracked as [issue #58](https://github.com/ftdube/secondbrain-mcp/issues/58), `RISKS.md` RISK-11 |

## 13. Observability & Monitoring Requirements

| Metric | Type | Source requirement |
|---|---|---|
| `mcp_overviews_total`, `mcp_overview_chars_total` | Counter | NFR-OVW-2 |
| `mcp_searches_total`, `mcp_search_chars_total`, `mcp_search_misses_total` | Counter | NFR-SRCH-2, NFR-SRCH-3 |
| `mcp_reads_total`, `mcp_read_chars_total` | Counter | NFR-READ-1 |
| `mcp_notes_total` | Counter | NFR-NOTE-2 |
| `mcp_propose_edits_total` | Counter | NFR-PROP-10 |
| `mcp_last_reindex_timestamp_seconds` | Gauge | NFR-OBS-1 *(§9.11, not yet implemented — [issue #60](https://github.com/ftdube/secondbrain-mcp/issues/60))* |

All counters are exposed unauthenticated at `/metrics` (NFR-COM-4) for Prometheus scraping; no dashboards or alerting rules are defined by this document beyond the Phase 1b trigger already specified in `next-steps.md` (NFR-SRCH-3). `/health`'s planned readiness signal (FR-OBS-1, §9.11) is a separate, non-metric mechanism intended for K8s probe wiring, not Prometheus.

## 14. Success Metrics / KPIs & Acceptance Criteria

- **Token budget:** tool-schema overhead SHALL stay ≤ ~3.5k tokens/session (five tools), against a generic-filesystem-MCP baseline of ~10k tokens (G3).
- **Search quality gate:** rolling 7-day `mcp_search_misses_total / mcp_searches_total` SHALL stay ≤ 20%; crossing this threshold is the sole documented trigger for starting Phase 1b work (out of scope for this revision).
- **Acceptance criteria for v1.1.0:** every FR/NFR row in §9.7 (`propose_edit`) and the multi-file addition in particular (FR-PROP-8, NFR-PROP-8, NFR-PROP-9) has a passing automated regression test (§9.1's traceability requirement); `ruff` reports no new lint findings versus the pre-`propose_edit` baseline; the model-free-apply gate (NFR-PROP-5) is codified in `agents.md`, not merely in this document.

## 15. Appendices

### Appendix A — Related Documents

- [`agents.md`](agents.md) — hard rules and non-obvious operational gotchas (token-budget-constrained, kept minimal by design; this document is the expanded, unconstrained counterpart)
- [`RISKS.md`](RISKS.md) — risk register (extracted from this document's former §14 in v1.9)
- [GitHub Issues](https://github.com/ftdube/secondbrain-mcp/issues) — open gaps and the prioritized backlog (moved out of this document's former §17 in v1.9); resolved gaps are closed issues linked to the PR that fixed them, not deleted
- [`README.md`](README.md) — user-facing setup and architecture summary
- [`next-steps.md`](next-steps.md) — phase roadmap, trigger conditions, and the `propose_edit` implementation history (including both correctness fixes referenced in NFR-PROP-8/9)
- The original `propose_edit` design note (vault `Inbox/propose_edit-pipeline---concept-requirements-validation.md`) — the source of the F1–F8/N1–N7 requirement IDs preserved in §9.7

### Appendix B — Out-of-Band Design Decisions Superseded by This Document

None. This is the first BRD issued for this service; all prior requirements existed only as the source design note (Appendix A) and inline code comments.
