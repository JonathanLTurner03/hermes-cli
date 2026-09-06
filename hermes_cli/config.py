"""Host-level identity config for hc.

Lives at /etc/hermes-cli/config.yml. Written once via `hc init <server>`,
read by every other command to figure out which server directory in the
hermes registry this host corresponds to.
"""
from __future__ import annotations

from pathlib import Path

import yaml

CONFIG_DIR = Path("/etc/hermes-cli")
CONFIG_PATH = CONFIG_DIR / "config.yml"

DEFAULT_REGISTRY_PATH = "/opt/infra/hermes"


class ConfigError(SystemExit):
    """Raised (as SystemExit) when config is missing or invalid."""


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        raise ConfigError(
            f"No config at {CONFIG_PATH} — run `hc init <server>` first"
        )
    data = yaml.safe_load(CONFIG_PATH.read_text()) or {}
    for key in ("server", "registry_path"):
        if key not in data:
            raise ConfigError(f"Config at {CONFIG_PATH} is missing '{key}'")
    return data


def write_config(server: str, registry_path: str = DEFAULT_REGISTRY_PATH) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    data = {"server": server, "registry_path": registry_path}
    CONFIG_PATH.write_text(yaml.safe_dump(data, sort_keys=False))


def config_exists() -> bool:
    return CONFIG_PATH.exists()
