# Secrets Management: sops + age + hc

## Why

Homelab services (Jellyfin, Hermes/hc-managed stack, etc.) need JWTs, API
keys, and similar static secrets available to containers at deploy time.
Requirements:

- Local-only, no external service dependency, no server process to run,
  patch, or unseal.
- Secrets tracked in git alongside the `hermes` compose registry, so
  changes are versioned and diffable like everything else in the fleet.
- Per-host scoping: a compromised host should only be able to decrypt
  its own secrets, not every other host's.
- Secrets should never land in `docker inspect` output, `/proc/<pid>/environ`,
  or any child process's environment. File-based delivery only.

Evaluated OpenBao (Vault fork) first but decided against it — running a
server, dealing with unsealing after restarts, and building an AppRole
auth flow is more moving parts than this actually needs for a handful of
static, hand-rotated secrets. sops + age gets equivalent security
properties (encrypted at rest, per-host scoped decryption) with no daemon
and no auth flow: just a private key file per host.

## What it should do

1. Secrets for each service live in an encrypted YAML file inside that
   service's directory in the `hermes` registry repo, e.g.
   `services/jellyfin/secrets.enc.yaml`.
2. Each host has its own `age` keypair. Only the private key ever leaves
   the host it was generated on — it never leaves.
3. `.sops.yaml` at the repo root maps path patterns to a list of `age`
   public keys (recipients) allowed to decrypt that path. Per-service
   scoping is done by listing only the relevant hosts' public keys against
   that service's path.
4. On deploy, `hc` decrypts the relevant `secrets.enc.yaml` using the
   host's local private key, writes each secret out to its own file under
   the Docker secrets directory (e.g.
   `/opt/infra/hermes/secrets/<service>/<name>`, mode `600`), and the
   compose file references those as file-based Docker secrets — mounted
   into the container at `/run/secrets/<name>`, never injected as env vars.
5. Editing a secret is done via `sops services/<name>/secrets.enc.yaml`,
   which decrypts to `$EDITOR`, and re-encrypts on save. No separate
   encrypt/decrypt step to remember.

## How it works

### age

Public-key encryption tool, purpose-built for this kind of thing (like a
much simpler alternative to GPG). Each host gets a keypair:

```
age-keygen -o ~/.config/sops/age/keys.txt
```

This prints (and embeds as a comment) the public key, `age1...`. The
private key (`AGE-SECRET-KEY-1...`) stays in that file, `chmod 600`,
never copied off the host it was generated on. age keys are unrelated to
SSH keys — no reuse, no bridging needed (though `ssh-to-age` exists if
ever wanted).

### sops

Wraps file encryption around age (or other backends). Encrypts only the
*values* in a YAML/JSON file, leaving keys in plaintext — so `git diff`
shows which secret changed without exposing anything. A file can be
encrypted against multiple age public keys at once; sops stores one
wrapped copy of the file's data key per recipient in a `sops:` block at
the bottom of the file, so any of those recipients' private keys can
decrypt the same file independently.

Example encrypted file:

```yaml
api_key: ENC[AES256_GCM,data:Xk3m...,tag:...,type:str]
admin_token: ENC[AES256_GCM,data:pQ7z...,tag:...,type:str]
sops:
    age:
        - recipient: age1qy8f...atlantis_pubkey
          enc: |
            -----BEGIN AGE ENCRYPTED FILE-----
            ...
            -----END AGE ENCRYPTED FILE-----
        - recipient: age1zx9c...desktop_pubkey
          enc: |
            -----BEGIN AGE ENCRYPTED FILE-----
            ...
            -----END AGE ENCRYPTED FILE-----
    version: 3.8.1
```

### .sops.yaml (repo root)

Defines recipients per path, matched top-down:

```yaml
creation_rules:
  - path_regex: services/jellyfin/.*\.enc\.yaml$
    age: age1qy8f...atlantis_pubkey,age1zx9c...desktop_pubkey

  - path_regex: services/hermes-db/.*\.enc\.yaml$
    age: age1qy8f...atlantis_pubkey,age1zx9c...desktop_pubkey,age1mw2p...delphi_pubkey

  - path_regex: .*\.enc\.yaml$
    age: age1zx9c...desktop_pubkey
```

### Key distribution

Only public keys move between machines (they're not secret). Pulled over
Tailscale/Headscale, e.g.:

```
ssh atlantis "age-keygen -y ~/.config/sops/age/keys.txt"
```

Paste the result into `.sops.yaml`, commit. Private keys never transit
the network.

Desktop (dev machine) holds its own key as a recipient on every file, so
secrets can always be edited from there via `sops`. Whether the desktop
also holds a copy of every host's private key is a tradeoff: convenient
for one-place editing/re-encryption, but makes the desktop's key file a
single point that can open every host's secrets — should be treated with
the same care as a universal SSH root key if done this way (disk
encryption, no cloud sync of `~/.config/sops`).

### Docker secrets delivery

Compose file references decrypted-and-written files, not env vars:

```yaml
services:
  jellyfin:
    secrets:
      - jellyfin_api_key
secrets:
  jellyfin_api_key:
    file: /opt/infra/hermes/secrets/jellyfin/api_key
```

Container sees it at `/run/secrets/jellyfin_api_key`. If an app only
reads config from env vars, bridge it in the entrypoint:

```
export API_KEY=$(cat /run/secrets/jellyfin_api_key)
```

### VS Code editing workflow

sops is a CLI tool, not VS Code-specific. Set:

```
export EDITOR="code --wait"
```

then `sops services/jellyfin/secrets.enc.yaml` from an integrated
terminal opens the decrypted content in VS Code; save and close the tab,
sops re-encrypts on exit. (`--wait` is required — without it `code`
returns immediately and sops thinks editing finished before it started.)

## What's needed from hc

- A way to declare, per service in the hermes registry, which
  `secrets.enc.yaml` file(s) apply and which keys map to which Docker
  secret names.
- A deploy-time step: decrypt via `sops -d`, write each key's value to
  its own file under the host's secrets directory, `chmod 600`, then
  proceed to `docker compose up` referencing those files.
- Optionally, a `hc secrets edit <service>` convenience wrapper around
  `sops services/<service>/secrets.enc.yaml`.
- No daemon, no persistent decrypted state — decrypt happens fresh each
  deploy, plaintext files written only to the secrets directory Docker
  reads from (not into `.env`, not passed as compose environment
  variables).