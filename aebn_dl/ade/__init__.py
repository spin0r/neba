"""Public API for AdultDVDEmpire, Elegant Angel, and DVDErotik scraping."""
from __future__ import annotations

# Re-export core constants
from .constants import (
    ADE_CLIP_RE,
    ADE_MOVIE_RE,
    ADE_SITE_API_KEY,
    ADE_TRAILER_RE,
    ADE_URL_RE,
    ADE_VERIFY_URL,
    EA_MOVIE_RE,
    EA_SCENE_RE,
)

# Re-export sessions and authentication
from .session import get_session, parse_ade_cookies
_get_session = get_session

from .auth import (
    auth_error,
    cookie_hint,
    no_player_cause,
    no_player_error,
    page_title,
    site_for_url,
    upper_first,
)

# Re-export player extraction
from .player import extract_player_params, get_playlist_url_from_verify

# Re-export thumbnails and backdrop
from .thumbnails import (
    extract_scene_backdrop,
    extract_scene_thumbnail,
    frame_width_value,
    upgrade_backdrop_width,
    upgrade_frame_width,
)
_extract_scene_thumbnail = extract_scene_thumbnail
_extract_scene_backdrop = extract_scene_backdrop

# Re-export screenshots
from .screenshots import (
    build_groups_from_page_blocks,
    build_screenshot_groups,
    caps_probe_info,
    dedupe_groups,
    extract_ea_screenshots,
    extract_more_screens_params,
    extract_movie_page_blocks,
    extract_scene_widgets,
    fetch_full_scene_shots,
    merge_shots,
    shot_offset_seconds,
    synth_screenshots,
)

# Re-export metadata
from .metadata import (
    extract_ade_duration_seconds,
    resolve_ade_title,
    scenes_info,
)

# Re-export utilities
from .utils import extract_ade_url

# Re-export main manifest extraction
from .extraction import get_ade_manifest, get_ade_preview_manifest

__all__ = [
    # Main extractors
    "get_ade_manifest",
    "get_ade_preview_manifest",
    "extract_ade_url",
    # Session & Cookies
    "get_session",
    "_get_session",
    "parse_ade_cookies",
    # Metadata
    "extract_ade_duration_seconds",
    "resolve_ade_title",
    "scenes_info",
    # Thumbnails
    "extract_scene_thumbnail",
    "extract_scene_backdrop",
    "_extract_scene_thumbnail",
    "_extract_scene_backdrop",
    "upgrade_backdrop_width",
    "upgrade_frame_width",
    # Screenshots
    "build_screenshot_groups",
    "extract_ea_screenshots",
    # Constants
    "ADE_URL_RE",
    "ADE_MOVIE_RE",
    "ADE_CLIP_RE",
    "EA_SCENE_RE",
    "EA_MOVIE_RE",
    "ADE_TRAILER_RE",
    "ADE_SITE_API_KEY",
    "ADE_VERIFY_URL",
]
