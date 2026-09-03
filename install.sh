#!/usr/bin/env bash
# install.sh: sets up hc on this host. Safe to rerun after any
# dependency change in pyproject.toml (code changes alone don't need this,
# since the install is editable).
set -euo pipefail
cd "$(dirname "$0")"

if ! command -v docker >/dev/null 2>&1; then
    echo "warning: docker not found on PATH, hc will install fine but won't be able to run anything yet" >&2
fi

if ! docker compose version >/dev/null 2>&1; then
    echo "warning: 'docker compose' (plugin form) not available, hc expects this, not the standalone docker-compose binary" >&2
fi

python3 -m venv .venv
.venv/bin/pip install --upgrade pip -q
.venv/bin/pip install -e . -q

ln -sf "$(pwd)/.venv/bin/hc" /usr/local/bin/hc

echo "hc installed -> $(readlink -f /usr/local/bin/hc)"
echo "next: hc init <server-name>"