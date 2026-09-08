"""Docker Hub tag discovery for `hc update`'s version-pin upgrade flow.

Docker Hub only, for now — an image hosted on another registry (ghcr.io, a
private registry, etc.) is detected and rejected with a clear error rather
than silently doing nothing or guessing at a different API shape.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request

API_BASE = "https://hub.docker.com/v2/repositories"

# At least major.minor, arbitrarily deep (mbentley/omada-controller, e.g.,
# tags patch/build revisions as major.minor.patch.build — "6.3.0.45"), pure
# digits only. Deliberately excludes bare single-component tags like "6" or
# "latest" (those are conventionally floating range tags, not a pin — see
# the original hc update design) and anything with a non-numeric suffix
# (variant/arch tags like "6.0-amd64", prerelease tags like "beta-6.3", all
# real examples pulled from mbentley/omada-controller's actual tag list).
VERSION_RE = re.compile(r"^\d+\.\d+(\.\d+)*$")


class DockerHubError(SystemExit):
    pass


def is_version_tag(tag: str) -> bool:
    return bool(VERSION_RE.match(tag))


def parse_version(tag: str) -> tuple[int, ...]:
    return tuple(int(part) for part in tag.split("."))


def split_image_ref(image: str) -> tuple[str, str]:
    """(everything before the tag, tag) — tag is "latest" if none was given.

    Only inspects the segment after the last '/' — a registry host:port's
    colon (e.g. myregistry.local:5000/repo) can only appear *before* the
    first '/', so looking for the tag-colon only in the last path segment
    avoids misreading a registry port as a tag.
    """
    last_slash = image.rfind("/")
    last_segment = image[last_slash + 1 :]
    if ":" in last_segment:
        prefix = image[: last_slash + 1] if last_slash != -1 else ""
        repo_name, tag = last_segment.rsplit(":", 1)
        return prefix + repo_name, tag
    return image, "latest"


def extract_tag(image: str) -> str:
    """The tag portion of an image reference, "latest" if none given."""
    return split_image_ref(image)[1]


def parse_image_ref(image: str) -> tuple[str, str, str]:
    """Split an `image:` string into (namespace, repository, tag) for the Docker Hub API.

    Raises DockerHubError if `image` points at a non-Docker-Hub registry —
    detected the same way Docker itself does: if the path has more than one
    segment and the first segment contains '.' or ':', or is literally
    "localhost", it's a registry host, not a Docker Hub namespace.
    """
    full_repo_path, tag = split_image_ref(image)
    parts = full_repo_path.split("/")

    if len(parts) >= 2 and ("." in parts[0] or ":" in parts[0] or parts[0] == "localhost"):
        raise DockerHubError(
            f"'{image}' is hosted on a non-Docker-Hub registry ('{parts[0]}') — "
            f"hc update's version picker only supports Docker Hub images right now"
        )

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
    """Every tag name for a Docker Hub repository, following pagination to the end."""
    names: list[str] = []
    url = f"{API_BASE}/{namespace}/{repo}/tags?page_size=100"
    while url:
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                data = json.load(resp)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise DockerHubError(f"no such Docker Hub repository: {namespace}/{repo}")
            raise DockerHubError(f"Docker Hub returned HTTP {exc.code} for {namespace}/{repo}")
        except urllib.error.URLError as exc:
            raise DockerHubError(f"couldn't reach Docker Hub: {exc}")
        names.extend(result["name"] for result in data["results"])
        url = data.get("next")
    return names


def newer_versions(current_tag: str, available_tags: list[str]) -> list[str]:
    """Version-shaped tags strictly newer than current_tag, sorted ascending.

    Tags that aren't version-shaped (variants, prereleases, "latest", bare
    "6") are silently excluded rather than erroring — they're just not
    comparable, not necessarily wrong.
    """
    current = parse_version(current_tag)
    candidates = []
    for tag in available_tags:
        if tag == current_tag or not is_version_tag(tag):
            continue
        version = parse_version(tag)
        if version > current:
            candidates.append((version, tag))
    candidates.sort()
    return [tag for _, tag in candidates]


def check_for_newer(image: str) -> list[str] | None:
    """Version-shaped tags newer than `image`'s current tag, sorted ascending.

    Returns None if this image isn't eligible for version-checking at all —
    its current tag isn't version-shaped, or it isn't hosted on Docker Hub
    — which the caller should treat as "silently fall back to the ordinary
    tag-agnostic update flow", not as an error: plenty of legitimate images
    just don't qualify. A real DockerHubError (network/API failure, repo
    not found) still propagates once we've confirmed the image *is*
    eligible — that's a genuine failure worth surfacing, not a fallback.
    """
    tag = extract_tag(image)
    if not is_version_tag(tag):
        return None
    try:
        namespace, repo, tag = parse_image_ref(image)
    except DockerHubError:
        return None
    return newer_versions(tag, fetch_tags(namespace, repo))
