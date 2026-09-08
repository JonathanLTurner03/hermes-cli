"""Git operations for committing hc-made changes back to the registry clone.

Used by `hc update`'s version-pin flow to turn a local file edit into a
committed, pushed change without the user doing it by hand — see
compose/cli.py's _update_one_versioned(). Kept separate from registry.py
(which only ever *reads* the registry) since this is the one place hc
writes to git history, not just files.
"""
from __future__ import annotations

import subprocess
from pathlib import Path


class RegistryGitError(SystemExit):
    pass


def _run(cwd: Path, *args: str, capture: bool = False) -> subprocess.CompletedProcess:
    cmd = ["git", *args]
    try:
        result = subprocess.run(cmd, cwd=cwd, capture_output=capture, text=capture)
    except FileNotFoundError as exc:
        raise RegistryGitError(f"git not found on PATH: {exc}")
    if result.returncode != 0:
        detail = f": {result.stderr.strip()}" if capture and result.stderr else ""
        raise RegistryGitError(f"`git {' '.join(args)}` failed (exit {result.returncode}){detail}")
    return result


def is_dirty(registry_path: Path) -> bool:
    result = _run(registry_path, "status", "--porcelain", capture=True)
    return bool(result.stdout.strip())


def current_branch(registry_path: Path) -> str:
    result = _run(registry_path, "rev-parse", "--abbrev-ref", "HEAD", capture=True)
    return result.stdout.strip()


def remote_url(registry_path: Path, remote: str = "origin") -> str:
    result = _run(registry_path, "remote", "get-url", remote, capture=True)
    return result.stdout.strip()


def prepare(registry_path: Path) -> str:
    """Check the clone is clean and sync it with origin — call this BEFORE
    writing the file that's about to be committed, not after. Returns the
    current branch name (the base to branch from, and the PR's base once
    commit_and_push_branch() opens one).

    Refuses if the clone already has uncommitted changes sitting there —
    don't want to sweep something unrelated into hc's own commit — or if
    the branch can't be fast-forwarded to match origin, which matters
    doubly here: it reduces the chance of a conflict later, and doing a
    pull/merge while the tree is dirty (which is exactly what'd happen if
    this ran *after* the write) risks a real conflict against hc's own
    uncommitted edit.
    """
    if is_dirty(registry_path):
        raise RegistryGitError(
            f"{registry_path} has uncommitted changes — resolve or stash them before hc update "
            f"can commit its own change"
        )
    base = current_branch(registry_path)
    _run(registry_path, "pull", "--ff-only")
    return base


def commit_and_push_branch(
    registry_path: Path, file_path: Path, branch: str, base: str, message: str
) -> None:
    """Branch from `base`, commit `file_path` (already written by the
    caller after calling prepare()), and push the branch to origin.

    Does NOT merge locally — the merge happens via a PR (see github.py)
    that a human approves on GitHub, per this project's branch-and-review
    workflow (CLAUDE.md's "Development workflow" section, extended to
    hc's own auto-commits, not just interactive development). Returns the
    clone to `base` afterward, left clean and checked out normally — the
    topic branch's commit only lands on `base`'s history once the PR is
    actually merged and something runs `hc pull`.

    If anything from the branch-create step onward fails, the topic branch
    (and whatever commit made it) is deliberately left in place rather
    than cleaned up, so nothing done so far is lost.
    """
    _run(registry_path, "checkout", "-b", branch)
    _run(registry_path, "add", str(file_path))
    _run(registry_path, "commit", "-m", message)
    _run(registry_path, "push", "-u", "origin", branch)
    _run(registry_path, "checkout", base)
