"""Click commands for `hc mount`. Attached to the top-level `main` group as
the `mount` subgroup by hermes_cli.cli.
"""
from __future__ import annotations

import click

from .. import config
from . import registry, systemd


@click.group()
def mount() -> None:
    """Manage registry-defined systemd mount units."""


def _load(cfg: dict) -> tuple[dict[str, registry.Pool], list[registry.MountSpec]]:
    pools = registry.load_pools(cfg)
    pools_by_name = {pool.name: pool for pool in pools}
    specs = registry.load_specs(cfg, set(pools_by_name))
    return pools_by_name, specs


def _dep_unit(specs: list[registry.MountSpec], pools_by_name: dict[str, registry.Pool], depends_on: str) -> str:
    if depends_on in pools_by_name:
        return systemd.escape_unit_name(pools_by_name[depends_on].target)
    return systemd.escape_unit_name(registry.find_spec(specs, depends_on).target)


def _enable_mount(
    specs: list[registry.MountSpec], pools_by_name: dict[str, registry.Pool], name: str
) -> None:
    if name in pools_by_name:
        raise registry.MountError(
            f"'{name}' is unmanaged by hc (lives in /etc/fstab) — "
            f"bring it up with `mount -a` or by editing fstab directly."
        )
    spec = registry.find_spec(specs, name)
    unit = systemd.escape_unit_name(spec.target)
    if spec.depends_on:
        dep_unit = _dep_unit(specs, pools_by_name, spec.depends_on)
        if not systemd.is_active(dep_unit):
            raise registry.MountError(
                f"cannot enable '{name}': its dependency '{spec.depends_on}' ({dep_unit}) isn't active"
            )
    systemd.enable_now(unit)


def _apply_pending(
    specs: list[registry.MountSpec], pools_by_name: dict[str, registry.Pool], names: list[str]
) -> None:
    """Enable `names` in dependency order, so a chain added in the same sync run applies cleanly."""
    pending = list(dict.fromkeys(names))
    while pending:
        progressed = False
        for name in list(pending):
            spec = registry.find_spec(specs, name)
            if spec.depends_on and spec.depends_on in pending:
                continue
            click.echo(f"enabling {name}")
            _enable_mount(specs, pools_by_name, name)
            pending.remove(name)
            progressed = True
        if not progressed:
            raise registry.MountError(f"cannot apply {pending}: unresolved dependency ordering")


@mount.command("sync")
@click.option("--apply", "apply_", is_flag=True, help="Enable/start added or changed mounts after syncing.")
@click.option(
    "--force",
    is_flag=True,
    help="Remove unit files for mounts no longer in the registry, even if currently active.",
)
@click.option(
    "--restart-docker",
    is_flag=True,
    help="Restart docker.service if the wait-for-mounts drop-in changed.",
)
def mount_sync(apply_: bool, force: bool, restart_docker: bool) -> None:
    """Render registry mount specs to systemd units and regenerate the docker.service drop-in."""
    cfg = config.load_config()
    pools_by_name, specs = _load(cfg)

    unit_names = {name: systemd.escape_unit_name(pool.target) for name, pool in pools_by_name.items()}
    for spec in specs:
        unit_names[spec.name] = systemd.escape_unit_name(spec.target)

    rendered = {}
    for spec in specs:
        source_ref = f"hermes/{cfg['server']}/mounts/{spec.name}.yml"
        rendered[unit_names[spec.name]] = systemd.render_unit(spec, unit_names, source_ref)

    diff = systemd.sync_units(rendered, force=force)
    for unit in diff.added:
        click.echo(f"+ {unit}")
    for unit in diff.changed:
        click.echo(f"~ {unit}")
    for unit in diff.removed:
        click.echo(f"- {unit}")
    if not (diff.added or diff.changed or diff.removed):
        click.echo("no changes")

    dropin_changed = systemd.sync_docker_dropin(sorted(unit_names.values()))
    systemd.daemon_reload()

    if dropin_changed:
        if restart_docker:
            systemd.restart_unit("docker.service")
            click.echo("docker.service restarted to pick up mount changes")
        else:
            click.echo("drop-in updated, restart docker to apply: hc mount sync --restart-docker")

    if apply_:
        unit_to_name = {unit: name for name, unit in unit_names.items()}
        pending = [unit_to_name[unit] for unit in diff.added + diff.changed]
        _apply_pending(specs, pools_by_name, pending)


@mount.command("enable")
@click.argument("name")
def mount_enable(name: str) -> None:
    """Enable and start a registered mount."""
    cfg = config.load_config()
    pools_by_name, specs = _load(cfg)
    _enable_mount(specs, pools_by_name, name)


@mount.command("disable")
@click.argument("name")
def mount_disable(name: str) -> None:
    """Disable and stop a registered mount."""
    cfg = config.load_config()
    pools_by_name, specs = _load(cfg)
    if name in pools_by_name:
        raise registry.MountError(f"'{name}' is unmanaged by hc — edit /etc/fstab directly.")
    spec = registry.find_spec(specs, name)
    unit = systemd.escape_unit_name(spec.target)
    dependents = [s.name for s in specs if s.depends_on == name]
    if dependents:
        click.echo(
            f"warning: {', '.join(dependents)} depend on '{name}' — disabling it may break them",
            err=True,
        )
    systemd.disable_now(unit)


def _status_row(name: str, unit: str, target: str, depends_on: str | None) -> dict:
    state = systemd.show(unit, ["ActiveState"])["ActiveState"] or "unknown"
    fs = systemd.findmnt(target)
    mounted = fs is not None
    usage = systemd.disk_usage(target) if mounted else None
    return {
        "name": name,
        "unit": unit,
        "target": target,
        "state": state,
        "mounted": mounted,
        "depends_on": depends_on or "-",
        "free": usage[0] if usage else "-",
        "pcent": usage[1] if usage else "-",
    }


def _print_table(rows: list[dict]) -> None:
    click.echo(f"{'NAME':<24}{'STATE':<9}{'MOUNTED':<9}{'DEPENDS_ON':<16}{'FREE':<9}{'USE%'}")
    for row in rows:
        mounted_str = "yes" if row["mounted"] else "no"
        line = (
            f"{row['name']:<24}{row['state']:<9}{mounted_str:<9}"
            f"{row['depends_on']:<16}{row['free']:<9}{row['pcent']}"
        )
        mismatch = row["state"] == "active" and not row["mounted"]
        click.secho(line, fg="red" if mismatch else None)
        if mismatch:
            click.secho(
                f"  ! systemd reports '{row['name']}' active but it isn't actually mounted", fg="red"
            )


def _print_detail(row: dict) -> None:
    click.echo(f"name:        {row['name']}")
    click.echo(f"unit:        {row['unit']}")
    click.echo(f"target:      {row['target']}")
    click.echo(f"state:       {row['state']}")
    click.echo(f"mounted:     {'yes' if row['mounted'] else 'no'}")
    click.echo(f"depends_on:  {row['depends_on']}")
    click.echo(f"free:        {row['free']}")
    click.echo(f"use%:        {row['pcent']}")


@mount.command("status")
@click.argument("name", required=False)
def mount_status(name: str | None) -> None:
    """Show status for one registered mount, or a table of every mount registered for this host."""
    cfg = config.load_config()
    pools_by_name, specs = _load(cfg)

    if name:
        if name in pools_by_name:
            pool = pools_by_name[name]
            unit = systemd.escape_unit_name(pool.target)
            row = _status_row(pool.name, unit, pool.target, None)
        else:
            spec = registry.find_spec(specs, name)
            unit = systemd.escape_unit_name(spec.target)
            row = _status_row(spec.name, unit, spec.target, spec.depends_on)
        _print_detail(row)
        click.echo()
        click.echo("── journal (last 20 lines) ──")
        click.echo(systemd.journal_tail(row["unit"]))
        return

    rows = [
        _status_row(pool.name, systemd.escape_unit_name(pool.target), pool.target, None)
        for pool in pools_by_name.values()
    ]
    for spec in specs:
        unit = systemd.escape_unit_name(spec.target)
        rows.append(_status_row(spec.name, unit, spec.target, spec.depends_on))
    _print_table(rows)

    unit_names = [systemd.escape_unit_name(pool.target) for pool in pools_by_name.values()]
    unit_names += [systemd.escape_unit_name(s.target) for s in specs]
    expected_dropin = systemd.render_docker_dropin(sorted(unit_names))
    actual_dropin = (
        systemd.DOCKER_DROPIN_PATH.read_text() if systemd.DOCKER_DROPIN_PATH.exists() else None
    )
    if actual_dropin != expected_dropin:
        click.secho(
            "warning: docker.service drop-in is stale relative to the registry — run `hc mount sync`",
            fg="yellow",
        )
