import contextlib
import io
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import apply_proposals

import server  # for _make_diff, reused so the patch format matches what propose_edit emits


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _init_repo(tmp_path: Path, content: str) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "note.md").write_text(content)
    _git(repo, "add", "note.md")
    _git(repo, "commit", "-q", "-m", "initial")
    return repo


def _write_patch(repo: Path, rel_path: str, old: str, new: str, rationale: str = "r") -> Path:
    proposals = repo / "Proposals"
    proposals.mkdir(exist_ok=True)
    diff = server._make_diff(rel_path, old, new)
    patch = proposals / "note-abcd1234.patch.md"
    patch.write_text(f"# Proposed edit: {rel_path}\n\n{rationale}\n\n```diff\n{diff}```\n")
    return patch


def test_extract_diff_reads_fenced_block(tmp_path):
    repo = _init_repo(tmp_path, "old text\n")
    patch = _write_patch(repo, "note.md", "old text\n", "new text\n")
    diff = apply_proposals.extract_diff(patch)
    assert diff.startswith("diff --git")
    assert "-old text" in diff
    assert "+new text" in diff


def test_check_clean_when_note_unchanged(tmp_path):
    repo = _init_repo(tmp_path, "old text\n")
    patch = _write_patch(repo, "note.md", "old text\n", "new text\n")
    assert apply_proposals.check(repo, patch) is True


def test_check_stale_when_note_drifted(tmp_path):
    repo = _init_repo(tmp_path, "old text\n")
    patch = _write_patch(repo, "note.md", "old text\n", "new text\n")
    (repo / "note.md").write_text("something else entirely\n")
    _git(repo, "add", "note.md")
    _git(repo, "commit", "-q", "-m", "drift")
    assert apply_proposals.check(repo, patch) is False


def test_drifted_apply_never_writes_conflict_markers(tmp_path):
    # Regression: a real (non-dummy) index hash lets `git apply --3way` locate
    # the historical blob and silently 3-way-merge, writing <<<<<<< conflict
    # markers into the note while --check still reports success. The dummy
    # 0000000 index hash in server._make_diff must keep this from happening.
    repo = _init_repo(tmp_path, "old text\n")
    patch = _write_patch(repo, "note.md", "old text\n", "new text\n")
    (repo / "note.md").write_text("something else entirely\n")
    _git(repo, "add", "note.md")
    _git(repo, "commit", "-q", "-m", "drift")

    assert apply_proposals.check(repo, patch) is False
    ok, _stderr = apply_proposals.apply_one(repo, patch)
    assert ok is False
    assert (repo / "note.md").read_text() == "something else entirely\n"
    assert "<<<<<<<" not in (repo / "note.md").read_text()


def test_apply_one_updates_file_and_leaves_it_uncommitted(tmp_path):
    repo = _init_repo(tmp_path, "old text\n")
    patch = _write_patch(repo, "note.md", "old text\n", "new text\n")
    ok, _stderr = apply_proposals.apply_one(repo, patch)
    assert ok is True
    assert (repo / "note.md").read_text() == "new text\n"
    status = subprocess.run(["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True, check=False).stdout
    assert "note.md" in status  # modified, not committed


def test_main_apply_deletes_applied_patch(tmp_path):
    repo = _init_repo(tmp_path, "old text\n")
    clean_patch = _write_patch(repo, "note.md", "old text\n", "new text\n")

    argv = sys.argv
    sys.argv = ["apply_proposals.py", "--repo", str(repo), "--apply"]
    try:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = apply_proposals.main()
    finally:
        sys.argv = argv

    assert code == 0
    assert "APPLIED: note-abcd1234.patch.md" in out.getvalue()
    assert not clean_patch.exists()


def test_main_dry_run_reports_stale_without_applying(tmp_path):
    repo = _init_repo(tmp_path, "old text\n")
    stale_patch = _write_patch(repo, "note.md", "old text\n", "new text\n")
    (repo / "note.md").write_text("something else entirely\n")
    _git(repo, "add", "note.md")
    _git(repo, "commit", "-q", "-m", "drift")

    argv = sys.argv
    sys.argv = ["apply_proposals.py", "--repo", str(repo)]
    try:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = apply_proposals.main()
    finally:
        sys.argv = argv

    assert code == 0
    assert "STALE: note-abcd1234.patch.md" in out.getvalue()
    assert stale_patch.exists()
