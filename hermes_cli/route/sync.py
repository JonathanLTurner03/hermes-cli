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

    Every desired entry's symlink is unconditionally recreated (unlink +
    re-link), even when it already points at the right target — not just
    when something's actually new or changed. Traefik's file provider
    watches target_dir itself via inotify, which only fires on events
    inside that directory; editing route.yml's *content* happens
    elsewhere in the registry and generates no event there at all, so a
    symlink that already "looks right" can silently be serving stale
    config with no way to tell from the diff output. Recreating it every
    run forces a real create event Traefik does see, so `hc sync` always
    guarantees a fresh reload — confirmed necessary by testing: editing an
    already-synced route.yml in place, with no symlink change, left
    Traefik serving the old content indefinitely.
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
        unchanged = current.is_symlink() and Path(os.readlink(current)) == resolved
        if not current.is_symlink() and not force:
            raise RouteError(
                f"{current} already exists and isn't a symlink hc manages — "
                f"remove it manually or rerun `hc sync --force`"
            )
        current.unlink()
        link_path.symlink_to(resolved)
        if not unchanged:
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
