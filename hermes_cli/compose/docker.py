"""Thin wrapper around `docker compose` invocations.

Deliberately dumb for v1: resolve the compose file, build the argv, exec it.
No network-ensure, no secrets injection yet — those are later milestones and
get bolted on here once this loop is trustworthy.
"""
from __future__ import annotations

import subprocess
from pathlib import Path


class ComposeError(SystemExit):
    pass


def run(
    compose_path: Path, *args: str, check: bool = True, capture: bool = False
) -> subprocess.CompletedProcess:
    cmd = ["docker", "compose", "-f", str(compose_path), *args]
    try:
        return subprocess.run(cmd, check=check, capture_output=capture, text=capture)
    except FileNotFoundError as exc:
        raise ComposeError(f"docker not found on PATH: {exc}")
    except subprocess.CalledProcessError as exc:
        raise ComposeError(f"`{' '.join(cmd)}` failed with exit code {exc.returncode}")


def up(compose_path: Path) -> None:
    run(compose_path, "up", "-d")


def down(compose_path: Path) -> None:
    run(compose_path, "down")


def restart(compose_path: Path) -> None:
    run(compose_path, "restart")


def update(compose_path: Path) -> None:
    """Re-pull image(s) and recreate any container whose image actually changed.

    A plain `up -d` won't notice a moving tag (`:latest`, a floating `:6`,
    etc.) has moved — it just reuses whatever's already cached locally under
    that tag. `pull` always checks the tag's current digest against the
    registry and only downloads if it changed; the follow-up `up -d` then
    recreates only the containers whose image (or other config) actually
    changed, leaving anything already current running untouched.
    """
    run(compose_path, "pull")
    run(compose_path, "up", "-d")


def check(compose_path: Path) -> bool:
    """True if an update is available — i.e. `update()` would actually recreate something.

    Pulls for real (refreshes the locally cached tag against the registry —
    same "real I/O, but no service disruption" trade-off as `hc self-update
    --check`'s `git fetch`), then asks compose what `up -d` *would* do via
    `--dry-run` without touching the running container at all. Checking for
    "Recreate" in the dry-run plan piggybacks on compose's own
    image-changed detection rather than hand-rolling image ID comparisons
    ourselves — verified live that a genuine change reports "Recreate" and
    leaves the real container completely untouched, and an unchanged image
    reports "Running".

    Checks both stdout and stderr: compose writes this progress/plan text to
    stderr, not stdout (confirmed by direct reproduction — capturing stdout
    alone silently produced an empty string and always reported "up to
    date", regardless of the real answer). Checking both is the more
    defensive read in case that changes across compose versions.
    """
    run(compose_path, "pull")
    result = run(compose_path, "up", "-d", "--dry-run", capture=True)
    return "Recreate" in result.stdout + result.stderr


def logs(compose_path: Path, follow: bool = False) -> None:
    args = ["logs"]
    if follow:
        args.append("-f")
    run(compose_path, *args)


def ps(compose_path: Path) -> subprocess.CompletedProcess:
    return run(compose_path, "ps", check=False)
