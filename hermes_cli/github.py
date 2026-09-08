"""GitHub API access for hc update's PR-based version-pin flow.

Creating a pull request is one authenticated POST — no SDK needed, just
urllib against the REST API, the same pattern compose/dockerhub.py and
compose/ghcr.py already use for their registries. Deliberately not using
the `gh` CLI: it's a separate compiled binary with its own per-OS install
story, awkward to roll out fleet-wide through install.sh's pip-based
dependency model, whereas this needs nothing beyond the stdlib.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from pathlib import Path

TOKEN_PATH = Path("/etc/hermes-cli/github_token")

# Fine-grained PATs are GitHub's current recommendation over classic tokens
# (scoped to specific repos rather than everything the account can touch) —
# this is the direct "create one" URL, shown by both `hc init`'s setup
# prompt and read_token()'s error message so there's one place to update it.
TOKEN_SETUP_URL = "https://github.com/settings/personal-access-tokens/new"

API_BASE = "https://api.github.com"

# Matches both the SSH form (git@github.com:owner/repo.git) and the HTTPS
# form (https://github.com/owner/repo.git or without the .git suffix).
_REMOTE_RE = re.compile(r"github\.com[:/]([^/]+)/(.+?)(?:\.git)?/?$")


class GitHubError(SystemExit):
    pass


def read_token() -> str:
    """The PR-creation token from TOKEN_PATH — a dedicated file per host,
    same posture as this project's existing .env.secrets convention:
    expected to exist out-of-band, hc just tells you clearly what's
    missing and where.
    """
    if not TOKEN_PATH.exists():
        raise GitHubError(
            f"no GitHub token at {TOKEN_PATH} — create one at {TOKEN_SETUP_URL} "
            f"(needs 'Pull requests: Read and write' access to this repo) and place it there "
            f"to enable PR creation, or rerun `hc init` to set it up interactively"
        )
    token = TOKEN_PATH.read_text().strip()
    if not token:
        raise GitHubError(f"{TOKEN_PATH} exists but is empty")
    return token


def write_token(token: str) -> None:
    """Writes the PR-creation token to TOKEN_PATH, root-readable only.

    Called from `hc init`'s setup prompt (or its --github-token flag) — by
    the time this runs, init has already self-elevated via
    privilege.require_root(), so creating a file under /etc is expected to
    just work here, not something this function needs to re-check itself.
    """
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(token.strip() + "\n")
    TOKEN_PATH.chmod(0o600)


def parse_owner_repo(remote_url: str) -> tuple[str, str]:
    match = _REMOTE_RE.search(remote_url)
    if not match:
        raise GitHubError(f"'{remote_url}' doesn't look like a github.com remote")
    return match.group(1), match.group(2)


def create_pull_request(
    owner: str, repo: str, *, title: str, body: str, head: str, base: str, token: str
) -> str:
    """Opens a PR from `head` into `base`. Returns the PR's URL."""
    url = f"{API_BASE}/repos/{owner}/{repo}/pulls"
    payload = json.dumps({"title": title, "body": body, "head": head, "base": base}).encode()
    request = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise GitHubError(f"GitHub API returned HTTP {exc.code} creating the PR: {detail}")
    except urllib.error.URLError as exc:
        raise GitHubError(f"couldn't reach the GitHub API: {exc}")
    return data["html_url"]
