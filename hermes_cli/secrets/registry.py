"""Path resolution for sops-encrypted per-service secrets within the hermes registry.

Registry layout:
    <registry_path>/<server>/<service>/secrets.enc.yaml   (sops+age encrypted, tracked)
    <registry_path>/<server>/<service>/secrets/<name>      (decrypted, NOT tracked)

The decrypted output directory sits right next to secrets.enc.yaml, in the
same spot compose's own .env.secrets already lives (see compose/registry.py)
rather than some shared path outside the registry clone — the registry's own
.gitignore already carves out `secrets/*` (keeping `.gitkeep`) for exactly
this, and it means no root-owned directory needs bootstrapping outside the
registry: whatever user can already write .env.secrets into a service
directory can write here too. A compose file references the result with a
path relative to itself (`file: ./secrets/<name>`), which `docker compose -f
<path> ...` resolves relative to the compose file's own directory.
"""
from __future__ import annotations

from pathlib import Path

from .. import registry
from . import sops


class SecretsError(SystemExit):
    pass


def secrets_enc_file(config: dict, service: str) -> Path | None:
    """Path to the service's secrets.enc.yaml, or None if it has none."""
    path = registry.server_root(config) / service / "secrets.enc.yaml"
    return path if path.exists() else None


def expects_secrets(config: dict, service: str) -> bool:
    return secrets_enc_file(config, service) is not None


def secrets_dir(config: dict, service: str) -> Path:
    """Where decrypted secret files get written for this service."""
    return registry.server_root(config) / service / "secrets"


def sync(config: dict, service: str) -> Path | None:
    """Decrypt this service's secrets.enc.yaml (if any) and write each
    top-level key to its own file under secrets_dir(), mode 600.

    Returns the directory written to, or None if the service has no
    secrets.enc.yaml at all. Every value is written as-is via str() — sops
    round-trips YAML scalars (strings, numbers, booleans) fine for the
    plain API-key/token/password use case this is built for; anything
    needing structured (list/dict) secret values isn't supported here.

    Re-decrypts and overwrites unconditionally on every call rather than
    diffing against what's already on disk — these are small files and this
    only runs at deploy time (hc up/update), so the extra sops invocation
    isn't worth the complexity of a staleness check.
    """
    enc_path = secrets_enc_file(config, service)
    if enc_path is None:
        return None

    data = sops.decrypt(enc_path)
    out_dir = secrets_dir(config, service)
    out_dir.mkdir(parents=True, exist_ok=True)
    for key, value in data.items():
        out_path = out_dir / key
        out_path.write_text(str(value))
        out_path.chmod(0o600)
    return out_dir
