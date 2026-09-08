"""GHCR (ghcr.io) tag discovery for `hc update`'s version-pin upgrade flow.

Unlike Docker Hub's fully-anonymous browsable API, GHCR implements the OCI
Distribution Spec: even a public/anonymous read needs a short-lived bearer
token first. Confirmed live against a real public GHCR image
(immich-app/immich-server): an unauthenticated GET to
/v2/<repo>/tags/list returns 401 with a
`WWW-Authenticate: Bearer realm="https://ghcr.io/token",service="ghcr.io",scope="repository:<repo>:pull"`
challenge naming the exact token endpoint/params to use. This hardcodes
that same fixed shape rather than parsing the challenge dynamically, since
this module only ever talks to ghcr.io — there's nothing to negotiate.

Pagination is via the OCI-standard RFC 5988 `Link` response header
(`<path>; rel="next"`), not a field in the JSON body like Docker Hub uses.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request

from . import imageref

REGISTRY_HOST = "ghcr.io"
TOKEN_URL = "https://ghcr.io/token"
API_BASE = "https://ghcr.io/v2"

_LINK_NEXT_RE = re.compile(r'<([^>]+)>;\s*rel="next"')


class GhcrError(SystemExit):
    pass


def is_ghcr_image(image: str) -> bool:
    return imageref.registry_host(image) == REGISTRY_HOST


def parse_image_ref(image: str) -> tuple[str, str]:
    """Split an `image:` string into (repo_path, tag) for the GHCR API.

    repo_path is everything between "ghcr.io/" and the tag, e.g.
    "immich-app/immich-server" — GHCR repo paths aren't guaranteed to be
    exactly owner/repo (some packages nest deeper), so this doesn't assume
    a fixed depth the way dockerhub.py's namespace/repo split does.
    """
    full_repo_path, tag = imageref.split_image_ref(image)
    if not full_repo_path.startswith(f"{REGISTRY_HOST}/"):
        raise GhcrError(f"'{image}' isn't a ghcr.io image reference")
    repo_path = full_repo_path[len(REGISTRY_HOST) + 1 :]
    return repo_path, tag


def _fetch_token(repo_path: str) -> str:
    url = f"{TOKEN_URL}?scope=repository:{repo_path}:pull&service={REGISTRY_HOST}"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as exc:
        raise GhcrError(f"ghcr.io auth failed for {repo_path} (HTTP {exc.code})")
    except urllib.error.URLError as exc:
        raise GhcrError(f"couldn't reach ghcr.io for an auth token: {exc}")
    return data["token"]


def fetch_tags(repo_path: str) -> list[str]:
    """Every tag name for a GHCR repository, following Link-header pagination to the end."""
    token = _fetch_token(repo_path)
    names: list[str] = []
    url = f"{API_BASE}/{repo_path}/tags/list?n=100"
    while url:
        request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        try:
            with urllib.request.urlopen(request, timeout=10) as resp:
                data = json.load(resp)
                link_header = resp.headers.get("Link", "")
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise GhcrError(f"no such ghcr.io package: {repo_path}")
            raise GhcrError(f"ghcr.io returned HTTP {exc.code} for {repo_path}")
        except urllib.error.URLError as exc:
            raise GhcrError(f"couldn't reach ghcr.io: {exc}")
        names.extend(data.get("tags") or [])
        match = _LINK_NEXT_RE.search(link_header)
        if not match:
            break
        next_ref = match.group(1)
        url = next_ref if next_ref.startswith("http") else f"https://{REGISTRY_HOST}{next_ref}"
    return names


def check_for_newer(image: str) -> list[str] | None:
    """Version-shaped tags newer than `image`'s current tag, sorted ascending.

    Returns None if this image isn't eligible for version-checking at all —
    its current tag isn't version-shaped, or it isn't hosted on ghcr.io —
    which the caller should treat as "not applicable here", not an error.
    A real GhcrError (network/API/auth failure, package not found) still
    propagates once we've confirmed the image *is* eligible.
    """
    if not is_ghcr_image(image):
        return None
    tag = imageref.extract_tag(image)
    if not imageref.is_version_tag(tag):
        return None
    repo_path, tag = parse_image_ref(image)
    return imageref.newer_versions(tag, fetch_tags(repo_path))
