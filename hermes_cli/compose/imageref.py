"""Image-reference parsing and version comparison shared across registry
backends (dockerhub.py, ghcr.py, ...). Nothing here talks to a network.
"""
from __future__ import annotations

import re

# At least major.minor, arbitrarily deep (some ecosystems tag patch/build
# revisions as major.minor.patch.build, e.g. "6.3.0.45"), optionally
# "v"-prefixed (the GitHub/GHCR convention — "v1.50.1"). Deliberately
# excludes bare single-component tags like "6" or "latest" (those are
# conventionally floating range tags, not a pin) and anything with a
# non-numeric suffix (variant/arch tags like "6.0-amd64", prerelease tags
# like "beta-6.3" or "v1.36.0_55-dev" — all real examples pulled from
# actual Docker Hub and GHCR tag lists).
VERSION_RE = re.compile(r"^v?\d+\.\d+(\.\d+)*$")


def is_version_tag(tag: str) -> bool:
    return bool(VERSION_RE.match(tag))


def parse_version(tag: str) -> tuple[int, ...]:
    numeric = tag[1:] if tag[:1] == "v" else tag
    return tuple(int(part) for part in numeric.split("."))


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


def registry_host(image: str) -> str | None:
    """The registry hostname an image is pinned to, or None for Docker Hub
    (the implicit default when no host is given).

    Detected the same way Docker itself does: if the image path has more
    than one segment and the first segment contains '.' or ':', or is
    literally "localhost", that first segment is a registry host rather
    than a Docker Hub namespace.
    """
    base, _ = split_image_ref(image)
    parts = base.split("/")
    if len(parts) >= 2 and ("." in parts[0] or ":" in parts[0] or parts[0] == "localhost"):
        return parts[0]
    return None


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
