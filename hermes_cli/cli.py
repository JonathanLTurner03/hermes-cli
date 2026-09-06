from __future__ import annotations

import subprocess

import click

from . import config
from .compose.cli import COMMANDS as _compose_commands
from .mount.cli import mount


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


for _cmd in _compose_commands:
    main.add_command(_cmd)

main.add_command(mount)


if __name__ == "__main__":
    main()
