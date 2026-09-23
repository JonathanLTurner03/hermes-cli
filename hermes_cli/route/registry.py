"""Route discovery for `hc sync` (Traefik's file provider).

Registry layout:
    <registry_path>/<server>/traefik/dynamic-enabled/    (rendered by hc sync, NOT tracked)
    <registry_path>/<any-server>/<service>/route.yml      (route.yml next to the service it fronts)
    <registry_path>/<any-server>/<service>/enabled        (empty marker file, toggles the route)
    <registry_path>/hecate/routes/<name>/route.yml        (routes to things hc doesn't manage)
    <registry_path>/hecate/routes/<name>/enabled

A route.yml is only rendered into dynamic-enabled/ when its sibling
`enabled` marker file also exists. `hc sync` runs on whichever host has a
traefik/ compose directory under its own server_root() (Hecate, in this
fleet) but scans the *entire* registry clone for route.yml — not just its
own server_root() — since routes for hc-managed services deliberately live
next to the service they front, on that service's own host directory, not
under the traefik host's tree. Every host already has the full registry
cloned locally (see registry_git.py / `hc pull`), so this doesn't require
any access beyond what's already on disk.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from .. import registry


class RouteError(SystemExit):
    pass


@dataclass(frozen=True)
class Route:
    name: str
    path: Path
    enabled: bool
    server: str


def _server_dirs(root: Path) -> list[Path]:
    return sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith("."))


def find_routes(config: dict) -> list[Route]:
    """Every route.yml in the registry, paired with whether it's enabled.

    A route's `name` is its containing directory's name (e.g. "jellyseerr",
    "omada") — that's what becomes the rendered filename in
    dynamic-enabled/, so two route.yml files under differently-named
    directories that happen to share a directory *name* across hosts is a
    genuine conflict, not a last-one-wins situation. Raises RouteError.
    """
    root = registry.registry_root(config)
    routes: list[Route] = []
    seen: dict[str, Path] = {}
    for server_dir in _server_dirs(root):
        for route_path in sorted(server_dir.rglob("route.yml")):
            name = route_path.parent.name
            if name in seen and seen[name] != route_path:
                raise RouteError(
                    f"duplicate route name '{name}': {seen[name]} and {route_path} — "
                    f"rename one of the containing directories, dynamic-enabled/ needs a unique filename"
                )
            seen[name] = route_path
            try:
                yaml.safe_load(route_path.read_text())
            except yaml.YAMLError as exc:
                raise RouteError(f"{route_path}: invalid YAML — {exc}")
            routes.append(
                Route(
                    name=name,
                    path=route_path,
                    enabled=(route_path.parent / "enabled").exists(),
                    server=server_dir.name,
                )
            )
    return routes


def dynamic_enabled_dir(config: dict) -> Path:
    """Where `hc sync` renders enabled routes for Traefik's file provider to watch.

    Only valid on the host running Traefik itself — requires a traefik/
    compose directory under this host's own server_root().
    """
    traefik_dir = registry.server_root(config) / "traefik"
    if not traefik_dir.exists():
        raise RouteError(
            f"No traefik/ directory at {traefik_dir} — `hc sync` only runs on the host "
            f"that runs Traefik (this host is configured as '{config['server']}')"
        )
    return traefik_dir / "dynamic-enabled"
