import contextlib
import fcntl
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


def _write_create_patch(repo: Path, rel_path: str, new: str, rationale: str = "r") -> Path:
    proposals = repo / "Proposals"
    proposals.mkdir(exist_ok=True)
    diff = server._make_diff(rel_path, "", new, is_new=True)
    patch = proposals / "new-abcd1234.patch.md"
    patch.write_text(f"# Proposed edit: {rel_path}\n\n{rationale}\n\n```diff\n{diff}```\n")
    return patch


def _init_empty_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "seed.md").write_text("seed\n")
    _git(repo, "add", "seed.md")
    _git(repo, "commit", "-q", "-m", "initial")
    return repo


def _init_multi_repo(tmp_path: Path, a_content: str, b_content: str) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "a.md").write_text(a_content)
    (repo / "b.md").write_text(b_content)
    _git(repo, "add", "a.md", "b.md")
    _git(repo, "commit", "-q", "-m", "initial")
    return repo


def _write_multi_patch(repo: Path, files: list[tuple[str, str, str]], rationale: str = "r") -> Path:
    # files: list of (rel_path, old, new)
    proposals = repo / "Proposals"
    proposals.mkdir(exist_ok=True)
    diff = "".join(server._make_diff(rel_path, old, new) for rel_path, old, new in files)
    header = ", ".join(rel_path for rel_path, _old, _new in files)
    patch = proposals / "multi-abcd1234.patch.md"
    patch.write_text(f"# Proposed edit: {header}\n\n{rationale}\n\n```diff\n{diff}```\n")
    return patch


# BRD: FR-PROP-8, NFR-PROP-8
def test_multi_file_patch_applies_both_files(tmp_path):
    repo = _init_multi_repo(tmp_path, "alpha old\n", "beta old\n")
    patch = _write_multi_patch(
        repo, [("a.md", "alpha old\n", "alpha new\n"), ("b.md", "beta old\n", "beta new\n")]
    )
    assert apply_proposals.check(repo, patch) is True
    ok, _stderr = apply_proposals.apply_one(repo, patch)
    assert ok is True
    assert (repo / "a.md").read_text() == "alpha new\n"
    assert (repo / "b.md").read_text() == "beta new\n"


# BRD: FR-PROP-8, NFR-PROP-8 (also the regression test cited by RISK-5's mitigation)
def test_multi_file_patch_atomic_when_one_file_drifted(tmp_path):
    # Regression: git apply is NOT atomic across files in one patch by itself —
    # a bare `git apply` on this patch mutates a.md before failing on b.md.
    # Atomicity here depends entirely on main() calling check() before
    # apply_one() and skipping the apply outright when check fails.
    repo = _init_multi_repo(tmp_path, "alpha old\n", "beta old\n")
    patch = _write_multi_patch(
        repo, [("a.md", "alpha old\n", "alpha new\n"), ("b.md", "beta old\n", "beta new\n")]
    )
    (repo / "b.md").write_text("beta DRIFTED\n")
    _git(repo, "add", "b.md")
    _git(repo, "commit", "-q", "-m", "drift b")

    assert apply_proposals.check(repo, patch) is False

    argv = sys.argv
    sys.argv = ["apply_proposals.py", "--repo", str(repo), "--apply"]
    try:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = apply_proposals.main()
    finally:
        sys.argv = argv

    assert code == 0
    assert "SKIP (stale): multi-abcd1234.patch.md" in out.getvalue()
    assert (repo / "a.md").read_text() == "alpha old\n"  # untouched, not partially applied
    assert (repo / "b.md").read_text() == "beta DRIFTED\n"
    assert patch.exists()


# BRD: FR-PROP-8, FR-PROP-9
def test_mixed_create_and_edit_patch_applies_atomically(tmp_path):
    repo = _init_repo(tmp_path, "old text\n")
    proposals = repo / "Proposals"
    proposals.mkdir(exist_ok=True)
    diff = server._make_diff("note.md", "old text\n", "new text\n") + server._make_diff(
        "sub/new.md", "", "hello\n", is_new=True
    )
    patch = proposals / "mixed-abcd1234.patch.md"
    patch.write_text(f"# Proposed edit: note.md, sub/new.md\n\nr\n\n```diff\n{diff}```\n")

    assert apply_proposals.check(repo, patch) is True
    ok, _stderr = apply_proposals.apply_one(repo, patch)
    assert ok is True
    assert (repo / "note.md").read_text() == "new text\n"
    assert (repo / "sub" / "new.md").read_text() == "hello\n"


# BRD: FR-PROP-4 (parsing counterpart of the artifact format)
def test_extract_diff_reads_fenced_block(tmp_path):
    repo = _init_repo(tmp_path, "old text\n")
    patch = _write_patch(repo, "note.md", "old text\n", "new text\n")
    diff = apply_proposals.extract_diff(patch)
    assert diff.startswith("diff --git")
    assert "-old text" in diff
    assert "+new text" in diff


# BRD: NFR-PROP-3
def test_check_clean_when_note_unchanged(tmp_path):
    repo = _init_repo(tmp_path, "old text\n")
    patch = _write_patch(repo, "note.md", "old text\n", "new text\n")
    assert apply_proposals.check(repo, patch) is True


# BRD: NFR-PROP-3, NFR-PROP-9
def test_check_stale_when_note_drifted(tmp_path):
    repo = _init_repo(tmp_path, "old text\n")
    patch = _write_patch(repo, "note.md", "old text\n", "new text\n")
    (repo / "note.md").write_text("something else entirely\n")
    _git(repo, "add", "note.md")
    _git(repo, "commit", "-q", "-m", "drift")
    assert apply_proposals.check(repo, patch) is False


# BRD: NFR-PROP-9, NFR-PROP-3, NFR-PROP-2
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


# BRD: FR-PROP-9, NFR-PROP-3
def test_check_clean_for_new_file_when_target_absent(tmp_path):
    repo = _init_empty_repo(tmp_path)
    patch = _write_create_patch(repo, "new.md", "hello\n")
    assert apply_proposals.check(repo, patch) is True


# BRD: FR-PROP-9, NFR-PROP-9
def test_apply_one_creates_new_file(tmp_path):
    repo = _init_empty_repo(tmp_path)
    patch = _write_create_patch(repo, "sub/new.md", "hello\n")
    ok, _stderr = apply_proposals.apply_one(repo, patch)
    assert ok is True
    assert (repo / "sub" / "new.md").read_text() == "hello\n"


# BRD: FR-PROP-9, NFR-PROP-9, NFR-PROP-11
def test_check_stale_when_create_target_already_exists(tmp_path):
    # Regression: for a *create* diff, the base is declared directly as
    # /dev/null in the diff text, not looked up via the index line's blob
    # hash — so the dummy-hash trick that protects existing-file edits from
    # a false-clean check does not apply here. Verified this bug empirically
    # before the fix: check() reported CLEAN even though the target had been
    # independently created with different content in the meantime.
    repo = _init_empty_repo(tmp_path)
    patch = _write_create_patch(repo, "new.md", "proposed content\n")
    (repo / "new.md").write_text("independently created content\n")
    _git(repo, "add", "new.md")
    _git(repo, "commit", "-q", "-m", "independent create")
    assert apply_proposals.check(repo, patch) is False


# BRD: FR-PROP-9, NFR-PROP-9, NFR-PROP-11, NFR-PROP-2
def test_drifted_create_apply_never_writes_conflict_markers(tmp_path):
    # Regression: before the _drifted_new_file_targets guard, `git apply
    # --3way` could always reconstruct an empty base for a create hunk (it's
    # declared in the diff itself, not fetched from a blob), so it performed
    # a genuine 3-way merge on a drifted create-target and silently wrote
    # <<<<<<< conflict markers into the file on disk — while check() still
    # reported CLEAN. Verified against a real git apply before this fix.
    repo = _init_empty_repo(tmp_path)
    patch = _write_create_patch(repo, "new.md", "proposed content\n")
    (repo / "new.md").write_text("independently created content\n")
    _git(repo, "add", "new.md")
    _git(repo, "commit", "-q", "-m", "independent create")

    assert apply_proposals.check(repo, patch) is False
    ok, stderr = apply_proposals.apply_one(repo, patch)
    assert ok is False
    assert "drifted" in stderr
    content = (repo / "new.md").read_text()
    assert content == "independently created content\n"
    assert "<<<<<<<" not in content


# BRD: FR-PROP-5, NFR-PROP-2
def test_apply_one_updates_file_and_leaves_it_uncommitted(tmp_path):
    repo = _init_repo(tmp_path, "old text\n")
    patch = _write_patch(repo, "note.md", "old text\n", "new text\n")
    ok, _stderr = apply_proposals.apply_one(repo, patch)
    assert ok is True
    assert (repo / "note.md").read_text() == "new text\n"
    status = subprocess.run(["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True, check=False).stdout
    assert "note.md" in status  # modified, not committed


# BRD: FR-PROP-5
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


# BRD: FR-PROP-5, NFR-PROP-3
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


# BRD: OI-3 (RISK-7 mitigation)
def test_main_rejects_concurrent_run_without_touching_anything(tmp_path):
    repo = _init_repo(tmp_path, "old text\n")
    patch = _write_patch(repo, "note.md", "old text\n", "new text\n")

    # Simulate another apply_proposals.py process already holding the lock.
    lock_path = repo / ".apply_proposals.lock"
    holder = lock_path.open("w")
    fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        argv = sys.argv
        sys.argv = ["apply_proposals.py", "--repo", str(repo), "--apply"]
        try:
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                code = apply_proposals.main()
        finally:
            sys.argv = argv

        assert code == 3
        assert "holds the lock" in err.getvalue()
        assert patch.exists()  # never even checked, let alone applied
        assert (repo / "note.md").read_text() == "old text\n"  # untouched
    finally:
        fcntl.flock(holder, fcntl.LOCK_UN)
        holder.close()
