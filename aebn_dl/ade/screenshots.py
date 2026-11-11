"""Screenshot, gallery, and caps probe helpers for ADE."""
from __future__ import annotations

import logging
import re
from typing import Any

from .constants import _ANY_CAPS_RE, _EA_THUMB_RE, _FRAME_RE, _SCENE_WIDGET_RE
from .thumbnails import frame_width_value, upgrade_frame_width

try:
    from ..custom_session import CustomSession
except ImportError:
    from aebn_dl.custom_session import CustomSession  # type: ignore

logger = logging.getLogger(__name__)


def extract_ea_screenshots(
    html: str,
    master: str | int | None = None,
    item_id: str | int | None = None,
) -> list[dict[str, str]]:
    """Extract full-size screenshot URLs from thumbnail patterns on Elegant Angel."""
    seen: set[str] = set()
    shots: list[dict[str, str]] = []

    for m in _EA_THUMB_RE.finditer(html):
        prefix_folder, _thumb_w, m_id, frame_idx = m.groups()
        if master is not None and str(master) != m_id:
            continue
        thumb_url = m.group(0)
        full_url = f"https://capscdn.adultempire.com/n/{prefix_folder}/1280/{m_id}_{frame_idx}_1280c.jpg"
        if full_url not in seen:
            seen.add(full_url)
            shots.append({"url": full_url, "thumbnail": thumb_url})

    if shots:
        return shots

    target_id_str = str(item_id) if item_id is not None else (str(master) if master is not None else None)
    for m in _ANY_CAPS_RE.finditer(html):
        kind, prefix_folder, _src_w, m_id, frame_idx = m.groups()
        if target_id_str and m_id != target_id_str:
            continue
        thumb_url = m.group(0)
        full_url = f"https://capscdn.adultempire.com/{kind}/{prefix_folder}/1280/{m_id}_{frame_idx}_1280c.jpg"
        if full_url not in seen:
            seen.add(full_url)
            shots.append({"url": full_url, "thumbnail": thumb_url})

    return shots


def merge_shots(*lists: list[dict[str, str]] | None) -> list[dict[str, str]]:
    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for lst in lists:
        for s in lst or []:
            u = s.get("url") or ""
            if u and u not in seen:
                seen.add(u)
                out.append(s)
    return out


def dedupe_groups(groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen_ids: set[str] = set()
    out: list[dict[str, Any]] = []
    for g in groups:
        gid = str(g.get("scene_id") or "")
        label = g.get("label") or ""
        key = f"{gid}::{label}"
        if key in seen_ids:
            continue
        seen_ids.add(key)
        out.append(g)
    return out


def extract_more_screens_params(html: str) -> list[dict[str, int]]:
    """Find data-scene-id / data-total / data-item-id for lazy-loaded screenshot widgets."""
    out: list[dict[str, int]] = []
    seen: set[tuple[int, int]] = set()
    pattern = re.compile(
        r"""data-item-id=['"](\d+)['"][^>]*data-scene-id=['"](\d+)['"][^>]*data-total=['"](\d+)['"]"""
        r"""|data-scene-id=['"](\d+)['"][^>]*data-item-id=['"](\d+)['"][^>]*data-total=['"](\d+)['"]"""
        r"""|data-scene-id=['"](\d+)['"][^>]*data-total=['"](\d+)['"][^>]*data-item-id=['"](\d+)['"]""",
        re.IGNORECASE,
    )
    for m in pattern.finditer(html):
        groups = [g for g in m.groups() if g is not None]
        if len(groups) == 3:
            try:
                vals = [int(x) for x in groups]
                k = (vals[0], vals[1])
                if k not in seen:
                    seen.add(k)
                    out.append({"item_id": vals[0], "scene_id": vals[1], "total": vals[2]})
            except (ValueError, IndexError):
                continue
    return out


def fetch_full_scene_shots(
    session: CustomSession,
    base_host: str,
    item_id: int | str,
    scene_id: int | str,
    total: int = 16,
) -> list[dict[str, str]]:
    """Call the AJAX endpoint to fetch all screenshots for a scene."""
    url = f"{base_host}/item/scene-screenshots/{item_id}/{scene_id}?take={max(total, 16)}&skip=0"
    try:
        r = session.get(url, headers={"X-Requested-With": "XMLHttpRequest"}, timeout=10)
        if r.status_code == 200:
            return extract_ea_screenshots(r.text, item_id=item_id)
    except Exception as exc:
        logger.debug("fetch_full_scene_shots failed for %s/%s: %s", item_id, scene_id, exc)
    return []


def extract_movie_page_blocks(html: str) -> tuple[list[dict[str, str]], dict[str, list[dict[str, str]]]]:
    """Extract screenshots partitioned by movie-level vs scene-specific blocks."""
    movie_shots: list[dict[str, str]] = []
    scene_blocks: dict[str, list[dict[str, str]]] = {}

    scene_chunk_re = re.compile(
        r"""(?:id=['"]scene-(\d+)['"]|data-scene-id=['"](\d+)['"]|href=['"][^'"]*?/(\d+)/[^'"]*?streaming-scene(?:-video)?\.html)"""
        r"""([\s\S]*?)(?=(?:id=['"]scene-\d+['"]|data-scene-id=['"]\d+['"]|href=['"][^'"]*?/\d+/[^'"]*?streaming-scene|<footer|</body|$))""",
        re.IGNORECASE,
    )
    for m in scene_chunk_re.finditer(html):
        sid = m.group(1) or m.group(2) or m.group(3)
        chunk = m.group(4) or ""
        shots = extract_ea_screenshots(chunk)
        if shots:
            scene_blocks.setdefault(sid, []).extend(shots)

    all_shots = extract_ea_screenshots(html)
    assigned: set[str] = {s["url"] for shots in scene_blocks.values() for s in shots}
    for s in all_shots:
        if s["url"] not in assigned:
            movie_shots.append(s)

    return movie_shots, scene_blocks


def extract_scene_widgets(html: str) -> list[dict[str, str]]:
    """Extract per-scene preview thumbnails and scene IDs from card widgets."""
    widgets: list[dict[str, str]] = []
    for m in _SCENE_WIDGET_RE.finditer(html):
        sid, img_src = m.groups()
        widgets.append({"scene_id": sid, "image": upgrade_frame_width(img_src, 3840)})

    card_pattern = re.compile(
        r'<a[^>]+href="[^"]*?/(\d+)/[^"]*?streaming-scene(?:-video)?\.html"[^>]*>([\s\S]*?)</a>',
        re.IGNORECASE,
    )
    for m in card_pattern.finditer(html):
        sid, inner = m.groups()
        imgs = _FRAME_URL_RE_INTERNAL.findall(inner)
        if imgs:
            best_img = max(imgs, key=frame_width_value)
            widgets.append({"scene_id": sid, "image": upgrade_frame_width(best_img, 3840)})

    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for w in widgets:
        if w["scene_id"] not in seen:
            seen.add(w["scene_id"])
            out.append(w)
    return out


_FRAME_URL_RE_INTERNAL = re.compile(
    r"https?://imgs\d?cdn\.adultempire\.com/frame/\d+\?[^\s\"\'\<\>]*?tc=\d+",
    re.IGNORECASE,
)


def build_groups_from_page_blocks(
    movie_shots: list[dict[str, str]],
    scene_blocks: dict[str, list[dict[str, str]]],
    scenes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []

    scene_map: dict[str, dict[str, Any]] = {}
    for sc in scenes:
        scene_map[str(sc.get("id") or "")] = sc

    for sid, shots in scene_blocks.items():
        sc = scene_map.get(sid, {})
        label = f"Scene {sc.get('n', '')}: {sc.get('title', '')}".strip(": ") if sc else f"Scene {sid}"
        groups.append({
            "scene_id": sid,
            "label": label,
            "scene_number": sc.get("n"),
            "screenshots": shots,
        })

    if movie_shots:
        groups.insert(0, {
            "scene_id": None,
            "label": "Movie / Gallery",
            "scene_number": None,
            "screenshots": movie_shots,
        })

    return groups


def synth_screenshots(
    item_detail: dict[str, Any],
    scene_id: str | int | None = None,
    movie_id: str | int | None = None,
) -> list[dict[str, str]]:
    """Fallback: synthesize frame CDN URLs using tc offsets."""
    m_id = str(movie_id or item_detail.get("id") or item_detail.get("item_id") or "")
    if not m_id:
        return []

    target_scene: dict[str, Any] | None = None
    if scene_id:
        for s in item_detail.get("scenes", []) or []:
            if str(s.get("id")) == str(scene_id):
                target_scene = s
                break

    if target_scene:
        start = int(target_scene.get("start_seconds") or 0)
        end = int(target_scene.get("end_seconds") or (start + 600))
    else:
        start = 0
        end = int(item_detail.get("length_seconds") or 7200)

    duration = max(end - start, 60)
    num_samples = 12
    step = max(duration // (num_samples + 1), 5)
    tcs = [start + step * i for i in range(1, num_samples + 1)]

    shots: list[dict[str, str]] = []
    for tc in tcs:
        full = f"https://imgs1cdn.adultempire.com/frame/{m_id}?tc={tc}&w=3840"
        thumb = f"https://imgs1cdn.adultempire.com/frame/{m_id}?tc={tc}&w=320"
        shots.append({"url": full, "thumbnail": thumb})
    return shots


def shot_offset_seconds(shot: dict[str, str]) -> int | None:
    u = shot.get("url") or ""
    m = _FRAME_RE.search(u)
    if m:
        try:
            return int(m.group(2))
        except ValueError:
            return None
    return None


def caps_probe_info(
    shots: list[dict[str, str]],
    start: int = 0,
    end: int = 0,
) -> dict[str, Any]:
    return {
        "count": len(shots),
        "start_offset_s": start,
        "end_offset_s": end,
        "has_highres": any("1280" in s.get("url", "") or "3840" in s.get("url", "") for s in shots),
    }


def build_screenshot_groups(
    item_detail: dict[str, Any],
    page_html: str,
    scene_id: str | int | None = None,
    session: CustomSession | None = None,
    base_url: str = "",
) -> list[dict[str, Any]]:
    """Assemble screenshot groups for UI consumption."""
    from .metadata import scenes_info

    scenes = scenes_info(item_detail)
    movie_shots, scene_blocks = extract_movie_page_blocks(page_html)

    # For Elegant Angel, probe full scene screenshots if we have session and base_url
    if session and base_url:
        parsed_base = f"{CustomSession.__name__}"  # just dummy reference
        from urllib.parse import urlparse
        p = urlparse(base_url)
        base_host = f"{p.scheme}://{p.netloc}"
        params = extract_more_screens_params(page_html)
        for prm in params:
            sid = str(prm["scene_id"])
            if sid not in scene_blocks or len(scene_blocks[sid]) < prm["total"]:
                extra = fetch_full_scene_shots(session, base_host, prm["item_id"], sid, prm["total"])
                if extra:
                    scene_blocks[sid] = merge_shots(scene_blocks.get(sid), extra)

    groups = build_groups_from_page_blocks(movie_shots, scene_blocks, scenes)

    # If single scene requested and no screenshots found, try direct extraction or synthesis
    if scene_id and not any(g.get("screenshots") for g in groups):
        direct = extract_ea_screenshots(page_html, master=scene_id, item_id=item_detail.get("id"))
        if not direct:
            direct = synth_screenshots(item_detail, scene_id=scene_id)
        if direct:
            groups.append({
                "scene_id": str(scene_id),
                "label": f"Scene {scene_id}",
                "scene_number": None,
                "screenshots": direct,
            })

    return dedupe_groups(groups)
