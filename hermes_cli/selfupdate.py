"""Update hc's own source checkout — distinct from `hc pull`, which only
updates the hermes *registry* clone (see config.py/registry.py).

hc is installed via `pip install -e .` (see install.sh), so its own source
lives at whatever git checkout that editable install points back to. This
module finds that checkout from hermes_cli.__file__ rather than needing a
separately-tracked path in config.yml — an editable install's __file__
always resolves to the real checkout, not a copied/zipped location.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import hermes_cli


class SelfUpdateError(SystemExit):
    pass


def repo_root() -> Path:
    return Path(hermes_cli.__file__).resolve().parent.parent


def _run(cmd: list[str], cwd: Path, **kwargs) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, cwd=cwd, **kwargs)
    except FileNotFoundError as exc:
        raise SelfUpdateError(f"{cmd[0]} not found on PATH: {exc}")


def is_dirty(root: Path) -> bool:
    result = _run(["git", "status", "--porcelain"], cwd=root, capture_output=True, text=True, check=False)
    return bool(result.stdout.strip())


def fetch(root: Path) -> None:
    result = _run(["git", "fetch"], cwd=root, check=False)
    if result.returncode != 0:
        raise SelfUpdateError(f"git fetch failed in {root} (exit {result.returncode})")


def behind_upstream(root: Path) -> bool:
    """Whether the checkout's tracking branch has commits HEAD doesn't. Call fetch() first."""
    local = _run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=False)
    upstream = _run(["git", "rev-parse", "@{u}"], cwd=root, capture_output=True, text=True, check=False)
    if local.returncode != 0 or upstream.returncode != 0:
        raise SelfUpdateError(
            f"couldn't resolve HEAD/upstream in {root} — is it a git checkout with a tracking branch?"
        )
    return local.stdout.strip() != upstream.stdout.strip()


def pull_and_install(root: Path) -> None:
    """Fast-forward the checkout and rerun install.sh (safe to rerun; picks up dependency changes)."""
    if is_dirty(root):
        raise SelfUpdateError(
            f"{root} has uncommitted local changes — resolve or stash them before self-update"
        )
    result = _run(["git", "pull", "--ff-only"], cwd=root, check=False)
    if result.returncode != 0:
        raise SelfUpdateError(f"git pull failed in {root} (exit {result.returncode})")

    install_script = root / "install.sh"
    result = _run(["bash", str(install_script)], cwd=root, check=False)
    if result.returncode != 0:
        raise SelfUpdateError(f"install.sh failed (exit {result.returncode})")
