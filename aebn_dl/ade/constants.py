"""Regex patterns, endpoints, and constants for ADE / Digiflix."""
from __future__ import annotations

import re

ADE_SITE_API_KEY = "60f039441fff44b4b08c64a3b4a64afe"
ADE_VERIFY_URL = "https://player.digiflix.video/verify"

# Regex: adultdvdempire.com, adultempire.com, elegantangel.com or dvderotik.com URLs
ADE_URL_RE = re.compile(
    r"https?://(?:(?:www\.)?(?:adultdvdempire|adultempire|elegantangel)\.com|(?:(?:[a-z0-9-]+\.)?dvderotik\.com))/\S+",
    re.IGNORECASE,
)

# Patterns for movie/clip pages
ADE_MOVIE_RE = re.compile(
    r"/(\d+)/([^/]+?)(?:-porn-movies|-porn-videos)?\.html",
    re.IGNORECASE,
)
ADE_CLIP_RE = re.compile(
    r"/clip/(\d+)/([^/]+?)(?:-streaming-scene)?\.html",
    re.IGNORECASE,
)

# Elegant Angel page patterns
EA_SCENE_RE = re.compile(
    r"/(\d+)/[^/]*?streaming-scene-video\.html",
    re.IGNORECASE,
)
EA_MOVIE_RE = re.compile(
    r"/(\d+)/[^/]*?(?:streaming-)?porn-videos\.html",
    re.IGNORECASE,
)

# Scene screenshot thumbs: https://caps1cdn.adultempire.com/n/0399/10/5090399_06670_10.jpg
# Full size:                            .../n/0399/1280/5090399_06670_1280c.jpg
_EA_THUMB_RE = re.compile(
    r"https://caps\d?cdn\.adultempire\.com/n/(\d+)/(10|320)/(\d+)_(\d+)_(?:10|320)\.jpg",
    re.IGNORECASE,
)

# Broad fallback: any caps CDN still
_ANY_CAPS_RE = re.compile(
    r"https://caps\d?cdn\.adultempire\.com/([a-z])/(\d+)/(\d+)/(\d+)_(\d+)_\d+[a-z]?\.jpg",
    re.IGNORECASE,
)

# Adult Empire / DVDErotik frame CDN URL pattern:
_FRAME_RE = re.compile(
    r"https?://imgs\d?cdn\.adultempire\.com/frame/(\d+)\?[^\s\"\'\<\>]*?tc=(\d+)",
    re.IGNORECASE,
)

# Any frame URL
_FRAME_URL_RE = re.compile(
    r"https?://imgs\d?cdn\.adultempire\.com/frame/\d+\?[^\s\"\'\<\>]*?tc=\d+",
    re.IGNORECASE,
)

# Scene backdrop/poster image: imgs{N}cdn.adultempire.com/backdrop/{width}/{item_id}_{scene_id}/{slug}.jpg
_BACKDROP_RE = re.compile(
    r"https?://imgs\d?cdn\.adultempire\.com/backdrop/\d+/\d+/[^\s\"\'\<\>]+\.jpg",
    re.IGNORECASE,
)

# Extract player init params from HTML
_PLAYER_INIT_RE = re.compile(
    r"AEVideoPlayer\([^)]*\{[^}]*"
    r"(?:item_id|item):\s*(\d+)[^}]*"
    r"site:\s*['\"]([^'\"]+)['\"][^}]*"
    r"key:\s*['\"]([^'\"]+)['\"][^}]*"
    r"timestamp:\s*['\"]([^'\"]+)['\"][^}]*"
    r"sig:\s*['\"]([^'\"]+)['\"]",
    re.DOTALL,
)

# Simpler individual param extraction as fallback
_ITEM_ID_RE = re.compile(r"['\"]?(?:item_id|item)['\"]?\s*:\s*['\"]?(\d+)['\"]?", re.IGNORECASE)
_SCENE_ID_RE = re.compile(r"['\"]?(?:scene_id|scene)['\"]?\s*:\s*['\"]?(\d+)['\"]?", re.IGNORECASE)
_TYPE_RE = re.compile(r"['\"]?type['\"]?\s*:\s*['\"]([^'\"]+)['\"]", re.IGNORECASE)
_SITE_RE = re.compile(r"['\"]?site['\"]?\s*:\s*['\"]([^'\"]+)['\"]", re.IGNORECASE)
_KEY_RE = re.compile(r"['\"]?key['\"]?\s*:\s*['\"]([^'\"]+)['\"]", re.IGNORECASE)
_TIMESTAMP_RE = re.compile(r"['\"]?timestamp['\"]?\s*:\s*['\"]([^'\"]+)['\"]", re.IGNORECASE)
_SIG_RE = re.compile(r"['\"]?sig['\"]?\s*:\s*['\"]([^'\"]+)['\"]", re.IGNORECASE)
_SCENE_WIDGET_RE = re.compile(r'data-scene-id="(\d+)"[^>]*>.*?<img[^>]+src="([^">]+)"', re.DOTALL | re.IGNORECASE)

ADE_TRAILER_RE = re.compile(
    r"https?://(?:(?:www\.)?(?:adultdvdempire|adultempire|elegantangel)\.com|(?:(?:[a-z0-9-]+\.)?dvderotik\.com))/(?:trailer/|sample/|clip/)?\S+",
    re.IGNORECASE,
)
