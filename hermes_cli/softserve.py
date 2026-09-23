"""SoftServe (self-hosted git server) access-token handling.

Mirrors github.py's token pattern: a single opaque string per host, used
as HTTP basic-auth (token as username, empty password) for git operations
against an http(s) SoftServe remote -- exactly how SoftServe's own docs
show using a token (`git clone http://<token>@host:port/repo.git`).
Generate one on the server itself, as whichever user hc should act as:

    ssh -p <port> <softserve-host> token create hc-<this-host>

An ssh:// SoftServe remote doesn't use this at all -- that authenticates
via a normal SSH keypair/agent, same as any other SSH git remote, so
there's nothing for a token to do there.
"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

TOKEN_PATH = Path("/etc/hermes-cli/softserve_token")


class SoftServeError(SystemExit):
    pass


def read_token() -> str:
    """The access token from TOKEN_PATH -- same posture as github.py's
    read_token(): expected to exist out-of-band, hc just tells you clearly
    what's missing and where.
    """
    if not TOKEN_PATH.exists():
        raise SoftServeError(
            f"no SoftServe token at {TOKEN_PATH} — generate one on the server with "
            f"`ssh -p <port> <softserve-host> token create hc-<this-host>` and place it there, "
            f"pass --token directly, or rerun `hc init` to set it up interactively"
        )
    token = TOKEN_PATH.read_text().strip()
    if not token:
        raise SoftServeError(f"{TOKEN_PATH} exists but is empty")
    return token


def write_token(token: str) -> None:
    """Writes the access token to TOKEN_PATH, root-readable only.

    Called from `hc init`'s setup prompt (or its --softserve-token flag),
    or from `hc self-update --token`. By the time init runs this, it has
    already self-elevated via privilege.require_root(); self-update
    doesn't need root at all since this only ever writes to a file
    already under /etc/hermes-cli from a prior root-run init.
    """
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(token.strip() + "\n")
    TOKEN_PATH.chmod(0o600)


def with_token(url: str, token: str) -> str:
    """Embeds `token` as the HTTP basic-auth username on an http(s) URL.

    Raises SoftServeError for any other scheme -- an ssh:// or git://
    remote authenticates differently and doesn't take a token this way,
    so silently ignoring it would leave the caller thinking auth is set
    up when it isn't.
    """
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise SoftServeError(
            f"'{url}' isn't an http(s) URL — a SoftServe access token only applies to "
            f"http(s) remotes; an ssh:// remote authenticates via SSH key instead, no token needed"
        )
    netloc = f"{quote(token, safe='')}@{parts.hostname}"
    if parts.port:
        netloc += f":{parts.port}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def sibling_repo_url(url: str, repo_name: str) -> str:
    """Same scheme/host/port as `url`, with its final path segment (repo
    name) replaced by `repo_name` -- e.g. turns a SoftServe hermes-cli URL
    into the sibling hermes registry's URL on that same server. Preserves
    a trailing ".git" if the original had one. Used so `hc self-update
    --repo <hermes-cli-url>` can derive the hermes registry's URL on the
    same server rather than needing it typed out separately.
    """
    parts = urlsplit(url)
    suffix = ".git" if parts.path.rstrip("/").endswith(".git") else ""
    return urlunsplit((parts.scheme, parts.netloc, f"/{repo_name}{suffix}", parts.query, parts.fragment))
