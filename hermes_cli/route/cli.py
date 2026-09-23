"""Click command for `hc sync`. Attached to the top-level `main` group as
a flat command (not a subgroup) by hermes_cli.cli.
"""
from __future__ import annotations

import click

from .. import config
from . import registry, sync


@click.command("sync")
@click.option(
    "--force",
    is_flag=True,
    help="Overwrite or remove dynamic-enabled/ entries hc doesn't recognize as its own symlinks.",
)
def route_sync(force: bool) -> None:
    """Render every enabled route.yml in the registry into Traefik's dynamic-enabled/.

    Walks the whole registry clone (not just this host's own directory) for
    route.yml + sibling `enabled` marker pairs, and reconciles this host's
    <server>/traefik/dynamic-enabled/ to match via symlinks — only valid on
    the host running Traefik itself.
    """
    cfg = config.load_config()
    target_dir = registry.dynamic_enabled_dir(cfg)
    routes = registry.find_routes(cfg)

    desired = {r.name: r.path for r in routes if r.enabled}
    diff = sync.sync_symlinks(target_dir, desired, force=force)

    for name in diff.added:
        click.echo(f"+ {name}")
    for name in diff.changed:
        click.echo(f"~ {name}")
    for name in diff.removed:
        click.echo(f"- {name}")
    if not (diff.added or diff.changed or diff.removed):
        click.echo("no changes")

    disabled = sorted(r.name for r in routes if not r.enabled)
    if disabled:
        click.echo(f"not enabled (no 'enabled' marker): {', '.join(disabled)}")
