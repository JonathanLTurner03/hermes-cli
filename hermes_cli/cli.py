from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

import click

from . import config, github, privilege, selfupdate, softserve
from .compose.cli import COMMANDS as _compose_commands
from .mount.cli import mount
from .route.cli import route_sync
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


def _maybe_configure_softserve_token() -> None:
    """Optional, skippable prompt at the end of `hc init` for a self-hosted
    SoftServe git server's access token (see softserve.py) — used by
    `hc self-update --repo` and, in future, an http(s) `hc pull` remote.
    Only offered when stdin is a tty, same reasoning as the GitHub prompt.
    """
    click.echo()
    click.echo("If this fleet's git server has moved to a self-hosted SoftServe instance, hc")
    click.echo("self-update --repo (and future SoftServe-backed hc pull) need an access token.")
    click.echo("Generate one on the server itself: ssh -p <port> <softserve-host> token create hc-<this-host>")
    if not click.confirm("Configure it now?", default=False):
        click.echo(f"skipped — set it up later: write a token to {softserve.TOKEN_PATH}, or rerun `hc init`")
        return
    token = click.prompt("SoftServe token", hide_input=True)
    softserve.write_token(token)
    click.echo(f"wrote {softserve.TOKEN_PATH}")


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
@click.option(
    "--softserve-token",
    default=None,
    help="SoftServe access token to configure non-interactively (skips the prompt) — "
    "used by `hc self-update --repo` and future SoftServe-backed hc pull.",
)
def init(server: str, registry_path: str, github_token: str | None, softserve_token: str | None) -> None:
    """Write host identity config (server name + registry path)."""
    privilege.require_root()
    config.write_config(server, registry_path)
    click.echo(f"wrote {config.CONFIG_PATH}: server={server} registry_path={registry_path}")

    if github_token:
        github.write_token(github_token)
        click.echo(f"wrote {github.TOKEN_PATH}")
    elif not github.TOKEN_PATH.exists() and _stdin_is_tty():
        _maybe_configure_github_token()

    if softserve_token:
        softserve.write_token(softserve_token)
        click.echo(f"wrote {softserve.TOKEN_PATH}")
    elif not softserve.TOKEN_PATH.exists() and _stdin_is_tty():
        _maybe_configure_softserve_token()


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


def _switch_repo_origin(root: Path, url: str, token: str | None) -> str | None:
    """Points `root`'s tracking remote at `url` (an already-resolved repo
    URL, not a server base), embedding a SoftServe token for an http(s)
    URL (from `token` if given, else the configured file). Returns the
    resolved token (so a caller switching a second, sibling repo can
    reuse it instead of re-reading/re-erroring), or None if no token was
    needed (ssh://).
    """
    remote = selfupdate.tracking_remote(root)
    final_url = url
    resolved_token = None
    if urlsplit(url).scheme in ("http", "https"):
        resolved_token = token or softserve.read_token()
        final_url = softserve.with_token(url, resolved_token)
    elif token:
        click.echo(
            "--token ignored: --server isn't http(s), so SSH key auth applies instead", err=True
        )
    selfupdate.set_remote_url(root, remote, final_url)
    click.echo(f"{root}: {remote} now points at {url}")
    return resolved_token


def _switch_registry_origin(server_url: str, token: str | None) -> None:
    """Best-effort sibling switch: if this host has already run `hc init`
    and its registry clone looks like a real git checkout, point it at the
    hermes repo on the same SoftServe server. Skipped with a message
    rather than failing self-update outright -- a bare hc install with no
    registry cloned yet (or no `hc init` run) is a normal state, not an
    error, and self-update's primary job is updating hc itself.
    """
    try:
        cfg = config.load_config()
    except SystemExit:
        click.echo("skipped hermes registry origin switch: `hc init` hasn't run on this host yet", err=True)
        return

    registry_path = Path(cfg["registry_path"])
    if not (registry_path / ".git").exists():
        click.echo(
            f"skipped hermes registry origin switch: {registry_path} isn't a git checkout", err=True
        )
        return

    _switch_repo_origin(registry_path, softserve.repo_url(server_url, "hermes"), token)


@main.command("self-update")
@click.option("--check", is_flag=True, help="Only check for an update, don't apply it.")
@click.option(
    "--server",
    "server_url",
    default=None,
    help="One-time switch: repoint hc's own git checkout, and (unless --no-registry) the "
    "hermes registry clone, at this SoftServe server's base URL (e.g. http://host:23232 "
    "or ssh://host:23231 — not a specific repo path) before checking/updating. For an "
    "http(s) server, a SoftServe access token is embedded automatically into each repo's "
    "URL — from --token if given, else /etc/hermes-cli/softserve_token.",
)
@click.option(
    "--token",
    default=None,
    help="SoftServe access token to use with --server for an http(s) server, instead of the "
    "one already configured via `hc init --softserve-token` (or its prompt).",
)
@click.option(
    "--no-registry",
    is_flag=True,
    help="With --server, only switch hc's own checkout — leave the hermes registry clone's origin alone.",
)
def self_update(check: bool, server_url: str | None, token: str | None, no_registry: bool) -> None:
    """Update hc itself from its own git checkout (separate from `hc pull`, which updates the registry)."""
    root = selfupdate.repo_root()

    if server_url:
        resolved_token = _switch_repo_origin(root, softserve.repo_url(server_url, "hermes-cli"), token)
        if not no_registry:
            _switch_registry_origin(server_url, resolved_token)

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
main.add_command(route_sync)
main.add_command(secrets)


if __name__ == "__main__":
    main()
