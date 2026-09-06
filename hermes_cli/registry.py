"""Shared entry point into the hermes registry's on-disk layout.

Every feature (compose, mount, ...) stores its config under
<registry_path>/<server>/<feature-subdir>/, so server_root() is the one
thing they all need in common. Feature-specific path resolution (e.g.
compose's docker-compose.yml/.env layout, mount's mounts/*.yml layout)
lives in that feature's own registry.py.
"""
from __future__ import annotations

from pathlib import Path


class RegistryError(SystemExit):
    pass


def server_root(config: dict) -> Path:
    root = Path(config["registry_path"]) / config["server"]
    if not root.exists():
        raise RegistryError(
            f"No directory for server '{config['server']}' at {root} — "
            f"does the hermes registry have an entry for this host?"
        )
    return root
