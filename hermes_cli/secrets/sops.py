"""Thin wrapper around the `sops` CLI (age-backed). hc never touches age keys
or .sops.yaml itself — those are sops's own territory (age's default key
lookup at ~/.config/sops/age/keys.txt, and the repo-root .sops.yaml
recipient rules). hc only shells out to decrypt at deploy time and to launch
an interactive edit session; sops/age handle the crypto and key management
entirely on their own.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path


class SopsError(SystemExit):
    pass


def _run(*args: str, capture: bool) -> subprocess.CompletedProcess:
    cmd = ["sops", *args]
    try:
        return subprocess.run(cmd, check=True, capture_output=capture, text=True)
    except FileNotFoundError:
        raise SopsError(
            "sops not found on PATH — install it (and age, its default backend) before "
            "using encrypted secrets: https://github.com/getsops/sops"
        )
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.strip() if capture and exc.stderr else f"exit code {exc.returncode}"
        raise SopsError(f"`{' '.join(cmd)}` failed: {detail}")


def decrypt(path: Path) -> dict:
    """Decrypt `path` and return its plaintext top-level key/value pairs.

    Uses --output-type json so the result is a plain dict regardless of the
    file's own extension/format, without needing a second YAML parse pass.
    """
    result = _run("-d", "--output-type", "json", str(path), capture=True)
    return json.loads(result.stdout)


SOPS_EXIT_FILE_UNCHANGED = 200


def edit(path: Path) -> None:
    """Open `path` in $EDITOR via `sops <path>`, decrypted for the duration.

    Inherits this process's stdio rather than capturing anything — sops
    drives $EDITOR interactively and re-encrypts on save/exit. Creates a new
    file (encrypted per .sops.yaml's matching rule) if `path` doesn't exist
    yet, same as running sops by hand.

    Doesn't use _run(): sops exits 200 (confirmed by real testing, not just
    docs) when the editor made no changes, which is an expected outcome
    (someone opened `edit`, looked, and quit without touching anything), not
    a failure — _run()'s check=True would turn that into a spurious
    SopsError. sops already prints its own "File has not changed, exiting."
    to stderr for this case, so there's nothing more to say here either way.
    """
    try:
        result = subprocess.run(["sops", str(path)], check=False)
    except FileNotFoundError:
        raise SopsError(
            "sops not found on PATH — install it (and age, its default backend) before "
            "using encrypted secrets: https://github.com/getsops/sops"
        )
    if result.returncode not in (0, SOPS_EXIT_FILE_UNCHANGED):
        raise SopsError(f"sops exited with code {result.returncode}")
