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


def run(compose_path: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    cmd = ["docker", "compose", "-f", str(compose_path), *args]
    try:
        return subprocess.run(cmd, check=check)
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


def logs(compose_path: Path, follow: bool = False) -> None:
    args = ["logs"]
    if follow:
        args.append("-f")
    run(compose_path, *args)


def ps(compose_path: Path) -> subprocess.CompletedProcess:
    return run(compose_path, "ps", check=False)
