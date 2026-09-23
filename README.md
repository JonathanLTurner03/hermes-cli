# hc — Hermes CLI

> [!WARNING]
> **Personal project — use at your own risk.** This is a side project I built to save myself time managing my own small homelab, not a maintained tool for general use. It leans heavily on AI as a development tool, because I don't have the spare time to hand-write and hand-test all of this myself on top of a full-time job and other projects. It's built and tested against my own specific setup and workflows — there's no unit test suite, no CI, and no guarantee any of it behaves correctly outside the exact scenarios I've personally exercised. If you use this, read the code first, understand what a command actually does before running it against anything you care about, and don't expect support.

`hc` is a fleet-management CLI. It runs on each host in your fleet, reads a small per-host identity file, pulls configuration from a shared "hermes" git registry, and applies it locally: starting/stopping Docker Compose services and rendering/enabling systemd mount units. Nothing about *what* runs on a host is kept on the host itself — it all lives in the registry and gets applied via `hc`.

This README covers the CLI. For how the registry repo itself is laid out — adding a new service, adding a mount spec, secrets handling — see that repo's own README.

## Install

Prerequisites: Docker with the `docker compose` plugin (not the standalone `docker-compose` binary), Python 3.10+.

```
git clone <this repo>
cd hermes-cli
./install.sh
```

`install.sh` creates a `.venv`, installs `hc` into it in editable mode, and symlinks it to `/usr/local/bin/hc`. Don't run the whole script with `sudo` — it checks for that and refuses; it prompts for elevation only for the final symlink step. It also sets up shell completion (see below) for `bash`/`zsh`/`fish` based on `$SHELL`, idempotently — safe to rerun on every `hc self-update`.

## First-time host setup

```
hc init <server-name> [--registry-path /opt/infra/hermes] [--github-token <token>]
```

Writes `/etc/hermes-cli/config.yml` with the server name and the local path of your registry clone. `<server-name>` must match a directory name in the registry (`<registry_path>/<server-name>/`). Every other `hc` command reads this file first and fails immediately if it's missing.

If run interactively (a real terminal, not a script) and no token is already configured, it also offers to set up the GitHub token `hc update`'s version-pin flow needs to open pull requests (see below) — prompts for it (input hidden) with a link to create one, skippable if you don't need it yet. Pass `--github-token <token>` to set it non-interactively instead (e.g. from a provisioning script), or just skip the prompt and configure it later — see "Version-pinned updates" for where the file goes and what access the token needs.

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

`install.sh` sets this up automatically based on `$SHELL` — nothing to do beyond opening a new shell (or `source`ing your rc file) after installing. It's idempotent, so rerunning `install.sh` (e.g. after `hc self-update`) won't duplicate the line.

If you ever need to add it by hand (unrecognized `$SHELL`, a different shell setup than the one `install.sh` detected, etc.):

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
| `hc up <service>` | `docker compose up -d`. Refuses to start if the service declares `.env.secrets` as an `env_file` but none is present on disk. Decrypts `secrets.enc.yaml` (if the service has one — see "Secrets commands" below) fresh via `sops`. Creates any network the compose file marks `external: true` before starting. |
| `hc down <service>` | `docker compose down` |
| `hc restart <service>` | `docker compose restart` |
| `hc update <service\|all> [--check]` | `docker compose pull` then `up -d`. For a moving tag (`:latest`, a floating `:6`, etc.), `up -d` alone won't notice a new build exists — it just reuses whatever's cached locally under that tag — so this pulls first to actually check the tag's current digest against the registry, then recreates only the containers whose image (or other config) changed. Same secrets/network preconditions as `up`. Requires an explicit target: a service name, or the literal `all` to update every registered service — bare `hc update` refuses rather than quietly updating the whole host, unlike `hc status`'s "no args means all". `--check` still pulls for real (so the answer reflects the registry's current state) but never recreates anything — just reports `up to date` or `update available` per target. For a single named service (not `all`) pinned to a version-shaped tag, see "Version-pinned updates" below — it behaves differently. |
| `hc logs <service> [-f]` | `docker compose logs`, `-f` to follow |
| `hc status [service]` | `docker compose ps` for one service, or every registered service if omitted |

### Version-pinned updates

If a service's `image:` tag is version-shaped (at least major.minor, all-numeric, optionally `v`-prefixed — `6.0`, `6.3.0.45`, `v1.50.1`; not `:latest` or a bare floating `:6`) and the image is on a supported registry, `hc update <service>` checks that registry for tags newer than the current one instead of just re-pulling the same tag (which would never find anything — a fixed version tag doesn't move). `all` never does this — bulk updates stay non-interactive.

- **Newer versions exist**: prints them and prompts `update to which version? (or q to quit)`. Picking one rewrites the `image:` tag in the registry's `docker-compose.yml` — only that line changes, comments/formatting/everything else in the file is untouched — commits it on a throwaway branch (`hc-update/<service>-<tag>`), pushes the branch, and **opens a pull request via the GitHub API**. It does not merge anything itself — a human reviews and merges the PR on GitHub, same "branch, then a person approves" workflow this project's own development follows (see `CLAUDE.md`). Needs a GitHub token at `/etc/hermes-cli/github_token` on the host (root-readable; set up via `hc init`'s prompt, its `--github-token` flag, or by hand — checked *before* touching git at all, so a missing token never leaves a half-made branch behind) and the registry's `origin` remote to actually be a `github.com` URL. Refuses up front if the registry clone has uncommitted changes already sitting there (won't sweep something unrelated into its commit) or can't be fast-forwarded to match origin first (avoids branching from a stale base). Either way, it does **not** pull/recreate the container in the same run — once the PR is merged, `hc pull && hc update <service>` (on this host or any other) actually applies it. Container disruption stays a deliberate, separate step even though opening the PR is now automatic.
- **No newer versions**: reports `up to date` and (unless `--check`) still falls through to a plain pull + recreate, in case the same tag was re-pushed with a fix.
- **Not version-shaped at all** (`:latest`, a bare floating `:6`): silently falls back to the ordinary pull-and-recreate behavior above — no error, no extra output, this is the common case.
- **Version-shaped, but on an unsupported registry**: reports that it can't check this one (names the registry host) and still falls back to the ordinary flow, rather than failing outright.
- **`--check`**: reports `up to date` or lists the newer versions, but never prompts and never touches Docker — the answer comes entirely from the registry's tag list.

Supports **Docker Hub** and **ghcr.io** (GitHub Container Registry) — anything else reports as unsupported and falls back, per above, rather than guessing at a different API shape. Only handles compose files with exactly one service (this registry's actual usage so far); anything else errors clearly.

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

## Secrets commands

`hc secrets` handles per-service secrets encrypted with [sops](https://github.com/getsops/sops) (backed by [age](https://github.com/FiloSottile/age)) instead of the out-of-band `.env.secrets` file — see the hermes registry's README for the full setup (generating an age keypair, adding it to `.sops.yaml`, referencing the result from a compose file). `hc` itself never touches age keys or `.sops.yaml` — both are entirely sops/age's own territory; `hc` only shells out to `sops` to decrypt at deploy time and to launch an edit session.

| Command | What it does |
|---|---|
| `hc secrets edit <service>` | Opens `<service>/secrets.enc.yaml` in `$EDITOR` via `sops` — decrypted for editing, re-encrypted on save. Creates the file if it doesn't exist yet, per whichever `.sops.yaml` rule matches its path. |
| `hc secrets sync [service]` | Decrypts `<service>/secrets.enc.yaml` (every registered service, if none named) and writes each top-level key to its own file under `<service>/secrets/<name>`, mode `600`. Runs automatically as part of `hc up`/`hc update` — this is a standalone entry point for re-syncing after rotating a value, or for debugging decryption without touching any container. A service with no `secrets.enc.yaml` is silently skipped. |

`hc up`/`hc update` call the same decrypt-and-write step automatically before starting or recreating a container, right after the existing `.env.secrets` presence check — so a service with a `secrets.enc.yaml` always gets a fresh decrypt on every deploy, with nothing else to remember on the host beyond having run `age-keygen` once and having a matching `.sops.yaml` entry.

## How it's organized

Each feature (compose, mount, secrets) is a self-contained subpackage: its own CLI commands, its own registry-path resolution, its own wrapper around the underlying tool (`docker`/`systemd`/`sops`). See [CLAUDE.md](CLAUDE.md) for the exact layout and conventions if you're extending this — it's written for an AI coding agent working in this repo, but it's a reasonable map for a human too.
