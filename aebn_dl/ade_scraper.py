"""AdultDVDEmpire / Elegant Angel / DVDErotik scraper module.

Modularized implementation re-exported from `aebn_dl.ade` for full backward compatibility.
"""
from __future__ import annotations

# Re-export entire public API from modular package `ade`
from .ade import *  # noqa: F401, F403

# Re-export internal helpers for backward compatibility with legacy scripts
from .ade.auth import (
    auth_error as _auth_error,
    cookie_hint as _cookie_hint,
    no_player_cause as _no_player_cause,
    no_player_error as _no_player_error,
    page_title as _page_title,
    site_for_url as _site_for_url,
    upper_first as _upper_first,
)
from .ade.constants import (
    _ANY_CAPS_RE,
    _BACKDROP_RE,
    _EA_THUMB_RE,
    _FRAME_RE,
    _FRAME_URL_RE,
    _ITEM_ID_RE,
    _KEY_RE,
    _PLAYER_INIT_RE,
    _SCENE_ID_RE,
    _SCENE_WIDGET_RE,
    _SIG_RE,
    _SITE_RE,
    _TIMESTAMP_RE,
    _TYPE_RE,
)
from .ade.extraction import _get_clip_preview
from .ade.metadata import (
    extract_ade_duration_seconds,
    resolve_ade_title,
    scenes_info as _scenes_info,
)
from .ade.player import (
    extract_player_params as _extract_player_params,
    get_playlist_url_from_verify as _get_playlist_url_from_verify,
)
from .ade.screenshots import (
    build_groups_from_page_blocks as _build_groups_from_page_blocks,
    build_screenshot_groups as _build_screenshot_groups,
    caps_probe_info as _caps_probe_info,
    dedupe_groups as _dedupe_groups,
    extract_ea_screenshots as _extract_ea_screenshots,
    extract_more_screens_params as _extract_more_screens_params,
    extract_movie_page_blocks as _extract_movie_page_blocks,
    extract_scene_widgets as _extract_scene_widgets,
    fetch_full_scene_shots as _fetch_full_scene_shots,
    merge_shots as _merge_shots,
    shot_offset_seconds as _shot_offset_seconds,
    synth_screenshots as _synth_screenshots,
)
from .ade.session import get_session as _get_session
from .ade.thumbnails import (
    extract_scene_backdrop as _extract_scene_backdrop,
    extract_scene_thumbnail as _extract_scene_thumbnail,
    frame_width_value as _frame_width_value,
    upgrade_backdrop_width as _upgrade_backdrop_width,
    upgrade_frame_width as _upgrade_frame_width,
)
from .custom_session import CustomSession
