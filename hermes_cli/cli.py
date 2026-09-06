from __future__ import annotations

import subprocess

import click

from . import config, privilege, selfupdate
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
    privilege.require_root()
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


@main.command("self-update")
@click.option("--check", is_flag=True, help="Only check for an update, don't apply it.")
def self_update(check: bool) -> None:
    """Update hc itself from its own git checkout (separate from `hc pull`, which updates the registry)."""
    root = selfupdate.repo_root()
    selfupdate.fetch(root)
    if not selfupdate.behind_upstream(root):
        click.echo(f"hc is up to date ({root})")
        return
    if check:
        click.echo(f"update available in {root} — run `hc self-update` to install it")
        return
    click.echo(f"updating hc in {root} ...")
    selfupdate.pull_and_install(root)
    click.echo("hc updated")


for _cmd in _compose_commands:
    main.add_command(_cmd)

main.add_command(mount)


if __name__ == "__main__":
    main()
