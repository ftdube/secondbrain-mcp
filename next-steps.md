# Next Steps

## Phases

| Phase | Stack | RAM | Trigger |
|---|---|---|---|
| **1a** ✅ deployed | FTS5 only | ~80 MB | — |
| 1b | + ONNX MiniLM + sqlite-vec + RRF | ~380 MB | FTS5 misses too many queries |
| 2a | sqlite-vec → Qdrant | ~280 MB + 80 MB | >300 notes or re-embed cost on restart |
| 2b | + Ollama reranker on external PC | ~100 MB + PC | Quality still insufficient |

## Phase 1b trigger monitoring

`mcp_search_misses_total` / `mcp_searches_total` — miss rate over a rolling window.
Alert threshold: >20% miss rate over 7 days → trigger Phase 1b.

Grafana PromQL: `rate(mcp_search_misses_total[7d]) / rate(mcp_searches_total[7d])`

## Phase 1b detail

Add `sqlite-vec`, ONNX `all-MiniLM-L6-v2`, RRF merge, wikilink adjacency table.

## propose_edit tool — ✅ implemented on `feature/propose-edit`, pending merge + real-world validation

5th MCP tool, gated behind human review: drafts a find/replace edit against a note in the read-only vault mirror, emits a git-format diff (no git in server — pure function of current content + edits), and routes it through the existing outbox→push-sync transport into a `Proposals/` queue instead of `Inbox/`. Applied out of band via `scripts/apply_proposals.py` (`git apply --3way`), never by a model in the loop.

Built: `server.py` (`propose_edit`, `_make_diff`), `sidecars/push-sync.sh` + `compose.yaml` (`PROPOSALS_DIR` routing), `scripts/apply_proposals.py`, `Makefile` (`proposals`, `apply-proposals`), `agents.md` gate rule, README, tests (`tests/test_server.py`, `tests/test_apply_proposals.py`).

**Correctness fix found during implementation:** the diff's `index` line must NOT be a real git blob hash. A real hash lets `git apply --3way` locate the historical blob and attempt a genuine content merge on drift — verified this silently writes `<<<<<<<` conflict markers into the note while `--check` reports it clean. Fixed by using a dummy `index 0000000..0000000` line, which forces plain context matching: drift is now rejected cleanly (exit 1, no mutation) instead of merged. Regression-tested in `test_apply_proposals.py::test_drifted_apply_never_writes_conflict_markers`.

**F8 (multi-file atomic proposals) — ✅ implemented.** Signature changed from `propose_edit(path, edits, rationale)` to `propose_edit(edits, rationale)` where each edit is `{path, old, new}`; edits sharing a path apply in order, edits across paths become one combined `Proposals/*.patch.md` with multiple `diff --git` blocks.

**Second correctness fix found while building F8:** `git apply` is NOT atomic across files within one patch — verified a bare `git apply` on a patch with one drifted file among several still mutates the earlier, non-drifted files before failing on the later one. Atomicity for F8 depends entirely on `apply_proposals.main()` always calling `check()` (a full-patch dry run) before `apply_one()` and skipping the apply outright if check fails — never on git's own guarantees. Documented as a hard invariant in `agents.md` and regression-tested in `test_apply_proposals.py::test_multi_file_patch_atomic_when_one_file_drifted`.

**Not yet done:** real end-to-end validation (V2/V3/V5 from the original vault design note) — a live Claude Code session actually running `make apply-proposals` rather than hand-applying, and a real idempotency check against a live push-sync sidecar. Trigger: before relying on this for real vault edits, run through Planned use steps 1-4 once against a scratch vault clone.

Note: the original "saves quota by shifting work to Claude.ai" rationale is retracted — Claude Code, Claude.ai, and Cowork share one subscription usage pool, so a draft-then-integrate split with a model on both ends burns *more* tokens, not less. The actual justification is the human-review gate on AI edits to load-bearing notes, plus mobile-first drafting.

Full original requirements (F1-F8, N1-N7) and validation plan (V1-V7) in vault `Inbox/propose_edit-pipeline---concept-requirements-validation.md`.

## Vault Path Blacklist — ✅ implemented on `feature/vault-blacklist`, pending merge + real-world validation

`VAULT_BLACKLIST` env var (comma-separated vault-relative directory prefixes) excludes matching notes from indexing, `read_note`, and `propose_edit`. Lives entirely inside `_resolve_in_vault`, so `read_note`/`propose_edit` inherit it with zero tool-specific code; `build_index` gets a matching exclusion, additive to the existing `Chat Archive` indexing-only exclusion. Full spec in `BRD.md` §9.10 (FR-BLK-1..5, NFR-BLK-1..3, all now Implemented).

**Bug found and fixed same-day:** a leading slash in an entry (e.g. `/Health/Psychology` instead of `Health/Psychology`) produced `Path("/Health/Psychology").parts == ("/", "Health", "Psychology")`, which would never match a real relative path's parts — a plausible operator typo would silently blacklist nothing. Fixed by stripping leading slashes during parsing (`_parse_blacklist`), regression-tested.

**Not yet done:** real end-to-end validation — mounting an actual vault with a real blacklisted directory (e.g. the Psychology domain, which is already marked read-on-request-only in the vault's own `context.md`) and confirming it's actually unreachable via a live Claude session, not just unit tests against synthetic fixtures. Trigger: before relying on this to actually hide anything, test IRL against a real deployment.

## Housekeeping — extract push-sync to its own repo

Trigger: CI publishing two unrelated images from one repo is messy.
Move `sidecars/` to a standalone `push-sync` repo with its own CI. Reference it from here as an external dependency in the README and compose.yaml.

