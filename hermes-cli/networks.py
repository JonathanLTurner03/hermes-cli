"""Docker network management — ensuring external networks exist before
`docker compose up` needs them.

Compose refuses to start a service if a network declared `external: true`
doesn't already exist, so `hc up` calls ensure() for every such network
before invoking compose.
"""
from __future__ import annotations

import subprocess


class NetworkError(SystemExit):
    pass


def exists(name: str) -> bool:
    try:
        result = subprocess.run(
            ["docker", "network", "inspect", name],
            capture_output=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise NetworkError(f"docker not found on PATH: {exc}")
    return result.returncode == 0


def create(name: str) -> None:
    try:
        subprocess.run(["docker", "network", "create", name], check=True)
    except subprocess.CalledProcessError as exc:
        raise NetworkError(f"failed to create network '{name}': exit code {exc.returncode}")


def ensure(name: str) -> None:
    if not exists(name):
        create(name)
