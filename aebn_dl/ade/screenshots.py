"""Screenshot, gallery, and caps probe helpers for ADE."""
from __future__ import annotations

from html import unescape as html_unescape
import logging
import re
from typing import Any

from .constants import _ANY_CAPS_RE, _EA_THUMB_RE, _FRAME_RE, _FRAME_URL_RE
from .metadata import scenes_info as _scenes_info
from .thumbnails import frame_width_value as _frame_width_value, upgrade_frame_width as _upgrade_frame_width

try:
    from ..custom_session import CustomSession
except ImportError:
    from aebn_dl.custom_session import CustomSession  # type: ignore

logger = logging.getLogger(__name__)


def extract_ea_screenshots(html: str, master: str | int | None = None) -> list[dict[str, str]]:
    """Extract caps stills, optionally filtered to one master id."""
    want = str(master) if master not in (None, "") else ""
    seen: set[tuple[str, ...]] = set()
    shots: list[dict[str, str]] = []

    # Frame images (e.g. DVDErotik / ADE scene pages)
    for m in _FRAME_RE.finditer(html or ""):
        mst, offset = m.group(1), m.group(2)
        if want and mst != want:
            continue
        key = (mst, offset)
        if key in seen:
            continue
        seen.add(key)
        shots.append({
            "thumb": f"https://imgs4cdn.adultempire.com/frame/{mst}?w=1280&tc={offset}",
            "full": f"https://imgs4cdn.adultempire.com/frame/{mst}?w=3840&tc={offset}",
        })

    for m in _EA_THUMB_RE.finditer(html or ""):
        host = m.group(0).split("/n/")[0]
        gallery, mst, offset = m.group(1), m.group(3), m.group(4)
        if want and mst != want:
            continue
        key = (mst, offset)
        if key in seen:
            continue
        seen.add(key)
        shots.append({
            "thumb": f"{host}/n/{gallery}/1280/{mst}_{offset}_1280c.jpg",
            "full": f"{host}/n/{gallery}/3840/{mst}_{offset}_3840.jpg",
        })

    # Broad pass too (don't early-return): ADE movie pages mix widths/prefixes.
    for m in _ANY_CAPS_RE.finditer(html or ""):
        prefix, gallery, _width, mst, offset = m.group(1), m.group(2), m.group(3), m.group(4), m.group(5)
        if want and mst != want:
            continue
        key = (mst, offset)
        if key in seen:
            continue
        seen.add(key)
        host = m.group(0).split(f"/{prefix}/")[0]
        shots.append({
            "thumb": f"{host}/{prefix}/{gallery}/1280/{mst}_{offset}_1280c.jpg",
            "full": f"{host}/{prefix}/{gallery}/3840/{mst}_{offset}_3840.jpg",
        })
    return shots


def merge_shots(*lists: list[dict[str, str]] | None) -> list[dict[str, str]]:
    """Dedupe screenshot lists (by full URL) preserving order."""
    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for lst in lists:
        for s in lst or []:
            key = s.get("full") or s.get("thumb") or ""
            if key and key not in seen:
                seen.add(key)
                out.append(s)
    return out


def dedupe_groups(groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop cross-group duplicate stills (by full URL), keeping first occurrence."""
    seen: set[str] = set()
    for g in groups:
        uniq: list[dict[str, str]] = []
        for s in g.get("screenshots") or []:
            key = s.get("full") or s.get("thumb") or ""
            if key and key not in seen:
                seen.add(key)
                uniq.append(s)
        g["screenshots"] = uniq
    return groups


def extract_more_screens_params(html: str) -> list[dict[str, int]]:
    """Parse ShowMoreScreens2017(item, start, end, sceneID, ...) call params."""
    out: list[dict[str, int]] = []
    for m in re.finditer(r"ShowMoreScreens2017\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)", html or ""):
        try:
            out.append({"item": int(m.group(1)), "start": int(m.group(2)),
                        "end": int(m.group(3)), "scene": int(m.group(4))})
        except ValueError:
            continue
    # Dedupe by scene, keep order
    seen: set[int] = set()
    uniq: list[dict[str, int]] = []
    for p in out:
        if p["scene"] not in seen:
            seen.add(p["scene"])
            uniq.append(p)
    return uniq


def fetch_full_scene_shots(session: CustomSession, base_host: str,
                            params: list[dict[str, int]]) -> dict[str, list[dict[str, str]]]:
    """Call /Item/LoadSceneScreenshots per scene; return {sceneID: shots}."""
    out: dict[str, list[dict[str, str]]] = {}
    for p in params:
        try:
            r = session.get(f"{base_host}/Item/LoadSceneScreenshots",
                            params={"item": p["item"], "start": p["start"],
                                    "end": p["end"], "sceneID": p["scene"]},
                            timeout=20)
            if r.ok and r.text:
                shots = extract_ea_screenshots(r.text)
                if shots:
                    out[str(p["scene"])] = shots
                    logger.info("Full stills scene %s: %d", p["scene"], len(shots))
        except Exception as e:
            logger.warning("LoadSceneScreenshots failed scene %s: %s", p["scene"], e)
    return out


def extract_movie_page_blocks(html: str) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    """Split an ADE/EA movie page into full-list stills + per-scene blocks."""
    parts = re.split(r'<a name="scene_(\d+)"', html or "")
    full_shots = extract_ea_screenshots(parts[0]) if parts else []
    blocks: list[dict[str, Any]] = []
    for i in range(1, len(parts), 2):
        clip_id = parts[i]
        block = parts[i + 1] if i + 1 < len(parts) else ""
        title_m = re.search(
            r"/(?:clip|shop)/" + re.escape(clip_id) + r"/[^\"]*?\"[^>]*>(.*?)</a>",
            block, re.S | re.I,
        )
        title = re.sub(r"\s+", " ", html_unescape(title_m.group(1)) if title_m else "").strip()
        blocks.append({
            "clip_id": clip_id,
            "title": title or f"Scene {len(blocks) + 1}",
            "shots": extract_ea_screenshots(block),
        })
    return full_shots, blocks


_SCENE_WIDGET_RE = re.compile(
    r'<article\b[^>]*class="[^"]*\bscene-widget\b[^"]*"[^>]*>(.*?)</article>',
    re.DOTALL | re.IGNORECASE,
)


def extract_scene_widgets(html: str) -> list[dict[str, str]]:
    """Parse the scene cards on a movie/VOD page."""
    widgets: list[dict[str, str]] = []
    for m in _SCENE_WIDGET_RE.finditer(html or ""):
        tag, block = m.group(0), m.group(1)
        sid = re.search(r'data-scene-id="(\d+)"', tag, re.I)
        if not sid:
            continue
        mid = re.search(r'data-master-id="(\d+)"', tag, re.I)
        ds = re.search(r'data-src="([^"]+)"', block, re.I)
        if ds and _FRAME_URL_RE.fullmatch(ds.group(1)):
            frame = ds.group(1)
        else:
            frames = _FRAME_URL_RE.findall(block)
            frame = max(frames, key=_frame_width_value) if frames else ""
        title_m = re.search(r"<h6[^>]*>(.*?)</h6>", block, re.S | re.I)
        widgets.append({
            "scene_id": sid.group(1),
            "master_id": mid.group(1) if mid else "",
            "title": re.sub(
                r"\s+", " ", html_unescape(title_m.group(1)) if title_m else ""
            ).strip(),
            "frame": frame,
        })
    return widgets


def build_groups_from_page_blocks(
    item_detail: dict[str, Any],
    full_shots: list[dict[str, str]],
    blocks: list[dict[str, Any]],
    combined_limit: int = 40,
) -> list[dict[str, Any]] | None:
    """Build screenshot groups from real movie-page scene blocks."""
    if not blocks:
        return None
    scenes = _scenes_info(item_detail)
    total_end = max((s["end_s"] for s in scenes), default=0)
    combined = list(full_shots) or synth_screenshots(item_detail, None, limit=combined_limit)
    groups: list[dict[str, Any]] = [{
        "key": "all",
        "scene_id": None,
        "n": 0,
        "title": "Full movie (combined)",
        "start_s": 0,
        "end_s": total_end,
        "screenshots": combined,
    }]
    for i, b in enumerate(blocks):
        sc = scenes[i] if i < len(scenes) else {}
        groups.append({
            "key": f"scene-{i + 1}",
            "scene_id": sc.get("id") or b.get("clip_id"),
            "n": i + 1,
            "title": b.get("title") or sc.get("title") or f"Scene {i + 1}",
            "start_s": sc.get("start_s"),
            "end_s": sc.get("end_s"),
            "screenshots": b.get("shots") or [],
        })
    return groups


def synth_screenshots(item_detail: dict[str, Any], scene_id: str | int | None = None, limit: int = 40) -> list[dict[str, str]]:
    """Synthesize screenshot URLs from verify data (works for any ADE/EA title)."""
    master = str(item_detail.get("master_id") or "")
    if not master.isdigit():
        return []
    frames = item_detail.get("frames") or {}
    try:
        interval = max(int(frames.get("interval") or 10), 10)
    except (TypeError, ValueError):
        interval = 10

    start, end = 0, 0
    if scene_id:
        for sc in item_detail.get("scenes", []):
            if str(sc.get("id")) == str(scene_id):
                start, end = int(sc.get("start_seconds") or 0), int(sc.get("end_seconds") or 0)
                break
    else:
        scenes = item_detail.get("scenes", [])
        if scenes:
            end = int(scenes[-1].get("end_seconds") or 0)
    if end <= start:
        return []

    duration = end - start
    step = max(interval, round(duration / limit / interval) * interval or interval)
    gallery = master[-4:]
    shots: list[dict[str, str]] = []
    offset = (start // step) * step
    while offset <= end and len(shots) < limit:
        tag = f"{offset:05d}"
        shots.append({
            "thumb": f"https://caps1cdn.adultempire.com/n/{gallery}/1280/{master}_{tag}_1280c.jpg",
            "full": f"https://caps1cdn.adultempire.com/n/{gallery}/3840/{master}_{tag}_3840.jpg",
        })
        offset += step
    return shots


def shot_offset_seconds(shot: dict[str, str]) -> int | None:
    """Parse the frame offset (seconds) out of a caps or frame CDN URL."""
    url = (shot.get("full") or "") + " " + (shot.get("thumb") or "")
    m = re.search(r"[?&]tc=(\d+)", url)
    if m:
        try:
            return int(m.group(1))
        except (TypeError, ValueError):
            pass
    m = re.search(r"_(\d{4,6})_(?:10|320|1280c|3840)\.jpg", url)
    if not m:
        m = re.search(r"_(\d+)_", shot.get("full") or shot.get("thumb") or "")
    try:
        return int(m.group(1)) if m else None
    except (TypeError, ValueError):
        return None


def caps_probe_info(shots: list[dict[str, str]], start: int = 0,
                     end: int | None = None, step: int = 10) -> dict[str, Any] | None:
    """Describe the full caps range behind a movie (for the UI opt-in toggle)."""
    master = gallery = prefix = ""
    for s in shots or []:
        m = re.search(r"/([a-z])/(\d+)/\d+/(\d+)_\d+_\d+[a-z]?\.jpg",
                      s.get("full") or s.get("thumb") or "")
        if m:
            prefix, gallery, master = m.group(1), m.group(2), m.group(3)
            break
    if not master:
        return None
    if end is None:
        offs = [o for o in (shot_offset_seconds(s) for s in shots) if o is not None]
        end = max(offs) if offs else 0
    if end <= start:
        return None
    return {"prefix": prefix, "gallery": gallery, "master": master,
            "start": start, "end": end, "step": step,
            "count": (end - start) // step + 1}


def build_screenshot_groups(
    item_detail: dict[str, Any],
    html_shots: list[dict[str, str]] | None = None,
    per_scene_limit: int = 30,
    combined_limit: int = 40,
) -> list[dict[str, Any]]:
    """Group screenshots per scene + a combined (full-movie) group."""
    scenes = _scenes_info(item_detail)
    if not scenes:
        return []
    html_shots = html_shots or []

    # Bucket HTML thumbs by scene boundaries (offset seconds within [start, end]).
    buckets: dict[str, list[dict[str, str]]] = {s["id"]: [] for s in scenes if s["id"]}
    leftover: list[dict[str, str]] = []
    for shot in html_shots:
        off = shot_offset_seconds(shot)
        placed = False
        if off is not None:
            for s in scenes:
                if s["start_s"] <= off <= s["end_s"]:
                    if s["id"]:
                        buckets[s["id"]].append(shot)
                    placed = True
                    break
        if not placed:
            leftover.append(shot)

    groups: list[dict[str, Any]] = []
    total_end = max((s["end_s"] for s in scenes), default=0)
    combined = synth_screenshots(item_detail, None, limit=combined_limit)
    if not combined and html_shots:
        combined = list(html_shots)
    groups.append({
        "key": "all",
        "scene_id": None,
        "n": 0,
        "title": "Full movie (combined)",
        "start_s": 0,
        "end_s": total_end,
        "screenshots": combined,
    })
    for s in scenes:
        sid = s["id"]
        bucketed = buckets.get(sid, []) if html_shots else []
        shots = bucketed if bucketed else synth_screenshots(item_detail, sid, limit=per_scene_limit)
        groups.append({
            "key": f"scene-{s['n']}",
            "scene_id": sid,
            "n": s["n"],
            "title": s["title"] or f"Scene {s['n']}",
            "start_s": s["start_s"],
            "end_s": s["end_s"],
            "screenshots": shots,
        })
    return groups
