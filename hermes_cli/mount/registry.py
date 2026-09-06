"""Registry-side loading and validation of mount specs.

Registry layout:
    <registry_path>/<server>/mounts/<name>.yml
    <registry_path>/<server>/pools.yml   (optional)

Each mounts/*.yml file is a declarative spec (see MountSpec) that
`systemd.render_unit()` turns into a systemd .mount unit.

Storage pools are intentionally NOT registry-managed — see
mount-feature-doc.md's "Scope decision" section — they live in /etc/fstab,
unmanaged by hc, so a registry/sync mistake can only ever affect derivative
bind mounts, never the pool itself. hc still needs to know a pool's *name*
and mount point to reference it from other mounts' `depends_on`, the
docker.service drop-in, and `hc mount status` — that's what pools.yml
declares. It lives at the server root rather than under mounts/ since it's
metadata about units hc does NOT render, not a mount spec itself. A host can
declare zero, one, or several pools there.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .. import registry


class MountError(SystemExit):
    pass


@dataclass(frozen=True)
class Pool:
    name: str
    target: str


@dataclass(frozen=True)
class MountSpec:
    name: str
    source: str
    target: str
    type: str = "bind"
    options: list[str] = field(default_factory=list)
    depends_on: str | None = None
    description: str | None = None


def mounts_dir(config: dict) -> Path:
    return registry.server_root(config) / "mounts"


def pools_file(config: dict) -> Path:
    return registry.server_root(config) / "pools.yml"


def load_pools(config: dict) -> list[Pool]:
    """Load the unmanaged storage pools declared for this host, if any.

    Returns an empty list if the host has no pools.yml — not every host has
    a pool of its own (e.g. one that's pure bind mounts off another host's
    share).
    """
    path = pools_file(config)
    if not path.exists():
        return []

    data = yaml.safe_load(path.read_text()) or {}
    entries = data.get("pools") or []
    pools: list[Pool] = []
    seen: set[str] = set()
    for entry in entries:
        for key in ("name", "target"):
            if key not in entry:
                raise MountError(f"{path}: pool entry missing required field '{key}'")
        if entry["name"] in seen:
            raise MountError(f"{path}: duplicate pool name '{entry['name']}'")
        seen.add(entry["name"])
        pools.append(Pool(name=entry["name"], target=entry["target"]))
    return pools


def load_specs(config: dict, pool_names: set[str]) -> list[MountSpec]:
    """Load and validate every mount spec registered for this host.

    Returns an empty list if the host has no mounts/ directory yet — not
    every host has registry-managed mounts.

    `pool_names` are the unmanaged pools declared in pools.yml (see
    load_pools): a spec can't reuse one of those names, but `depends_on` may
    reference one even though it has no spec file of its own.
    """
    directory = mounts_dir(config)
    if not directory.exists():
        return []

    specs: list[MountSpec] = []
    for path in sorted(directory.glob("*.yml")):
        data = yaml.safe_load(path.read_text()) or {}
        for key in ("name", "source", "target"):
            if key not in data:
                raise MountError(f"{path}: missing required field '{key}'")
        if data["name"] in pool_names:
            raise MountError(
                f"{path}: '{data['name']}' is declared as a pool in pools.yml — pools are "
                f"intentionally unmanaged by hc (see mount-feature-doc.md's scope decision). "
                f"Remove this file from the registry; other mounts can still depend_on it by name."
            )
        specs.append(
            MountSpec(
                name=data["name"],
                source=data["source"],
                target=data["target"],
                type=data.get("type", "bind"),
                options=list(data.get("options") or []),
                depends_on=data.get("depends_on"),
                description=data.get("description"),
            )
        )

    names = {spec.name for spec in specs}
    for spec in specs:
        if spec.depends_on and spec.depends_on not in pool_names and spec.depends_on not in names:
            raise MountError(
                f"mount '{spec.name}' has depends_on: {spec.depends_on}, which isn't "
                f"a registered mount or declared pool for this host"
            )
    return specs


def find_spec(specs: list[MountSpec], name: str) -> MountSpec:
    for spec in specs:
        if spec.name == name:
            return spec
    raise MountError(f"No mount '{name}' registered for this host")
