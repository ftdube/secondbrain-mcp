import sqlite3

import server

# ── _iter_chunks ──────────────────────────────────────────────────────────────

# BRD: FR-IDX-1
def test_iter_chunks_empty():
    assert list(server._iter_chunks("note.md", "")) == []


# BRD: FR-IDX-1
def test_iter_chunks_no_headings():
    assert list(server._iter_chunks("note.md", "plain text")) == [
        ("note.md", "", "plain text")
    ]


# BRD: FR-IDX-1, FR-IDX-2
def test_iter_chunks_heading_at_start():
    # Body of each chunk includes the heading line itself (prev_pos = heading start).
    chunks = list(server._iter_chunks("note.md", "# A\n\nbody a\n\n## B\n\nbody b"))
    assert chunks == [
        ("note.md", "A", "# A\n\nbody a"),
        ("note.md", "B", "## B\n\nbody b"),
    ]


# BRD: FR-IDX-1
def test_iter_chunks_content_before_first_heading():
    chunks = list(server._iter_chunks("note.md", "intro\n\n# A\n\nbody"))
    assert chunks[0] == ("note.md", "", "intro")
    assert chunks[1][1] == "A"


# BRD: FR-IDX-3
def test_iter_chunks_h4_not_a_split_point():
    chunks = list(server._iter_chunks("note.md", "# A\n\n#### ignored\n\nbody"))
    assert len(chunks) == 1
    assert chunks[0][1] == "A"
    assert "#### ignored" in chunks[0][2]


# ── build_index ───────────────────────────────────────────────────────────────

# BRD: FR-IDX-1 (does not cover FR-IDX-5 — see BRD.md OI-10; single call only)
def test_build_index_counts_chunks(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "note.md").write_text("# A\n\nbody a\n\n## B\n\nbody b")
    assert server.build_index(vault, tmp_path / "index.db") == 2


# BRD: FR-IDX-4
def test_build_index_excludes_chat_archive(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "Chat Archive").mkdir()
    (vault / "Chat Archive" / "chat.md").write_text("# Chat\n\ncontent")
    (vault / "normal.md").write_text("# Normal\n\ncontent")
    assert server.build_index(vault, tmp_path / "index.db") == 1


# BRD: FR-IDX-1 (empty-vault edge case)
def test_build_index_empty_vault(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    assert server.build_index(vault, tmp_path / "index.db") == 0


# BRD: FR-IDX-5
def test_build_index_second_call_clears_stale_rows(tmp_path):
    db = tmp_path / "index.db"
    vault_a = tmp_path / "vault_a"
    vault_a.mkdir()
    (vault_a / "a.md").write_text("# A\n\ncontent a")
    server.build_index(vault_a, db)

    vault_b = tmp_path / "vault_b"
    vault_b.mkdir()
    (vault_b / "b.md").write_text("# B\n\ncontent b")
    n = server.build_index(vault_b, db)

    conn = sqlite3.connect(db)
    paths = [row[0] for row in conn.execute("SELECT path FROM chunks_fts").fetchall()]
    conn.close()
    assert n == 1
    assert paths == ["b.md"]  # a.md's row from the first call is gone, not just uncounted


# BRD: FR-COM-4 (build_index's own copy of the effective-vault-root fallback)
def test_build_index_prefers_nested_vault_dir(tmp_path):
    mount = tmp_path / "mount"
    nested = mount / "vault"
    nested.mkdir(parents=True)
    (nested / "note.md").write_text("# Inner\n\nbody")
    (mount / "outer.md").write_text("# Outer\n\nbody")  # sibling to vault/, must be ignored

    n = server.build_index(mount, tmp_path / "index.db")
    assert n == 1


# ── search ────────────────────────────────────────────────────────────────────

def _indexed_db(tmp_path, content: str):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "note.md").write_text(content)
    db = tmp_path / "index.db"
    server.build_index(vault, db)
    return db


# BRD: FR-SRCH-1 (does not assert the exact FR-SRCH-2 row limit or FR-SRCH-3 snippet shape — see BRD.md §16)
def test_search_returns_matching_note(tmp_path, monkeypatch):
    db = _indexed_db(tmp_path, "# Python\n\nPython is great")
    monkeypatch.setattr(server, "DB_PATH", db)
    assert "note.md" in server.search("Python")


# BRD: FR-SRCH-5
def test_search_no_results(tmp_path, monkeypatch):
    db = _indexed_db(tmp_path, "# Hello\n\nworld")
    monkeypatch.setattr(server, "DB_PATH", db)
    assert server.search("xyzzy_not_found") == "No results."


# BRD: FR-SRCH-4, NFR-SRCH-4
def test_search_fts_syntax_fallback(tmp_path, monkeypatch):
    # An invalid FTS5 query should not raise — it retries as a quoted phrase.
    db = _indexed_db(tmp_path, "# Hello\n\nworld")
    monkeypatch.setattr(server, "DB_PATH", db)
    result = server.search("AND")
    assert isinstance(result, str)


# ── read_note ─────────────────────────────────────────────────────────────────

# BRD: FR-READ-1 (VAULT_PATH fallback branch — see test_read_note_prefers_nested_vault_dir for the other branch)
def test_read_note_valid(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "note.md").write_text("hello")
    monkeypatch.setattr(server, "VAULT_PATH", vault)
    assert server.read_note("note.md") == "hello"


# BRD: FR-READ-3
def test_read_note_not_found(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setattr(server, "VAULT_PATH", vault)
    assert server.read_note("missing.md") == "Not found: missing.md"


# BRD: FR-COM-1, FR-READ-2
def test_read_note_path_traversal_blocked(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setattr(server, "VAULT_PATH", vault)
    assert server.read_note("../../etc/passwd") == "Access denied: ../../etc/passwd"


# BRD: FR-READ-1
def test_read_note_nested_path(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    (vault / "sub").mkdir(parents=True)
    (vault / "sub" / "note.md").write_text("nested")
    monkeypatch.setattr(server, "VAULT_PATH", vault)
    assert server.read_note("sub/note.md") == "nested"


# BRD: FR-COM-4 (the previously-untested VAULT_PATH/vault branch — mirrors the git-sync symlink target)
def test_read_note_prefers_nested_vault_dir(tmp_path, monkeypatch):
    mount = tmp_path / "mount"
    nested = mount / "vault"
    nested.mkdir(parents=True)
    (nested / "note.md").write_text("nested-root")
    (mount / "note.md").write_text("outer-root")  # must NOT be the one read
    monkeypatch.setattr(server, "VAULT_PATH", mount)
    assert server.read_note("note.md") == "nested-root"


# BRD: FR-READ-4, NFR-READ-2
def test_read_note_truncates_large_files(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir()
    content = "x" * (server.READ_MAX_CHARS + 500)
    (vault / "big.md").write_text(content)
    monkeypatch.setattr(server, "VAULT_PATH", vault)

    result = server.read_note("big.md")

    assert len(result) < len(content)
    assert result.startswith("x" * server.READ_MAX_CHARS)
    assert f"truncated, {len(content.encode())} bytes total" in result


# BRD: FR-READ-1 (below the cap — must not be truncated)
def test_read_note_under_cap_not_truncated(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "small.md").write_text("well under the cap")
    monkeypatch.setattr(server, "VAULT_PATH", vault)
    assert server.read_note("small.md") == "well under the cap"


# BRD: FR-READ-5
def test_read_note_pagination_continues_from_offset(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir()
    content = "a" * server.READ_MAX_CHARS + "b" * 500
    (vault / "big.md").write_text(content)
    monkeypatch.setattr(server, "VAULT_PATH", vault)

    first = server.read_note("big.md")
    assert f"offset={server.READ_MAX_CHARS} to continue" in first

    second = server.read_note("big.md", offset=server.READ_MAX_CHARS)
    assert second == "b" * 500  # no further truncation marker — reached the end


# BRD: FR-READ-5 (offset at or beyond the file's length)
def test_read_note_offset_beyond_length_returns_empty(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "small.md").write_text("short")
    monkeypatch.setattr(server, "VAULT_PATH", vault)
    assert server.read_note("small.md", offset=1000) == ""


# BRD: FR-READ-5 (negative offset is clamped, not an error — FR-COM-2)
def test_read_note_negative_offset_clamped_to_zero(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "small.md").write_text("hello")
    monkeypatch.setattr(server, "VAULT_PATH", vault)
    assert server.read_note("small.md", offset=-5) == "hello"


# ── get_overview ──────────────────────────────────────────────────────────────

# BRD: FR-OVW-1 (content presence — see test_get_overview_exact_format for the precise FR-OVW-2 shape)
def test_get_overview_both_files(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "context.md").write_text("my context")
    (vault / "_map.md").write_text("my map")
    monkeypatch.setattr(server, "VAULT_PATH", vault)
    result = server.get_overview()
    assert "my context" in result
    assert "my map" in result


# BRD: FR-OVW-2
def test_get_overview_exact_format(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "context.md").write_text("my context")
    (vault / "_map.md").write_text("my map")
    monkeypatch.setattr(server, "VAULT_PATH", vault)
    result = server.get_overview()
    assert result == "## context.md\n\nmy context\n\n---\n\n## _map.md\n\nmy map"


# BRD: FR-OVW-3
def test_get_overview_partial(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "context.md").write_text("only context")
    monkeypatch.setattr(server, "VAULT_PATH", vault)
    result = server.get_overview()
    assert "only context" in result
    assert "my map" not in result


# BRD: FR-OVW-4
def test_get_overview_no_files(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setattr(server, "VAULT_PATH", vault)
    assert server.get_overview() == "Vault unavailable."


# ── note ──────────────────────────────────────────────────────────────────────

def _note_setup(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir()
    outbox = tmp_path / "outbox"
    monkeypatch.setattr(server, "VAULT_PATH", vault)
    monkeypatch.setattr(server, "OUTBOX_PATH", outbox)
    return vault, outbox


# BRD: FR-NOTE-1, FR-NOTE-5, FR-COM-3
def test_note_writes_to_outbox(tmp_path, monkeypatch):
    vault, outbox = _note_setup(tmp_path, monkeypatch)

    result = server.note("My Title", "some content")

    assert result == "Saved to inbox: My-Title.md"
    dest = outbox / "My-Title.md"
    assert dest.exists()
    assert dest.read_text() == "# My Title\n\nsome content\n"
    assert list(vault.rglob("*.md")) == []  # never written to the vault itself


# BRD: FR-NOTE-2
def test_note_filename_sanitization(tmp_path, monkeypatch):
    _note_setup(tmp_path, monkeypatch)
    result = server.note("Hello, World! @#$", "x")
    assert result == "Saved to inbox: Hello-World.md"


# BRD: FR-NOTE-2 (empty-after-sanitization edge case)
def test_note_filename_defaults_to_untitled(tmp_path, monkeypatch):
    _note_setup(tmp_path, monkeypatch)
    result = server.note("!!!", "x")
    assert result == "Saved to inbox: untitled.md"


# BRD: FR-NOTE-2 (80-char truncation)
def test_note_filename_truncated_to_80_chars(tmp_path, monkeypatch):
    _vault, outbox = _note_setup(tmp_path, monkeypatch)
    title = "a" * 200
    server.note(title, "x")
    files = list(outbox.glob("*.md"))
    assert len(files) == 1
    assert files[0].stem == "a" * 80


# BRD: FR-NOTE-3
def test_note_collision_appends_timestamp(tmp_path, monkeypatch):
    _vault, outbox = _note_setup(tmp_path, monkeypatch)
    outbox.mkdir(parents=True)
    (outbox / "My-Title.md").write_text("existing draft")

    result = server.note("My Title", "new content")

    assert result != "Saved to inbox: My-Title.md"
    assert result.startswith("Saved to inbox: My-Title-")
    assert (outbox / "My-Title.md").read_text() == "existing draft"  # untouched


# ── propose_edit ──────────────────────────────────────────────────────────────

def _propose_setup(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir()
    outbox = tmp_path / "outbox"
    monkeypatch.setattr(server, "VAULT_PATH", vault)
    monkeypatch.setattr(server, "OUTBOX_PATH", outbox)
    return vault, outbox


# BRD: FR-PROP-1, FR-PROP-3, FR-PROP-4, FR-COM-3
def test_propose_edit_writes_proposal(tmp_path, monkeypatch):
    vault, outbox = _propose_setup(tmp_path, monkeypatch)
    (vault / "note.md").write_text("# Note\n\nold text\n")

    result = server.propose_edit(
        [{"path": "note.md", "old": "old text", "new": "new text"}], "fix wording"
    )

    assert result.startswith("Proposed: ")
    files = list(outbox.glob("*.patch.md"))
    assert len(files) == 1
    body = files[0].read_text()
    assert "note.md" in body
    assert "fix wording" in body
    assert "```diff" in body
    assert "-old text" in body
    assert "+new text" in body


# BRD: FR-PROP-1 (empty-edits guard; not independently itemized in the BRD beyond the signature contract)
def test_propose_edit_no_edits(tmp_path, monkeypatch):
    _propose_setup(tmp_path, monkeypatch)
    assert server.propose_edit([], "r") == "No edits provided."


# BRD: FR-PROP-2
def test_propose_edit_anchor_not_found(tmp_path, monkeypatch):
    vault, outbox = _propose_setup(tmp_path, monkeypatch)
    (vault / "note.md").write_text("content")

    result = server.propose_edit([{"path": "note.md", "old": "missing", "new": "x"}], "r")

    assert "not found" in result
    assert list(outbox.glob("*.patch.md")) == []


# BRD: FR-PROP-2
def test_propose_edit_anchor_ambiguous(tmp_path, monkeypatch):
    vault, outbox = _propose_setup(tmp_path, monkeypatch)
    (vault / "note.md").write_text("dup dup")

    result = server.propose_edit([{"path": "note.md", "old": "dup", "new": "x"}], "r")

    assert "matches 2 times" in result
    assert list(outbox.glob("*.patch.md")) == []


# BRD: FR-PROP-6
def test_propose_edit_missing_note_routes_to_note_tool(tmp_path, monkeypatch):
    _propose_setup(tmp_path, monkeypatch)

    result = server.propose_edit([{"path": "missing.md", "old": "a", "new": "b"}], "r")

    assert "No such note" in result
    assert "note tool" in result


# BRD: FR-COM-1, NFR-PROP-6
def test_propose_edit_path_traversal_blocked(tmp_path, monkeypatch):
    _propose_setup(tmp_path, monkeypatch)

    result = server.propose_edit([{"path": "../../etc/passwd", "old": "a", "new": "b"}], "r")
    assert result == "Access denied: ../../etc/passwd"


# BRD: FR-PROP-2 (old == new no-op; not independently itemized in the BRD)
def test_propose_edit_no_changes(tmp_path, monkeypatch):
    vault, outbox = _propose_setup(tmp_path, monkeypatch)
    (vault / "note.md").write_text("same")

    result = server.propose_edit([{"path": "note.md", "old": "same", "new": "same"}], "r")

    assert result.startswith("No changes")
    assert list(outbox.glob("*.patch.md")) == []


# BRD: FR-PROP-7
def test_propose_edit_idempotent(tmp_path, monkeypatch):
    vault, outbox = _propose_setup(tmp_path, monkeypatch)
    (vault / "note.md").write_text("old")

    edits = [{"path": "note.md", "old": "old", "new": "new"}]
    first = server.propose_edit(edits, "r")
    second = server.propose_edit(edits, "r")

    assert first.startswith("Proposed: ")
    assert second.startswith("Already proposed")
    assert len(list(outbox.glob("*.patch.md"))) == 1


# BRD: FR-PROP-1, FR-PROP-2
def test_propose_edit_sequential_edits_applied_in_order(tmp_path, monkeypatch):
    vault, outbox = _propose_setup(tmp_path, monkeypatch)
    (vault / "note.md").write_text("one two\n")

    result = server.propose_edit(
        [
            {"path": "note.md", "old": "one", "new": "1"},
            {"path": "note.md", "old": "two", "new": "2"},
        ],
        "r",
    )

    assert result.startswith("Proposed: ")
    body = next(outbox.glob("*.patch.md")).read_text()
    assert "+1 2" in body


# ── propose_edit: multi-file (F8) ────────────────────────────────────────────

# BRD: FR-PROP-3, FR-PROP-4, FR-PROP-8
def test_propose_edit_multi_file_writes_one_combined_patch(tmp_path, monkeypatch):
    vault, outbox = _propose_setup(tmp_path, monkeypatch)
    (vault / "a.md").write_text("alpha old\n")
    (vault / "b.md").write_text("beta old\n")

    result = server.propose_edit(
        [
            {"path": "a.md", "old": "alpha old", "new": "alpha new"},
            {"path": "b.md", "old": "beta old", "new": "beta new"},
        ],
        "two-file update",
    )

    assert result.startswith("Proposed: ")
    files = list(outbox.glob("*.patch.md"))
    assert len(files) == 1
    body = files[0].read_text()
    assert body.count("diff --git") == 2
    assert "a.md" in body and "b.md" in body
    assert "+alpha new" in body
    assert "+beta new" in body


# BRD: FR-PROP-2, FR-PROP-8
def test_propose_edit_multi_file_fails_atomically_no_partial_write(tmp_path, monkeypatch):
    vault, outbox = _propose_setup(tmp_path, monkeypatch)
    (vault / "a.md").write_text("alpha old\n")
    (vault / "b.md").write_text("beta old\n")

    result = server.propose_edit(
        [
            {"path": "a.md", "old": "alpha old", "new": "alpha new"},
            {"path": "b.md", "old": "missing anchor", "new": "beta new"},
        ],
        "r",
    )

    assert "Edit 1 for b.md failed" in result
    assert list(outbox.glob("*.patch.md")) == []


# BRD: FR-PROP-8
def test_propose_edit_multi_file_skips_unchanged_files(tmp_path, monkeypatch):
    vault, outbox = _propose_setup(tmp_path, monkeypatch)
    (vault / "a.md").write_text("same\n")
    (vault / "b.md").write_text("beta old\n")

    result = server.propose_edit(
        [
            {"path": "a.md", "old": "same", "new": "same"},
            {"path": "b.md", "old": "beta old", "new": "beta new"},
        ],
        "r",
    )

    assert result.startswith("Proposed: ")
    body = next(outbox.glob("*.patch.md")).read_text()
    assert body.count("diff --git") == 1
    assert "b.md" in body
    assert "a.md" not in body


# ── Prometheus counters (OI-7) ───────────────────────────────────────────────
# Counters are module-level globals shared across the whole test session, so
# every assertion here is delta-based (before/after one call), never absolute.

def _value(counter):
    return counter._value.get()


# BRD: NFR-OVW-2
def test_get_overview_increments_counters(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "context.md").write_text("hi")
    monkeypatch.setattr(server, "VAULT_PATH", vault)

    before_calls, before_chars = _value(server.OVERVIEW_COUNTER), _value(server.OVERVIEW_CHARS)
    result = server.get_overview()

    assert _value(server.OVERVIEW_COUNTER) == before_calls + 1
    assert _value(server.OVERVIEW_CHARS) == before_chars + len(result)


# BRD: NFR-SRCH-2
def test_search_increments_counters(tmp_path, monkeypatch):
    db = _indexed_db(tmp_path, "# Python\n\nPython is great")
    monkeypatch.setattr(server, "DB_PATH", db)

    before_calls, before_chars = _value(server.SEARCH_COUNTER), _value(server.SEARCH_CHARS)
    result = server.search("Python")

    assert _value(server.SEARCH_COUNTER) == before_calls + 1
    assert _value(server.SEARCH_CHARS) == before_chars + len(result)


# BRD: NFR-SRCH-2, NFR-SRCH-3
def test_search_no_results_increments_miss_counter(tmp_path, monkeypatch):
    db = _indexed_db(tmp_path, "# Hello\n\nworld")
    monkeypatch.setattr(server, "DB_PATH", db)

    before = _value(server.SEARCH_MISSES)
    server.search("xyzzy_not_found")

    assert _value(server.SEARCH_MISSES) == before + 1


# BRD: NFR-READ-1
def test_read_note_increments_counters(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "note.md").write_text("hello")
    monkeypatch.setattr(server, "VAULT_PATH", vault)

    before_calls, before_chars = _value(server.READ_COUNTER), _value(server.READ_CHARS)
    result = server.read_note("note.md")

    assert _value(server.READ_COUNTER) == before_calls + 1
    assert _value(server.READ_CHARS) == before_chars + len(result)


# BRD: NFR-NOTE-2
def test_note_increments_counter(tmp_path, monkeypatch):
    _note_setup(tmp_path, monkeypatch)
    before = _value(server.NOTE_COUNTER)
    server.note("t", "c")
    assert _value(server.NOTE_COUNTER) == before + 1


# BRD: NFR-PROP-10
def test_propose_edit_increments_counter(tmp_path, monkeypatch):
    vault, _outbox = _propose_setup(tmp_path, monkeypatch)
    (vault / "note.md").write_text("old\n")
    before = _value(server.PROPOSE_COUNTER)
    server.propose_edit([{"path": "note.md", "old": "old", "new": "new"}], "r")
    assert _value(server.PROPOSE_COUNTER) == before + 1
