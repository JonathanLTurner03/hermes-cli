# hc — Hermes CLI

`hc` is a fleet-management CLI. It runs on each host in your fleet, reads a small per-host identity file, pulls configuration from a shared "hermes" git registry, and applies it locally: starting/stopping Docker Compose services and rendering/enabling systemd mount units. Nothing about *what* runs on a host is kept on the host itself — it all lives in the registry and gets applied via `hc`.

This README covers the CLI. For how the registry repo itself is laid out — adding a new service, adding a mount spec, secrets handling — see that repo's own README.

## Install

Prerequisites: Docker with the `docker compose` plugin (not the standalone `docker-compose` binary), Python 3.10+.

```
git clone <this repo>
cd hermes-cli
./install.sh
```

`install.sh` creates a `.venv`, installs `hc` into it in editable mode, and symlinks it to `/usr/local/bin/hc`. Don't run the whole script with `sudo` — it checks for that and refuses; it prompts for elevation only for the final symlink step.

## First-time host setup

```
hc init <server-name> [--registry-path /opt/infra/hermes]
```

Writes `/etc/hermes-cli/config.yml` with the server name and the local path of your registry clone. `<server-name>` must match a directory name in the registry (`<registry_path>/<server-name>/`). Every other `hc` command reads this file first and fails immediately if it's missing.

Writing it requires root — you don't need to type `sudo` yourself, though. `init` and the mount commands that write to `/etc` (`mount sync`/`enable`/`disable`) self-elevate: if not already running as root, they re-exec themselves under `sudo`, which prompts for your password exactly as if you'd typed `sudo hc ...`. This only works with a tty attached (interactive use); from a script or cron job with no terminal to prompt on, run those commands with `sudo` explicitly. Read-only commands (`services`, `where`, `status`, `mount status`) never need root and never prompt.

```
hc pull
```

Git-pulls the registry clone at the configured path. This only updates the *registry* (compose/mount specs) — it does not update `hc` itself. For that, see `hc self-update` below.

## Updating `hc` itself

```
hc self-update [--check]
```

`hc pull` only syncs the registry clone; it has no way to know about — let alone apply — changes to `hc`'s own source. `hc self-update` is the separate command for that: it finds its own git checkout (via the editable install's module path, so no extra config is needed), fetches, and compares `HEAD` against the tracking branch. With no changes upstream, it reports "up to date" and exits. If there's an update, `--check` reports it without applying anything; without `--check`, it fast-forwards the checkout (`git pull --ff-only`, refusing if the checkout has uncommitted local changes) and reruns `install.sh` to pick up any dependency changes. Requires the checkout to be on a branch with a configured upstream (i.e. cloned normally, not detached).

## Shell completion

`hc` uses Click's built-in completion support, so command and option names complete for free. `<service>` and mount `<name>` arguments complete too, dynamically — they read the registry the same way the command itself would, so suggestions are always live (e.g. `hc mount enable <TAB>` only offers registry-managed specs, since pools always refuse; `hc mount status <TAB>` offers both).

One-time setup, per shell:

```
# bash — add to ~/.bashrc
eval "$(_HC_COMPLETE=bash_source hc)"

# zsh — add to ~/.zshrc
eval "$(_HC_COMPLETE=zsh_source hc)"

# fish — add to ~/.config/fish/completions/hc.fish
_HC_COMPLETE=fish_source hc | source
```

Dynamic completions shell out to `hc` itself on every `<TAB>`, so they only work once `hc init` has been run (before that, they just fail silently and offer nothing — no config to read yet).

## Compose commands

| Command | What it does |
|---|---|
| `hc services` | List services registered for this host |
| `hc where <service>` | Print the resolved path to a service's directory (debug helper) |
| `hc up <service>` | `docker compose up -d`. Refuses to start if the service declares `.env.secrets` as an `env_file` but none is present on disk. Creates any network the compose file marks `external: true` before starting. |
| `hc down <service>` | `docker compose down` |
| `hc restart <service>` | `docker compose restart` |
| `hc logs <service> [-f]` | `docker compose logs`, `-f` to follow |
| `hc status [service]` | `docker compose ps` for one service, or every registered service if omitted |

## Mount commands

`hc mount` manages systemd `.mount` units the same way the compose commands manage containers: specs live in the registry, `hc` renders and applies them to the host.

| Command | What it does |
|---|---|
| `hc mount sync [--apply] [--force] [--restart-docker]` | Renders every registered mount spec to a systemd unit file and regenerates the `docker.service` drop-in that makes Docker wait on all of them at boot. Prints a diff of added/changed/removed units. Never enables or starts anything by itself unless `--apply` is passed. Refuses to delete the unit file for a mount that's still active unless `--force` is passed (which stops it first). If the drop-in changed, tells you to re-run with `--restart-docker` to actually bounce Docker — that restarts every container on the host, so it's never automatic. |
| `hc mount enable <name>` | `systemctl enable --now` the mount. Refuses if its `depends_on` mount isn't active yet, with a clear error instead of letting systemd fail silently. |
| `hc mount disable <name>` | `systemctl disable --now` the mount. Warns (doesn't block) if other registered mounts depend on it. |
| `hc mount status [name]` | No argument: table of every registered mount for this host (plus every storage pool declared in `pools.yml`, which isn't registry-managed but is always shown) — systemd state, whether it's *actually* mounted (`findmnt`, independent ground truth), what it depends on, free space/use%. Flags in red if systemd thinks something's active but it isn't actually mounted. Also warns if the `docker.service` drop-in on disk is stale relative to what the registry currently says it should be. With an argument: detail view for one mount plus its last 20 journal lines. |

Typical flow for a new or changed mount: edit the registry, `hc pull`, `hc mount sync` to review the diff, then `hc mount enable <name>` (or re-run `sync --apply` to enable everything just added/changed). To remove one: `hc mount disable <name>` first, delete its spec from the registry, `hc pull`, then `hc mount sync`.

Storage pools (e.g. `mnt-pool`) are intentionally not registry-managed — each lives in `/etc/fstab` on the host. `hc` only ever references them by name/mount point via an optional `pools.yml` at the server root (a host can declare more than one) and will reject a registry mount spec that reuses a declared pool's name. See [mount-feature-doc.md](mount-feature-doc.md) for the full rationale.

## How it's organized

Each feature (compose, mount) is a self-contained subpackage: its own CLI commands, its own registry-path resolution, its own wrapper around the underlying tool (`docker`/`systemd`). See [CLAUDE.md](CLAUDE.md) for the exact layout and conventions if you're extending this — it's written for an AI coding agent working in this repo, but it's a reasonable map for a human too.
