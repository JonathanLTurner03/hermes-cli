"""Reconciles Traefik's dynamic-enabled/ directory with the registry's
enabled routes, as symlinks — the actual "apply" half of `hc sync`.

Mirrors mount/systemd.py's sync_units() diffing shape (added/changed/
removed), but there's no external tool to shell out to here: Traefik's
file provider just watches a directory of files, so applying a route is
nothing more than a symlink pointing at the registry's route.yml.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from .registry import RouteError


@dataclass
class SyncDiff:
    added: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)


def sync_symlinks(target_dir: Path, desired: dict[str, Path], force: bool = False) -> SyncDiff:
    """Reconcile target_dir's `<name>.yml` symlinks against `desired` (name -> route.yml path).

    Only ever touches entries whose filename hc recognizes as one it
    manages. A non-symlink file already occupying a name hc wants to write
    (or a stale one no longer in the registry) is left in place unless
    `force` is set — clobbering it silently could delete something
    hand-placed on the host.
    """
    target_dir.mkdir(parents=True, exist_ok=True)
    diff = SyncDiff()

    existing = {p.stem: p for p in target_dir.iterdir() if p.name.endswith(".yml")}

    for name, route_path in desired.items():
        resolved = route_path.resolve()
        link_path = target_dir / f"{name}.yml"

        if name not in existing:
            link_path.symlink_to(resolved)
            diff.added.append(name)
            continue

        current = existing[name]
        if current.is_symlink() and Path(os.readlink(current)) == resolved:
            continue
        if not current.is_symlink() and not force:
            raise RouteError(
                f"{current} already exists and isn't a symlink hc manages — "
                f"remove it manually or rerun `hc sync --force`"
            )
        current.unlink()
        link_path.symlink_to(resolved)
        diff.changed.append(name)

    for name, path in existing.items():
        if name in desired:
            continue
        if not path.is_symlink() and not force:
            raise RouteError(
                f"{path} isn't a symlink hc manages but occupies a name no longer "
                f"enabled in the registry — remove it manually or rerun `hc sync --force`"
            )
        path.unlink()
        diff.removed.append(name)

    return diff
