"""Player parameters extraction and verify API resolution."""
from __future__ import annotations

import logging
import re
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
    """Extract AEVideoPlayer init params from HTML."""
    if not html:
        return None

    # 1. Try regex on the player initialization block
    m = _PLAYER_INIT_RE.search(html)
    if m:
        item_id, site, key, timestamp, sig = m.groups()[:5]
        # Also try to extract scene_id and type from nearby within the call
        scene_m = _SCENE_ID_RE.search(html, m.start(), min(len(html), m.end() + 500))
        type_m = _TYPE_RE.search(html, m.start(), min(len(html), m.end() + 500))
        return {
            "item_id": item_id,
            "scene_id": scene_m.group(1) if scene_m else "",
            "type": type_m.group(1) if type_m else "",
            "site": site,
            "key": key,
            "timestamp": timestamp,
            "sig": sig or "",
        }

    # 2. Broader flexible search within AEVideoPlayer(...) block
    call_m = re.search(r"AEVideoPlayer\s*\(\s*\{([^}]+)\}", html, re.DOTALL | re.IGNORECASE)
    if call_m:
        block = call_m.group(1)
        item_m = _ITEM_ID_RE.search(block)
        site_m = _SITE_RE.search(block)
        key_m = _KEY_RE.search(block)
        ts_m = _TIMESTAMP_RE.search(block)
        sig_m = _SIG_RE.search(block)
        scene_m = _SCENE_ID_RE.search(block)
        type_m = _TYPE_RE.search(block)

        if key_m and ts_m and sig_m:
            return {
                "item_id": item_m.group(1) if item_m else "",
                "scene_id": scene_m.group(1) if scene_m else "",
                "type": type_m.group(1) if type_m else "",
                "site": site_m.group(1) if site_m else ADE_SITE_API_KEY,
                "key": key_m.group(1),
                "timestamp": ts_m.group(1),
                "sig": sig_m.group(1),
            }

    # 3. Fallback: extract individual fields from anywhere in the document
    item_ids = _ITEM_ID_RE.findall(html)
    scene_ids = _SCENE_ID_RE.findall(html)
    sites = _SITE_RE.findall(html)
    keys = _KEY_RE.findall(html)
    timestamps = _TIMESTAMP_RE.findall(html)
    sigs = _SIG_RE.findall(html)
    types = _TYPE_RE.findall(html)

    if keys and timestamps and sigs:
        return {
            "item_id": item_ids[0] if item_ids else "",
            "scene_id": scene_ids[0] if scene_ids else "",
            "type": types[0] if types else "",
            "site": sites[0] if sites else ADE_SITE_API_KEY,
            "key": keys[0],
            "timestamp": timestamps[0],
            "sig": sigs[0],
        }

    return None


def get_playlist_url_from_verify(
    session: CustomSession,
    item_id: str,
    key: str,
    timestamp: str,
    sig: str = "",
    site: str = ADE_SITE_API_KEY,
    stream_type: str = "VOD",
    scene_id: str | int | None = None,
) -> dict[str, Any]:
    """Call the digiflix verify endpoint to get the streaming URL."""
    payload: dict[str, Any] = {
        "item_id": int(item_id),
        "encrypted_customer_id": key,
        "signature": sig,
        "timestamp": timestamp,
        "stream_type": stream_type,
        "initiate_tracking": True,
        "forcehd": None,
    }
    if scene_id:
        payload["scene_id"] = int(scene_id)

    headers = {
        "Content-Type": "application/json",
        "api_key": site,
    }

    resp = session.post(ADE_VERIFY_URL, json=payload, headers=headers)
    resp.raise_for_status()
    return resp.json()
