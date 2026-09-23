"""Click commands for sops+age encrypted secrets. Attached to the top-level
`main` group as the `secrets` subgroup by hermes_cli.cli.
"""
from __future__ import annotations

import click

from .. import config
from ..compose import registry as compose_registry
from . import registry, sops


def _complete_service(ctx: click.Context, param: click.Parameter, incomplete: str) -> list[str]:
    """Shell-completion source: registered service names for this host.

    Reuses compose's service listing (a "service" is just a directory with a
    docker-compose.yml) rather than duplicating it — secrets always belong
    to a compose service directory. Swallows every failure (no config yet,
    no registry, etc.) rather than raising, same as compose's own completers.
    """
    try:
        cfg = config.load_config()
        names = compose_registry.list_services(cfg)
    except SystemExit:
        return []
    return [name for name in names if name.startswith(incomplete)]


@click.group()
def secrets() -> None:
    """Manage sops+age encrypted per-service secrets."""


@secrets.command("edit")
@click.argument("service", shell_complete=_complete_service)
def secrets_edit(service: str) -> None:
    """Open <service>/secrets.enc.yaml in $EDITOR via sops (decrypted for editing, re-encrypted on save).

    Creates the file if it doesn't exist yet, per whatever recipients
    .sops.yaml's matching rule lists for this path — same as running sops
    by hand.
    """
    cfg = config.load_config()
    path = compose_registry.service_path(cfg, service) / "secrets.enc.yaml"
    sops.edit(path)


@secrets.command("sync")
@click.argument("service", required=False, shell_complete=_complete_service)
def secrets_sync(service: str | None) -> None:
    """Decrypt secrets.enc.yaml and write out this host's copy under <service>/secrets/.

    Runs automatically as part of `hc up`/`hc update` — this is a standalone
    entry point for re-syncing without touching any container (e.g. after
    rotating a value, or to debug decryption before deploying).
    """
    cfg = config.load_config()
    targets = [service] if service else compose_registry.list_services(cfg)
    found_any = False
    for name in targets:
        out_dir = registry.sync(cfg, name)
        if out_dir is not None:
            found_any = True
            click.echo(f"{name}: wrote {out_dir}")
    if not found_any:
        scope = f"'{service}'" if service else "any registered service"
        click.echo(f"no secrets.enc.yaml found for {scope}")
