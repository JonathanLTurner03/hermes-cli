"""Click commands for compose-managed services. Attached to the top-level
`main` group (as flat `hc <cmd>` commands, not a `hc compose <cmd>` subgroup)
by hermes_cli.cli.
"""
from __future__ import annotations

import click

from .. import config
from . import docker, networks, registry


def _complete_service(ctx: click.Context, param: click.Parameter, incomplete: str) -> list[str]:
    """Shell-completion source for `<service>` arguments: registered service names for this host.

    Swallows every failure (no config yet, no registry, etc.) rather than
    raising — a completion request that errors out just means no suggestions
    that keystroke, not a crash in the user's shell.
    """
    try:
        cfg = config.load_config()
        names = registry.list_services(cfg)
    except SystemExit:
        return []
    return [name for name in names if name.startswith(incomplete)]


def _complete_service_or_all(ctx: click.Context, param: click.Parameter, incomplete: str) -> list[str]:
    """Shell-completion source for `hc update`'s target: service names, plus the `all` keyword."""
    try:
        cfg = config.load_config()
        names = registry.list_services(cfg)
    except SystemExit:
        names = []
    return [name for name in ["all", *names] if name.startswith(incomplete)]


def _ensure_ready(cfg: dict, service: str):
    """Preconditions shared by any command that starts/recreates containers:
    refuse if declared secrets are missing, and make sure external networks
    the compose file expects already exist. Returns the resolved compose
    file path so the caller doesn't have to look it up again.
    """
    compose_path = registry.compose_file(cfg, service)

    if registry.expects_secrets(cfg, service) and registry.secrets_file(cfg, service) is None:
        raise SystemExit(
            f"'{service}' expects .env.secrets but none found at "
            f"{registry.service_path(cfg, service) / '.env.secrets'} — copy it before starting"
        )

    for net in registry.external_networks(cfg, service):
        networks.ensure(net)

    return compose_path


@click.command()
@click.argument("service", shell_complete=_complete_service)
def up(service: str) -> None:
    """Start a service (docker compose up -d)."""
    cfg = config.load_config()
    compose_path = _ensure_ready(cfg, service)
    docker.up(compose_path)


@click.command()
@click.argument("service", shell_complete=_complete_service)
def down(service: str) -> None:
    """Stop a service (docker compose down)."""
    cfg = config.load_config()
    docker.down(registry.compose_file(cfg, service))


@click.command()
@click.argument("service", shell_complete=_complete_service)
def restart(service: str) -> None:
    """Restart a service (docker compose restart)."""
    cfg = config.load_config()
    docker.restart(registry.compose_file(cfg, service))


@click.command()
@click.argument("service", shell_complete=_complete_service)
@click.option("-f", "--follow", is_flag=True, help="Follow log output.")
def logs(service: str, follow: bool) -> None:
    """Tail logs for a service."""
    cfg = config.load_config()
    docker.logs(registry.compose_file(cfg, service), follow=follow)


@click.command()
@click.argument("service", required=False, shell_complete=_complete_service_or_all)
def update(service: str | None) -> None:
    """Re-pull image(s) and recreate any container whose image actually changed.

    Requires an explicit target — a service name, or `all` for every
    registered service on this host. Bare `hc update` refuses rather than
    quietly updating everything: recreating every container on a host at
    once is a bigger blast radius than a missing argument should trigger by
    default (unlike e.g. `hc status`, where "no args means all" is harmless).

    For a moving tag (:latest, a floating :6, etc.) that's already cached
    locally, `up` alone won't notice a new build exists — this pulls first
    so the tag's current digest is actually checked against the registry.
    """
    if service is None:
        raise SystemExit(
            "hc update needs a target — specify a service name, or `hc update all` "
            "to update every registered service on this host"
        )
    cfg = config.load_config()
    targets = registry.list_services(cfg) if service == "all" else [service]
    for name in targets:
        compose_path = _ensure_ready(cfg, name)
        click.echo(f"── {name} ──")
        docker.update(compose_path)


@click.command()
@click.argument("service", required=False, shell_complete=_complete_service)
def status(service: str | None) -> None:
    """Show `docker compose ps` for one service, or all registered services."""
    cfg = config.load_config()
    targets = [service] if service else registry.list_services(cfg)
    for name in targets:
        compose_path = registry.compose_file(cfg, name)
        click.echo(f"── {name} ──")
        docker.ps(compose_path)


@click.command()
def services() -> None:
    """List services registered for this server."""
    cfg = config.load_config()
    for name in registry.list_services(cfg):
        click.echo(name)


@click.command()
@click.argument("service", shell_complete=_complete_service)
def where(service: str) -> None:
    """Print the resolved path for a service (debug helper)."""
    cfg = config.load_config()
    click.echo(str(registry.service_path(cfg, service)))


COMMANDS = [up, down, restart, update, logs, status, services, where]
