#!/usr/bin/env python3
"""
Apply propose_edit patches from a vault's Proposals/ queue.

Model-free by design (see agents.md): run from a terminal, cron, or `make` —
never inside a Claude Code session. Claude Code must invoke this script, not
read or reason about the patch files itself.

Each Proposals/*.patch.md file wraps a fenced ```diff block, written by the
propose_edit MCP tool in server.py. Applying uses `git apply --3way`, so a
proposal drifted out of sync with its target note is skipped, not force-applied.
"""

import argparse
import contextlib
import fcntl
import re
import subprocess
import sys
from pathlib import Path

DIFF_BLOCK_RE = re.compile(r"```diff\n(.*?)```", re.DOTALL)


@contextlib.contextmanager
def _lock(repo: Path):
    # BRD.md OI-3/RISK-7: without this, two overlapping runs (e.g. a cron job
    # and a manual run) could interleave check()/apply() steps across
    # processes and partially apply a patch. LOCK_NB fails fast instead of
    # blocking, so a second run exits cleanly rather than hanging.
    lock_path = repo / ".apply_proposals.lock"
    lock_file = lock_path.open("w")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock_file.close()
        raise
    try:
        yield
    finally:
        fcntl.flock(lock_file, fcntl.LOCK_UN)
        lock_file.close()


def extract_diff(patch_md: Path) -> str:
    m = DIFF_BLOCK_RE.search(patch_md.read_text())
    if not m:
        raise ValueError(f"no fenced diff block in {patch_md}")
    return m.group(1)


def check(repo: Path, patch_md: Path) -> bool:
    proc = subprocess.run(
        ["git", "apply", "--3way", "--check"],
        input=extract_diff(patch_md), text=True, cwd=repo, capture_output=True, check=False,
    )
    return proc.returncode == 0


def apply_one(repo: Path, patch_md: Path) -> tuple[bool, str]:
    proc = subprocess.run(
        ["git", "apply", "--3way"],
        input=extract_diff(patch_md), text=True, cwd=repo, capture_output=True, check=False,
    )
    return proc.returncode == 0, proc.stderr


def _run(repo: Path, proposals_dir: Path, apply: bool) -> int:
    patches = sorted(proposals_dir.glob("*.patch.md"))
    if not patches:
        print("No proposals.")
        return 0

    exit_code = 0
    for patch_md in patches:
        clean = check(repo, patch_md)
        if not apply:
            print(f"{'CLEAN' if clean else 'STALE'}: {patch_md.name}")
            continue
        if not clean:
            print(f"SKIP (stale): {patch_md.name}")
            continue
        ok, stderr = apply_one(repo, patch_md)
        if ok:
            patch_md.unlink()
            print(f"APPLIED: {patch_md.name}")
        else:
            print(f"FAILED: {patch_md.name}\n{stderr}", file=sys.stderr)
            exit_code = 1
    return exit_code


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", required=True, type=Path, help="path to the vault git clone")
    ap.add_argument("--proposals-dir", type=Path, default=None, help="default: <repo>/Proposals")
    ap.add_argument("--apply", action="store_true", help="apply cleanly-checked proposals (default: dry-run report)")
    args = ap.parse_args()

    proposals_dir = args.proposals_dir or (args.repo / "Proposals")

    try:
        with _lock(args.repo):
            return _run(args.repo, proposals_dir, apply=args.apply)
    except BlockingIOError:
        print(
            f"Another apply_proposals.py run holds the lock on {args.repo} — exiting without touching anything.",
            file=sys.stderr,
        )
        return 3


if __name__ == "__main__":
    sys.exit(main())
