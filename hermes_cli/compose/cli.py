"""Click commands for compose-managed services. Attached to the top-level
`main` group (as flat `hc <cmd>` commands, not a `hc compose <cmd>` subgroup)
by hermes_cli.cli.
"""
from __future__ import annotations

import socket
from pathlib import Path

import click

from .. import config, registry_git
from . import docker, imageref, networks, registry, versioncheck


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


def _prompt_for_version(name: str, current_tag: str, newer: list[str]) -> str | None:
    """Interactive picker over `newer`. Returns the chosen tag, or None if the user quit."""
    click.echo(f"{name} is pinned to {current_tag}")
    click.echo(f"newer versions available: {', '.join(newer)}")
    while True:
        choice = click.prompt(f"update {name} to which version? (or q to quit)")
        if choice.lower() in ("q", "quit"):
            return None
        if choice in newer:
            return choice
        click.echo(f"'{choice}' isn't one of the offered versions — {', '.join(newer)} (or q to quit)")


def _update_one_versioned(cfg: dict, name: str, check: bool) -> bool:
    """Handle `hc update <name>` if it's pinned to a version-shaped tag on a
    supported registry (Docker Hub, ghcr.io).

    Returns True if this fully handled the command (caller should stop).
    Returns False if either the image isn't eligible for version-checking
    at all (the current tag isn't version-shaped — e.g. :latest, a bare
    floating :6), or it IS eligible but a real (non --check) run found no
    newer version — both cases fall through to the ordinary tag-agnostic
    pull-and-recreate flow below. --check stops either way rather than
    falling through, since it should never touch Docker at all when the
    registry alone already gives a definitive answer.

    A version-shaped tag on a registry hc doesn't know how to query (not
    Docker Hub or ghcr.io) also falls through — but reports why first,
    since that's a real gap worth knowing about, not a silent no-op.
    """
    compose_path = registry.compose_file(cfg, name)
    current_image = registry.current_image(compose_path)
    try:
        newer = versioncheck.check_for_newer(current_image)
    except versioncheck.UnsupportedRegistryError as exc:
        click.echo(f"{name}: {exc} — falling back to a plain update")
        return False
    if newer is None:
        return False

    current_tag = imageref.extract_tag(current_image)

    if not newer:
        click.echo(f"{name}: up to date ({current_tag})")
        return check

    if check:
        click.echo(f"{name}: update available — newer versions: {', '.join(newer)}")
        return True

    chosen = _prompt_for_version(name, current_tag, newer)
    if chosen is None:
        click.echo(f"{name}: cancelled, no changes made")
        return True

    registry_root = Path(cfg["registry_path"])
    base = registry_git.prepare(registry_root)

    _, old_image, new_image = registry.rewrite_image_tag(compose_path, chosen)
    branch = f"hc-update/{name}-{chosen}"
    message = (
        f"hc update: {name} {current_tag} -> {chosen}\n"
        f"\n"
        f"Image: {old_image} -> {new_image}\n"
        f"Applied automatically by `hc update {name}` on {socket.gethostname()} "
        f"(server: {cfg['server']})."
    )
    registry_git.commit_and_merge(registry_root, compose_path, branch, base, message)
    click.echo(f"{name}: committed and pushed ({current_tag} -> {chosen})")
    click.echo(
        f"run `hc update {name}` again to pull and apply it "
        f"(on another host: `hc pull && hc update {name}`)"
    )
    return True


@click.command()
@click.argument("service", required=False, shell_complete=_complete_service_or_all)
@click.option(
    "--check",
    is_flag=True,
    help="Only report whether an update is available for each target; never recreate anything.",
)
def update(service: str | None, check: bool) -> None:
    """Re-pull image(s) and recreate any container whose image actually changed.

    Requires an explicit target — a service name, or `all` for every
    registered service on this host. Bare `hc update` refuses rather than
    quietly updating everything: recreating every container on a host at
    once is a bigger blast radius than a missing argument should trigger by
    default (unlike e.g. `hc status`, where "no args means all" is harmless).

    For a moving tag (:latest, a floating :6, etc.) that's already cached
    locally, `up` alone won't notice a new build exists — this pulls first
    so the tag's current digest is actually checked against the registry.

    --check still pulls for real (so the check reflects the registry's
    current state, not a stale local cache) but never recreates a
    container — same "real I/O, no service disruption" trade-off as
    `hc self-update --check`'s `git fetch`.

    For a single named service (not `all`) pinned to a version-shaped tag
    (at least major.minor, e.g. 6.0, 6.3.0.45, or v1.50.1 — not :latest or
    a bare floating :6) on a Docker Hub or ghcr.io image, this checks the
    registry for newer versions instead of just re-pulling the same tag.
    If any exist, it prompts you to pick one, rewrites the tag in the
    registry's docker-compose.yml, and commits + pushes that change itself
    (on a throwaway branch, fast-forward merged back and deleted once the
    push succeeds — see registry_git.py). It still does NOT pull/recreate
    the container in the same run: re-run `hc update <service>` (this host
    already has the new tag; other hosts need `hc pull` first) to actually
    apply it — container disruption stays a deliberate, separate step even
    though the registry write is now automatic. Refuses if the registry
    clone has uncommitted changes already sitting there, or can't be
    fast-forwarded to match origin first — won't sweep unrelated changes
    into its commit or risk a messy non-fast-forward push. If none exist,
    it falls back to the plain flow above. If the tag IS version-shaped
    but the image is on some other registry, it says so (only Docker Hub
    and ghcr.io are supported right now) and still falls back rather than
    failing outright. `all` never triggers any of this — bulk updates stay
    non-interactive.
    """
    if service is None:
        raise SystemExit(
            "hc update needs a target — specify a service name, or `hc update all` "
            "to update every registered service on this host"
        )
    cfg = config.load_config()

    if service != "all" and _update_one_versioned(cfg, service, check):
        return

    targets = registry.list_services(cfg) if service == "all" else [service]
    for name in targets:
        compose_path = _ensure_ready(cfg, name)
        click.echo(f"── {name} ──")
        if check:
            if docker.check(compose_path):
                click.echo(f"{name}: update available")
            else:
                click.echo(f"{name}: up to date")
        else:
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
