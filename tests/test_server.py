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

# BRD: FR-READ-1 (VAULT_PATH fallback branch only — see BRD.md OI-8 for the untested VAULT_PATH/vault branch)
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


# ── get_overview ──────────────────────────────────────────────────────────────

# BRD: FR-OVW-1, FR-OVW-2 (content presence only — exact heading/separator format not asserted, see BRD.md OI-9)
def test_get_overview_both_files(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "context.md").write_text("my context")
    (vault / "_map.md").write_text("my map")
    monkeypatch.setattr(server, "VAULT_PATH", vault)
    result = server.get_overview()
    assert "my context" in result
    assert "my map" in result


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
