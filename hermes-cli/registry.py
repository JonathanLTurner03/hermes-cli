"""Path resolution within the hermes registry.

Registry layout:
    <registry_path>/<server>/<service>/docker-compose.yml
    <registry_path>/<server>/<service>/.env             (config, tracked)
    <registry_path>/<server>/<service>/.env.secrets      (secrets, NOT tracked)
"""
from __future__ import annotations

from pathlib import Path

import yaml


class RegistryError(SystemExit):
    pass


def server_root(config: dict) -> Path:
    root = Path(config["registry_path"]) / config["server"]
    if not root.exists():
        raise RegistryError(
            f"No directory for server '{config['server']}' at {root} — "
            f"does the hermes registry have an entry for this host?"
        )
    return root


def service_path(config: dict, service: str) -> Path:
    path = server_root(config) / service
    if not path.exists():
        raise RegistryError(
            f"No service '{service}' found for server '{config['server']}' "
            f"(expected {path})"
        )
    return path


def compose_file(config: dict, service: str) -> Path:
    path = service_path(config, service) / "docker-compose.yml"
    if not path.exists():
        raise RegistryError(f"No docker-compose.yml in {path.parent}")
    return path


def list_services(config: dict) -> list[str]:
    root = server_root(config)
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
    path = server_root(config) / ".env"
    return path if path.exists() else None


def host_secrets_file(config: dict) -> Path | None:
    path = server_root(config) / ".env.secrets"
    return path if path.exists() else None


def external_networks(config: dict, service: str) -> list[str]:
    """Names of networks this service's compose file declares as external: true."""
    compose_path = compose_file(config, service)
    data = yaml.safe_load(compose_path.read_text()) or {}
    nets = data.get("networks", {}) or {}
    return [
        name for name, net_cfg in nets.items()
        if isinstance(net_cfg, dict) and net_cfg.get("external")
    ]
