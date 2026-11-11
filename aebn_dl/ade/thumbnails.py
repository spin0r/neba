"""Thumbnail, backdrop, and preview image extraction."""
from __future__ import annotations

import re

from .constants import _BACKDROP_RE, _FRAME_RE, _FRAME_URL_RE


def upgrade_backdrop_width(url: str, width: int = 1920) -> str:
    """Upgrade a backdrop URL width component to `width` px (default 1920)."""
    return re.sub(r"/backdrop/\d+/", f"/backdrop/{width}/", url)


def frame_width_value(url: str) -> int:
    m = re.search(r"[?&]w=(\d+)", url)
    return int(m.group(1)) if m else 0


def upgrade_frame_width(url: str, width: int = 3840) -> str:
    """Upgrade or set the `w` query param on an Adult Empire frame CDN URL."""
    if re.search(r"[?&]w=\d+", url):
        return re.sub(r"([?&]w=)\d+", rf"\g<1>{width}", url)
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}w={width}"


def extract_scene_backdrop(
    html: str,
    item_id: str | int | None = None,
    scene_id: str | int | None = None,
    slug: str | None = None,
) -> str | None:
    """Extract a scene backdrop/poster photo URL from the page HTML, or construct it."""
    matches = _BACKDROP_RE.findall(html)
    if matches:
        for url in matches:
            if "/backdrop/1920/" in url or "/backdrop/3840/" in url:
                return upgrade_backdrop_width(url, 1280)
        return upgrade_backdrop_width(matches[0], 1280)

    # Check for meta og:image or link tags with backdrop
    meta_m = re.search(r'[\'"](https?://imgs\d?cdn\.adultempire\.com/backdrop/[^\'"]+)[\'"]', html, re.I)
    if meta_m:
        return upgrade_backdrop_width(meta_m.group(1), 1280)

    # If item_id/master_id and scene_id are available, construct the backdrop URL
    # On Adult Empire CDN, the backdrop URL format is:
    # https://imgs1cdn.adultempire.com/backdrop/1920/{master_id}_{scene_id}/{slug}.jpg
    # Note: the master_id corresponds to the video master ID (which appears in VideoObject / frame URLs)
    if scene_id:
        master = None
        # Always check VideoObject thumbnailUrl or frame URL in HTML first for the true video master_id
        vo_m = re.search(r'"thumbnailUrl":\s*"https?://imgs\d?cdn\.adultempire\.com/frame/(\d+)', html)
        if vo_m:
            master = vo_m.group(1)
        if not master:
            frame_m = re.search(r'https?://imgs\d?cdn\.adultempire\.com/frame/(\d+)', html)
            if frame_m:
                master = frame_m.group(1)
        if not master and item_id:
            master = str(item_id)

        if master:
            clean_slug = slug or "scene"
            if clean_slug.endswith(".html"):
                clean_slug = clean_slug[:-5]
            if clean_slug.endswith("-streaming-scene"):
                clean_slug = clean_slug[:-16]
            clean_slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", clean_slug).strip("-") or "scene"
            return f"https://imgs1cdn.adultempire.com/backdrop/1920/{master}_{scene_id}/{clean_slug}.jpg"

    return None


def extract_scene_thumbnail(
    html: str,
    target_tc: str | int | None = None,
    item_id: str | int | None = None,
    scene_id: str | int | None = None,
    slug: str | None = None,
) -> str | None:
    """
    Extract a representative thumbnail preview image for a scene.
    Prefers dedicated backdrop photo over frame grab, falling back to frames.
    """
    bd = extract_scene_backdrop(html, item_id=item_id, scene_id=scene_id, slug=slug)
    if bd:
        return bd

    if target_tc is not None:
        tc_str = str(target_tc)
        pattern = re.compile(
            rf"https?://imgs\d?cdn\.adultempire\.com/frame/\d+\?[^\s\"\'\<\>]*?tc={tc_str}\b[^\s\"\'\<\>]*",
            re.IGNORECASE,
        )
        m = pattern.search(html)
        if m:
            return upgrade_frame_width(m.group(0), 1280)

    best_url: str | None = None
    best_w = -1
    for m in _FRAME_URL_RE.finditer(html):
        url = m.group(0)
        w = frame_width_value(url)
        if w > best_w:
            best_w = w
            best_url = url
    if best_url:
        return upgrade_frame_width(best_url, 1280)

    m = _FRAME_RE.search(html)
    if m:
        return upgrade_frame_width(m.group(0), 1280)

    return None
