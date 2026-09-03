from __future__ import annotations

import subprocess

import click

from . import compose, config, networks, registry


@click.group()
def main() -> None:
    """hc - Hermes CLI. Wrapper around Docker Compose for the hermes registry."""


@main.command()
@click.argument("server")
@click.option(
    "--registry-path",
    default=config.DEFAULT_REGISTRY_PATH,
    show_default=True,
    help="Path to the local hermes registry clone.",
)
def init(server: str, registry_path: str) -> None:
    """Write host identity config (server name + registry path)."""
    config.write_config(server, registry_path)
    click.echo(f"wrote {config.CONFIG_PATH}: server={server} registry_path={registry_path}")


@main.command()
def pull() -> None:
    """Git pull the hermes registry."""
    cfg = config.load_config()
    result = subprocess.run(
        ["git", "-C", cfg["registry_path"], "pull"],
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(result.returncode)


@main.command()
@click.argument("service")
def where(service: str) -> None:
    """Print the resolved path for a service (debug helper)."""
    cfg = config.load_config()
    path = registry.service_path(cfg, service)
    click.echo(str(path))


@main.command()
def services() -> None:
    """List services registered for this server."""
    cfg = config.load_config()
    for name in registry.list_services(cfg):
        click.echo(name)


@main.command()
@click.argument("service")
def up(service: str) -> None:
    """Start a service (docker compose up -d)."""
    cfg = config.load_config()
    compose_path = registry.compose_file(cfg, service)

    if registry.expects_secrets(cfg, service) and registry.secrets_file(cfg, service) is None:
        raise SystemExit(
            f"'{service}' expects .env.secrets but none found at "
            f"{registry.service_path(cfg, service) / '.env.secrets'} — copy it before starting"
        )

    for net in registry.external_networks(cfg, service):
        networks.ensure(net)

    compose.up(compose_path)


@main.command()
@click.argument("service")
def down(service: str) -> None:
    """Stop a service (docker compose down)."""
    cfg = config.load_config()
    compose_path = registry.compose_file(cfg, service)
    compose.down(compose_path)


@main.command()
@click.argument("service")
def restart(service: str) -> None:
    """Restart a service (docker compose restart)."""
    cfg = config.load_config()
    compose_path = registry.compose_file(cfg, service)
    compose.restart(compose_path)


@main.command()
@click.argument("service")
@click.option("-f", "--follow", is_flag=True, help="Follow log output.")
def logs(service: str, follow: bool) -> None:
    """Tail logs for a service."""
    cfg = config.load_config()
    compose_path = registry.compose_file(cfg, service)
    compose.logs(compose_path, follow=follow)


@main.command()
@click.argument("service", required=False)
def status(service: str | None) -> None:
    """Show `docker compose ps` for one service, or all registered services."""
    cfg = config.load_config()
    targets = [service] if service else registry.list_services(cfg)
    for name in targets:
        compose_path = registry.compose_file(cfg, name)
        click.echo(f"── {name} ──")
        compose.ps(compose_path)


if __name__ == "__main__":
    main()
