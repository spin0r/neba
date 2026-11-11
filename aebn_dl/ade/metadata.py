"""Scene metadata, duration calculation, and title resolution."""
from __future__ import annotations

import re
from html import unescape as html_unescape
from typing import Any


def scenes_info(item_detail: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalize verify `scenes` into UI-friendly metadata."""
    out: list[dict[str, Any]] = []
    for i, sc in enumerate(item_detail.get("scenes", []) or []):
        try:
            start_s = int(sc.get("start_seconds") or 0)
        except (TypeError, ValueError):
            start_s = 0
        try:
            end_s = int(sc.get("end_seconds") or 0)
        except (TypeError, ValueError):
            end_s = 0
        title = html_unescape(str(sc.get("title") or "")).strip()
        out.append({
            "n": i + 1,
            "id": str(sc.get("id") or ""),
            "title": title,
            "performers": sc.get("performers") or sc.get("stars") or [],
            "start_s": start_s,
            "end_s": end_s,
        })
    return out


def extract_ade_duration_seconds(
    item_detail: dict[str, Any],
    scene_id: str | int | None = None,
    playlist_url: str = "",
) -> int:
    """
    Extract the accurate duration in seconds for an ADE movie or clip/scene.
    ADE's API returns trailer/preview length in some fields or length in minutes.
    This resolves scene boundaries or full movie duration accurately.
    """
    # 1. If scene_id is specified (clip/scene page), find the specific scene duration
    if scene_id:
        for s in item_detail.get("scenes", []):
            if str(s.get("id")) == str(scene_id):
                start_s = s.get("start_seconds", 0)
                end_s = s.get("end_seconds", 0)
                if end_s > start_s:
                    return int(end_s - start_s)

    # 2. Check total seconds across all scenes if present
    scenes = item_detail.get("scenes", [])
    if scenes:
        max_end = max((s.get("end_seconds", 0) for s in scenes), default=0)
        if max_end > 0:
            return int(max_end)

    # 3. Check explicit duration fields in item_detail
    for key in ("length_seconds", "duration_seconds", "duration", "total_seconds"):
        val = item_detail.get(key)
        if val and isinstance(val, (int, float)) and val > 0:
            return int(val)

    # 4. Check length in minutes
    for key in ("length_minutes", "minutes", "length"):
        val = item_detail.get(key)
        if val:
            try:
                mins = float(val)
                if mins > 0:
                    return int(mins * 60)
            except (ValueError, TypeError):
                pass

    # 5. Extract from playlist URL query params if present (e.g. ?dur=...)
    if playlist_url:
        dur_m = re.search(r"[?&](?:dur|duration)=(\d+)", playlist_url)
        if dur_m:
            return int(dur_m.group(1))

    return 0


def resolve_ade_title(
    base_title: str,
    item_detail: dict[str, Any],
    scene_id: str | int | None = None,
) -> str:
    """Build a descriptive, clean title for the movie or scene."""
    title = base_title or item_detail.get("title") or item_detail.get("name") or "video"
    if scene_id:
        for s in item_detail.get("scenes", []):
            if str(s.get("id")) == str(scene_id):
                stitle = s.get("title")
                if stitle:
                    return f"{title} - {stitle}"
                snum = s.get("scene_number") or s.get("scene_index")
                if snum:
                    return f"{title} - Scene {snum}"
                return f"{title} - Scene {scene_id}"
    return title
