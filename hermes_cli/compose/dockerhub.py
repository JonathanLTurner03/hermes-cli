"""Docker Hub tag discovery for `hc update`'s version-pin upgrade flow."""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from . import imageref

API_BASE = "https://hub.docker.com/v2/repositories"


class DockerHubError(SystemExit):
    pass


def is_docker_hub_image(image: str) -> bool:
    """Docker Hub is the implicit default registry — no host prefix means Docker Hub."""
    return imageref.registry_host(image) is None


def parse_image_ref(image: str) -> tuple[str, str, str]:
    """Split an `image:` string into (namespace, repository, tag) for the Docker Hub API.

    A single path segment (e.g. "nginx") is an official image, living under
    the "library" namespace on Docker Hub's API. Raises DockerHubError if
    `image` is hosted on another registry — self-defending even though
    check_for_newer() already gates on is_docker_hub_image() before ever
    calling this, so this function is still correct if called directly.
    """
    host = imageref.registry_host(image)
    if host is not None:
        raise DockerHubError(
            f"'{image}' is hosted on a non-Docker-Hub registry ('{host}') — "
            f"this function only handles Docker Hub image references"
        )
    full_repo_path, tag = imageref.split_image_ref(image)
    parts = full_repo_path.split("/")
    if len(parts) == 1:
        namespace, repo = "library", parts[0]
    elif len(parts) == 2:
        namespace, repo = parts
    else:
        raise DockerHubError(
            f"'{image}' doesn't look like a Docker Hub image reference (too many path segments)"
        )
    return namespace, repo, tag


def fetch_tags(namespace: str, repo: str) -> list[str]:
    """Every tag name for a Docker Hub repository, following pagination as far as it goes.

    Docker Hub caps pagination depth for anonymous (unauthenticated)
    requests — confirmed live against library/nginx (1000+ tags): past
    roughly page 10 it returns 403 with body
    '{"message":"pagination offset too large for anonymous requests; sign
    in to page further"}'. That's not a real failure worth surfacing: the
    endpoint's default ordering is most-recently-pushed first, so what
    gets cut off is the *oldest* tags — irrelevant to "is anything newer
    than mine out there". Treated as "stop, use what's already collected"
    rather than an error. Checking the response body (not just the status
    code) keeps this from swallowing a 403 for some other reason, e.g. a
    genuinely private/inaccessible repository.
    """
    names: list[str] = []
    url = f"{API_BASE}/{namespace}/{repo}/tags?page_size=100"
    while url:
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                data = json.load(resp)
        except urllib.error.HTTPError as exc:
            if exc.code == 403 and b"pagination offset too large" in exc.read():
                break
            if exc.code == 404:
                raise DockerHubError(f"no such Docker Hub repository: {namespace}/{repo}")
            raise DockerHubError(f"Docker Hub returned HTTP {exc.code} for {namespace}/{repo}")
        except urllib.error.URLError as exc:
            raise DockerHubError(f"couldn't reach Docker Hub: {exc}")
        names.extend(result["name"] for result in data["results"])
        url = data.get("next")
    return names


def check_for_newer(image: str) -> list[str] | None:
    """Version-shaped tags newer than `image`'s current tag, sorted ascending.

    Returns None if this image isn't eligible for version-checking at all —
    its current tag isn't version-shaped, or it isn't hosted on Docker Hub
    — which the caller should treat as "not applicable here", not an error.
    A real DockerHubError (network/API failure, repo not found) still
    propagates once we've confirmed the image *is* eligible.
    """
    if not is_docker_hub_image(image):
        return None
    tag = imageref.extract_tag(image)
    if not imageref.is_version_tag(tag):
        return None
    namespace, repo, tag = parse_image_ref(image)
    return imageref.newer_versions(tag, fetch_tags(namespace, repo))
