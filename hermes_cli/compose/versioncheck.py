"""Dispatches hc update's version-pin upgrade flow across registry backends.

Currently supports Docker Hub and GHCR (ghcr.io). Adding a new backend
means giving it the same is_<x>_image()/check_for_newer() shape as those
two (see dockerhub.py/ghcr.py) and adding one more branch below.
"""
from __future__ import annotations

from . import dockerhub, ghcr, imageref


class UnsupportedRegistryError(Exception):
    """Not a SystemExit — the caller decides whether to report and fall
    back (that's what `hc update` does) rather than always crashing."""


def check_for_newer(image: str) -> list[str] | None:
    """Version-shaped tags newer than `image`'s current tag, sorted ascending.

    Returns None if the current tag isn't version-shaped at all (:latest,
    a bare floating :6, etc.) — not worth mentioning, this is normal and
    common; the caller should silently fall back to the ordinary
    tag-agnostic update flow.

    Raises UnsupportedRegistryError if the tag IS version-shaped but the
    image isn't hosted on a registry hc knows how to query — that's worth
    reporting before falling back, since it's a real gap, not "nothing to
    do here".
    """
    tag = imageref.extract_tag(image)
    if not imageref.is_version_tag(tag):
        return None
    if dockerhub.is_docker_hub_image(image):
        return dockerhub.check_for_newer(image)
    if ghcr.is_ghcr_image(image):
        return ghcr.check_for_newer(image)
    host = imageref.registry_host(image) or "docker hub"
    raise UnsupportedRegistryError(
        f"'{image}' is pinned to a version-shaped tag ('{tag}') but hc doesn't know how to "
        f"check versions on '{host}' yet — only Docker Hub and ghcr.io are supported"
    )
