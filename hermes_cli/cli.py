from __future__ import annotations

import subprocess
import sys

import click

from . import config, github, privilege, selfupdate
from .compose.cli import COMMANDS as _compose_commands
from .mount.cli import mount
from .secrets.cli import secrets


@click.group()
def main() -> None:
    """hc - Hermes CLI. Wrapper around Docker Compose for the hermes registry."""


def _stdin_is_tty() -> bool:
    """A named wrapper around sys.stdin.isatty(), not just an inline call —
    click.testing.CliRunner substitutes its own sys.stdin object for the
    duration of invoke(), which a test-time patch on the *pre-existing*
    sys.stdin.isatty made before calling invoke() won't survive. Patching
    this function directly (`cli._stdin_is_tty = lambda: True`) sidesteps
    that substitution entirely.
    """
    return sys.stdin.isatty()


def _maybe_configure_github_token() -> None:
    """Optional, skippable prompt at the end of `hc init` for hc update's
    PR-creation token (see github.py). Only offered when stdin is a tty —
    a scripted/automated `hc init` has nothing to prompt against and
    should pass --github-token instead, or set the file up separately.
    """
    click.echo()
    click.echo("hc update can open a GitHub pull request automatically when it finds a newer")
    click.echo("image version for a pinned service — needs a token with 'Pull requests: Read")
    click.echo(f"and write' access to this repo. Create one at: {github.TOKEN_SETUP_URL}")
    if not click.confirm("Configure it now?", default=False):
        click.echo(f"skipped — set it up later: write a token to {github.TOKEN_PATH}, or rerun `hc init`")
        return
    token = click.prompt("GitHub token", hide_input=True)
    github.write_token(token)
    click.echo(f"wrote {github.TOKEN_PATH}")


@main.command()
@click.argument("server")
@click.option(
    "--registry-path",
    default=config.DEFAULT_REGISTRY_PATH,
    show_default=True,
    help="Path to the local hermes registry clone.",
)
@click.option(
    "--github-token",
    default=None,
    help="GitHub PR-creation token to configure non-interactively (skips the prompt) — "
    "see README's 'Version-pinned updates' section for what access it needs.",
)
def init(server: str, registry_path: str, github_token: str | None) -> None:
    """Write host identity config (server name + registry path)."""
    privilege.require_root()
    config.write_config(server, registry_path)
    click.echo(f"wrote {config.CONFIG_PATH}: server={server} registry_path={registry_path}")

    if github_token:
        github.write_token(github_token)
        click.echo(f"wrote {github.TOKEN_PATH}")
    elif not github.TOKEN_PATH.exists() and _stdin_is_tty():
        _maybe_configure_github_token()


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
main.add_command(secrets)


if __name__ == "__main__":
    main()
