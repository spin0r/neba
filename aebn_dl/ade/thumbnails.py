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


def extract_scene_backdrop(html: str) -> str | None:
    """Extract a scene backdrop/poster photo URL from the page HTML."""
    matches = _BACKDROP_RE.findall(html)
    if not matches:
        return None
    for url in matches:
        if "/backdrop/1920/" in url or "/backdrop/3840/" in url:
            return upgrade_backdrop_width(url, 1280)
    return upgrade_backdrop_width(matches[0], 1280)


def extract_scene_thumbnail(html: str, target_tc: str | int | None = None) -> str | None:
    """
    Extract a representative thumbnail preview image for a scene.
    Prefers dedicated backdrop photo over frame grab, falling back to frames.
    """
    bd = extract_scene_backdrop(html)
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
