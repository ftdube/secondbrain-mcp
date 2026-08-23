import sqlite3
import server


# ── _iter_chunks ──────────────────────────────────────────────────────────────

def test_iter_chunks_empty():
    assert list(server._iter_chunks("note.md", "")) == []


def test_iter_chunks_no_headings():
    assert list(server._iter_chunks("note.md", "plain text")) == [
        ("note.md", "", "plain text")
    ]


def test_iter_chunks_heading_at_start():
    # Body of each chunk includes the heading line itself (prev_pos = heading start).
    chunks = list(server._iter_chunks("note.md", "# A\n\nbody a\n\n## B\n\nbody b"))
    assert chunks == [
        ("note.md", "A", "# A\n\nbody a"),
        ("note.md", "B", "## B\n\nbody b"),
    ]


def test_iter_chunks_content_before_first_heading():
    chunks = list(server._iter_chunks("note.md", "intro\n\n# A\n\nbody"))
    assert chunks[0] == ("note.md", "", "intro")
    assert chunks[1][1] == "A"


def test_iter_chunks_h4_not_a_split_point():
    chunks = list(server._iter_chunks("note.md", "# A\n\n#### ignored\n\nbody"))
    assert len(chunks) == 1
    assert chunks[0][1] == "A"
    assert "#### ignored" in chunks[0][2]


# ── build_index ───────────────────────────────────────────────────────────────

def test_build_index_counts_chunks(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "note.md").write_text("# A\n\nbody a\n\n## B\n\nbody b")
    assert server.build_index(vault, tmp_path / "index.db") == 2


def test_build_index_excludes_chat_archive(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "Chat Archive").mkdir()
    (vault / "Chat Archive" / "chat.md").write_text("# Chat\n\ncontent")
    (vault / "normal.md").write_text("# Normal\n\ncontent")
    assert server.build_index(vault, tmp_path / "index.db") == 1


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


def test_search_returns_matching_note(tmp_path, monkeypatch):
    db = _indexed_db(tmp_path, "# Python\n\nPython is great")
    monkeypatch.setattr(server, "DB_PATH", db)
    assert "note.md" in server.search("Python")


def test_search_no_results(tmp_path, monkeypatch):
    db = _indexed_db(tmp_path, "# Hello\n\nworld")
    monkeypatch.setattr(server, "DB_PATH", db)
    assert server.search("xyzzy_not_found") == "No results."


def test_search_fts_syntax_fallback(tmp_path, monkeypatch):
    # An invalid FTS5 query should not raise — it retries as a quoted phrase.
    db = _indexed_db(tmp_path, "# Hello\n\nworld")
    monkeypatch.setattr(server, "DB_PATH", db)
    result = server.search("AND")
    assert isinstance(result, str)


# ── read_note ─────────────────────────────────────────────────────────────────

def test_read_note_valid(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "note.md").write_text("hello")
    monkeypatch.setattr(server, "VAULT_PATH", vault)
    assert server.read_note("note.md") == "hello"


def test_read_note_not_found(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setattr(server, "VAULT_PATH", vault)
    assert server.read_note("missing.md") == "Not found: missing.md"


def test_read_note_path_traversal_blocked(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setattr(server, "VAULT_PATH", vault)
    assert server.read_note("../../etc/passwd") == "Access denied: ../../etc/passwd"


def test_read_note_nested_path(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    (vault / "sub").mkdir(parents=True)
    (vault / "sub" / "note.md").write_text("nested")
    monkeypatch.setattr(server, "VAULT_PATH", vault)
    assert server.read_note("sub/note.md") == "nested"


# ── get_overview ──────────────────────────────────────────────────────────────

def test_get_overview_both_files(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "context.md").write_text("my context")
    (vault / "_map.md").write_text("my map")
    monkeypatch.setattr(server, "VAULT_PATH", vault)
    result = server.get_overview()
    assert "my context" in result
    assert "my map" in result


def test_get_overview_partial(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "context.md").write_text("only context")
    monkeypatch.setattr(server, "VAULT_PATH", vault)
    result = server.get_overview()
    assert "only context" in result
    assert "my map" not in result


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


def test_propose_edit_writes_proposal(tmp_path, monkeypatch):
    vault, outbox = _propose_setup(tmp_path, monkeypatch)
    (vault / "note.md").write_text("# Note\n\nold text\n")

    result = server.propose_edit("note.md", [{"old": "old text", "new": "new text"}], "fix wording")

    assert result.startswith("Proposed: ")
    files = list(outbox.glob("*.patch.md"))
    assert len(files) == 1
    body = files[0].read_text()
    assert "note.md" in body
    assert "fix wording" in body
    assert "```diff" in body
    assert "-old text" in body
    assert "+new text" in body


def test_propose_edit_anchor_not_found(tmp_path, monkeypatch):
    vault, outbox = _propose_setup(tmp_path, monkeypatch)
    (vault / "note.md").write_text("content")

    result = server.propose_edit("note.md", [{"old": "missing", "new": "x"}], "r")

    assert "not found" in result
    assert list(outbox.glob("*.patch.md")) == []


def test_propose_edit_anchor_ambiguous(tmp_path, monkeypatch):
    vault, outbox = _propose_setup(tmp_path, monkeypatch)
    (vault / "note.md").write_text("dup dup")

    result = server.propose_edit("note.md", [{"old": "dup", "new": "x"}], "r")

    assert "matches 2 times" in result
    assert list(outbox.glob("*.patch.md")) == []


def test_propose_edit_missing_note_routes_to_note_tool(tmp_path, monkeypatch):
    _propose_setup(tmp_path, monkeypatch)

    result = server.propose_edit("missing.md", [{"old": "a", "new": "b"}], "r")

    assert "No such note" in result
    assert "note tool" in result


def test_propose_edit_path_traversal_blocked(tmp_path, monkeypatch):
    _propose_setup(tmp_path, monkeypatch)

    assert server.propose_edit("../../etc/passwd", [{"old": "a", "new": "b"}], "r") == "Access denied: ../../etc/passwd"


def test_propose_edit_no_changes(tmp_path, monkeypatch):
    vault, outbox = _propose_setup(tmp_path, monkeypatch)
    (vault / "note.md").write_text("same")

    result = server.propose_edit("note.md", [{"old": "same", "new": "same"}], "r")

    assert result.startswith("No changes")
    assert list(outbox.glob("*.patch.md")) == []


def test_propose_edit_idempotent(tmp_path, monkeypatch):
    vault, outbox = _propose_setup(tmp_path, monkeypatch)
    (vault / "note.md").write_text("old")

    first = server.propose_edit("note.md", [{"old": "old", "new": "new"}], "r")
    second = server.propose_edit("note.md", [{"old": "old", "new": "new"}], "r")

    assert first.startswith("Proposed: ")
    assert second.startswith("Already proposed")
    assert len(list(outbox.glob("*.patch.md"))) == 1


def test_propose_edit_sequential_edits_applied_in_order(tmp_path, monkeypatch):
    vault, outbox = _propose_setup(tmp_path, monkeypatch)
    (vault / "note.md").write_text("one two\n")

    result = server.propose_edit(
        "note.md",
        [{"old": "one", "new": "1"}, {"old": "two", "new": "2"}],
        "r",
    )

    assert result.startswith("Proposed: ")
    body = next(outbox.glob("*.patch.md")).read_text()
    assert "+1 2" in body
