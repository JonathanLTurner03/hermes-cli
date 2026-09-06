"""Root-privilege handling for commands that write to /etc or manage
systemd units. Not every command needs this: read-only status commands
don't, `hc pull` doesn't, and compose commands are gated by `docker` group
membership rather than root — call require_root() only from the commands
that actually need it.
"""
from __future__ import annotations

import os
import sys


def require_root() -> None:
    """Re-exec the current command under sudo if not already running as root.

    Uses os.execvp to replace this process rather than spawning a child, so
    there's no double Python startup and the re-exec'd process keeps the
    original stdin/stdout/stderr — sudo's password prompt behaves exactly
    as if the user had typed `sudo hc ...` themselves. Refuses to attempt
    elevation when stdin isn't a tty (cron, CI, etc.), since sudo would
    otherwise hang or fail opaquely waiting on a prompt nothing can answer.
    """
    if os.geteuid() == 0:
        return
    if not sys.stdin.isatty():
        raise SystemExit(
            "this command needs root — rerun with sudo (no tty available to prompt for a password)"
        )
    try:
        os.execvp("sudo", ["sudo"] + sys.argv)
    except FileNotFoundError:
        raise SystemExit("sudo not found on PATH — rerun this command as root directly")
