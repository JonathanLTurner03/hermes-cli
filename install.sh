#!/usr/bin/env bash
# install.sh — sets up hc on this host. Safe to rerun after any
# dependency change in pyproject.toml. Do NOT run this whole script with
# sudo — only the final symlink step needs root, and running venv/pip
# under sudo can leave a venv built against root's python instead of yours.
set -euo pipefail
cd "$(dirname "$0")"

if [[ $EUID -eq 0 ]]; then
    echo "error: don't run install.sh with sudo — it'll prompt for sudo only where needed" >&2
    exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
    echo "warning: docker not found on PATH — hc will install fine but won't be able to run anything yet" >&2
fi

if ! docker compose version >/dev/null 2>&1; then
    echo "warning: 'docker compose' (plugin form) not available — hc expects this, not the standalone docker-compose binary" >&2
fi

python3 -m venv .venv
.venv/bin/pip install --upgrade pip -q
.venv/bin/pip install -e . -q

sudo ln -sf "$(pwd)/.venv/bin/hc" /usr/local/bin/hc

echo "hc installed -> $(readlink -f /usr/local/bin/hc)"

# Shell completion: one line in the invoking user's shell rc file so `hc`
# tab-completes commands, service names, and mount names (see README.md's
# "Shell completion" section). Idempotent — skipped if already present —
# so this is safe on every rerun, not just the first install.
shell_name="$(basename "${SHELL:-}")"
case "$shell_name" in
    bash)
        rcfile="$HOME/.bashrc"
        completion_line='eval "$(_HC_COMPLETE=bash_source hc)"'
        ;;
    zsh)
        rcfile="$HOME/.zshrc"
        completion_line='eval "$(_HC_COMPLETE=zsh_source hc)"'
        ;;
    fish)
        rcfile="$HOME/.config/fish/completions/hc.fish"
        completion_line='_HC_COMPLETE=fish_source hc | source'
        ;;
    *)
        rcfile=""
        ;;
esac

if [[ -n "$rcfile" ]]; then
    mkdir -p "$(dirname "$rcfile")"
    touch "$rcfile"
    if grep -qF '_HC_COMPLETE' "$rcfile" 2>/dev/null; then
        echo "shell completion already configured in $rcfile"
    else
        echo "$completion_line" >> "$rcfile"
        echo "added shell completion to $rcfile — restart your shell, or: source $rcfile"
    fi
else
    echo "warning: unrecognized shell (\$SHELL=${SHELL:-unset}) — skipping shell completion setup; see README.md's 'Shell completion' section to add it by hand" >&2
fi

echo "next: hc init <server-name>"