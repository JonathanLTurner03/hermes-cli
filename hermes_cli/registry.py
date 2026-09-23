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


def registry_root(config: dict) -> Path:
    """The whole registry clone, not just this host's <server>/ subdirectory.

    Only needed by features that deliberately look beyond their own host's
    tree — currently just `hc sync` (see route/registry.py), which finds
    route.yml files under *other* hosts' directories.
    """
    root = Path(config["registry_path"])
    if not root.exists():
        raise RegistryError(
            f"No registry clone at {root} — has `hc init` / `hc pull` run yet?"
        )
    return root
