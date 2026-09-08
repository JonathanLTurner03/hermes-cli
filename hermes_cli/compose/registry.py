"""Path resolution for compose services within the hermes registry.

Registry layout:
    <registry_path>/<server>/<service>/docker-compose.yml
    <registry_path>/<server>/<service>/.env             (config, tracked)
    <registry_path>/<server>/<service>/.env.secrets      (secrets, NOT tracked)
"""
from __future__ import annotations

from pathlib import Path

import yaml
from ruamel.yaml import YAML

from .. import registry
from . import imageref


def service_path(config: dict, service: str) -> Path:
    path = registry.server_root(config) / service
    if not path.exists():
        raise registry.RegistryError(
            f"No service '{service}' found for server '{config['server']}' "
            f"(expected {path})"
        )
    return path


def compose_file(config: dict, service: str) -> Path:
    path = service_path(config, service) / "docker-compose.yml"
    if not path.exists():
        raise registry.RegistryError(f"No docker-compose.yml in {path.parent}")
    return path


def list_services(config: dict) -> list[str]:
    root = registry.server_root(config)
    return sorted(
        p.name for p in root.iterdir()
        if p.is_dir() and (p / "docker-compose.yml").exists()
    )


def secrets_file(config: dict, service: str) -> Path | None:
    """Path to the service's .env.secrets, or None if it doesn't exist."""
    path = service_path(config, service) / ".env.secrets"
    return path if path.exists() else None


def expects_secrets(config: dict, service: str) -> bool:
    """Whether this service's compose file declares .env.secrets as an env_file."""
    compose_path = compose_file(config, service)
    return ".env.secrets" in compose_path.read_text()


def host_env_file(config: dict) -> Path | None:
    path = registry.server_root(config) / ".env"
    return path if path.exists() else None


def host_secrets_file(config: dict) -> Path | None:
    path = registry.server_root(config) / ".env.secrets"
    return path if path.exists() else None


def _single_service(compose_path: Path) -> tuple[str, dict]:
    """(service name, service mapping) for a compose file's one and only service.

    Raises RegistryError if the file doesn't define exactly one service —
    version-tag rewriting only handles the common single-service-per-file
    case this registry actually uses; anything else needs a hand edit.
    """
    data = yaml.safe_load(compose_path.read_text()) or {}
    services = data.get("services") or {}
    if len(services) != 1:
        raise registry.RegistryError(
            f"{compose_path}: expected exactly one service, found {len(services)}"
        )
    name = next(iter(services))
    return name, services[name]


def current_image(compose_path: Path) -> str:
    """The `image:` value of a compose file's one and only service."""
    name, service = _single_service(compose_path)
    if "image" not in service:
        raise registry.RegistryError(f"{compose_path}: service '{name}' has no 'image:' key")
    return str(service["image"])


def rewrite_image_tag(compose_path: Path, new_tag: str) -> tuple[str, str, str]:
    """Rewrite the single service's image tag in place.

    Only the exact line containing `image:` is touched — everything else in
    the file (comments, formatting, key order) is left byte-for-byte
    unchanged. Uses ruamel.yaml's round-trip loader purely to *locate* that
    line (via its line/column tracking); the actual edit is a plain text
    substitution on that one line, not a full YAML re-dump, so there's no
    risk of ruamel reformatting anything else in the file.

    Returns (service_name, old_image, new_image).
    """
    yaml_rt = YAML(typ="rt")
    with compose_path.open() as f:
        data = yaml_rt.load(f)

    services = data.get("services") or {}
    if len(services) != 1:
        raise registry.RegistryError(
            f"{compose_path}: expected exactly one service, found {len(services)}"
        )
    name = next(iter(services))
    service = services[name]
    if "image" not in service:
        raise registry.RegistryError(f"{compose_path}: service '{name}' has no 'image:' key")

    old_image = str(service["image"])
    base, _old_tag = imageref.split_image_ref(old_image)
    new_image = f"{base}:{new_tag}"

    line_idx, _col = service.lc.value("image")
    lines = compose_path.read_text().splitlines(keepends=True)
    if old_image not in lines[line_idx]:
        raise registry.RegistryError(
            f"{compose_path}:{line_idx + 1}: expected to find '{old_image}' on this line — "
            f"refusing to guess, edit the file by hand"
        )
    lines[line_idx] = lines[line_idx].replace(old_image, new_image, 1)
    compose_path.write_text("".join(lines))

    return name, old_image, new_image


def external_networks(config: dict, service: str) -> list[str]:
    """Names of networks this service's compose file declares as external: true."""
    compose_path = compose_file(config, service)
    data = yaml.safe_load(compose_path.read_text()) or {}
    nets = data.get("networks", {}) or {}
    return [
        name for name, net_cfg in nets.items()
        if isinstance(net_cfg, dict) and net_cfg.get("external")
    ]
