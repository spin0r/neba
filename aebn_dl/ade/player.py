"""Player parameters extraction and verify API resolution."""
from __future__ import annotations

import logging
from typing import Any

from .constants import (
    ADE_SITE_API_KEY,
    ADE_VERIFY_URL,
    _ITEM_ID_RE,
    _KEY_RE,
    _PLAYER_INIT_RE,
    _SCENE_ID_RE,
    _SIG_RE,
    _SITE_RE,
    _TIMESTAMP_RE,
    _TYPE_RE,
)

try:
    from ..custom_session import CustomSession
except ImportError:
    from aebn_dl.custom_session import CustomSession  # type: ignore

logger = logging.getLogger(__name__)


def extract_player_params(html: str) -> dict[str, str] | None:
    """Extract player init params from HTML using regexes."""
    m = _PLAYER_INIT_RE.search(html)
    if m:
        item_id, site, key, timestamp, sig, ptype, scene_id = m.groups()
        return {
            "item_id": item_id,
            "site": site,
            "key": key,
            "timestamp": timestamp,
            "sig": sig or "",
            "type": ptype or "",
            "scene_id": scene_id or "",
        }

    # Fallback: find individual values in the page
    site_m = _SITE_RE.search(html)
    key_m = _KEY_RE.search(html)
    ts_m = _TIMESTAMP_RE.search(html)
    item_m = _ITEM_ID_RE.search(html)

    if site_m and key_m and ts_m and item_m:
        sig_m = _SIG_RE.search(html)
        type_m = _TYPE_RE.search(html)
        scene_m = _SCENE_ID_RE.search(html)
        return {
            "item_id": item_m.group(1),
            "site": site_m.group(1),
            "key": key_m.group(1),
            "timestamp": ts_m.group(1),
            "sig": sig_m.group(1) if sig_m else "",
            "type": type_m.group(1) if type_m else "",
            "scene_id": scene_m.group(1) if scene_m else "",
        }

    return None


def get_playlist_url_from_verify(
    session: CustomSession,
    item_id: str,
    site: str,
    key: str,
    timestamp: str,
    sig: str = "",
    player_type: str = "",
    scene_id: str = "",
    origin_url: str = "",
) -> tuple[str, dict[str, Any]]:
    """Call Digiflix verify API to obtain playlist URL and item metadata."""
    payload: dict[str, Any] = {
        "item_id": item_id,
        "site": site,
        "key": key,
        "timestamp": timestamp,
        "site_api_key": ADE_SITE_API_KEY,
    }
    if sig:
        payload["sig"] = sig
    if player_type:
        payload["type"] = player_type
    if scene_id:
        payload["scene_id"] = scene_id

    verify_headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://player.digiflix.video",
        "Referer": "https://player.digiflix.video/",
    }

    resp = session.post(ADE_VERIFY_URL, json=payload, headers=verify_headers, timeout=20)
    if resp.status_code != 200:
        raise ValueError(f"Digiflix verify API returned HTTP {resp.status_code}: {resp.text[:200]}")

    data = resp.json()
    if not data.get("success"):
        msg = data.get("message") or data.get("error") or str(data)
        raise ValueError(f"Digiflix verify failed: {msg}")

    result = data.get("result", {})
    playlist_url = result.get("playlist_url") or result.get("stream_url") or ""
    if not playlist_url:
        raise ValueError(f"No playlist_url in Digiflix verify response: {data}")

    return playlist_url, result
