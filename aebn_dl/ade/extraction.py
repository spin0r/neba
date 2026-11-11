"""Main manifest and preview extraction logic for ADE, Elegant Angel, and DVDErotik."""
from __future__ import annotations

from html import unescape as html_unescape
import logging
import os
import re
from typing import Any
from urllib.parse import urlparse

from .auth import auth_error, cookie_hint, no_player_error, site_for_url, upper_first
from .constants import (
    ADE_CLIP_RE,
    ADE_MOVIE_RE,
    EA_MOVIE_RE,
    EA_SCENE_RE,
    _ITEM_ID_RE,
)
from .metadata import extract_ade_duration_seconds, resolve_ade_title, scenes_info
from .player import extract_player_params, get_playlist_url_from_verify
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
    synth_screenshots,
)
from .session import get_session
from .thumbnails import extract_scene_backdrop, extract_scene_thumbnail, upgrade_frame_width

try:
    from ..custom_session import CustomSession
except ImportError:
    from aebn_dl.custom_session import CustomSession  # type: ignore

logger = logging.getLogger(__name__)


def _get_clip_preview(session: CustomSession, scene_id: str, url: str, html: str | None = None) -> dict[str, Any]:
    """Fallback: preview trailer for clip when VOD not authorized."""
    url_tc_m = re.search(r"[?&]tc=(\d+)", url)
    url_tc = url_tc_m.group(1) if url_tc_m else None
    if html is None:
        resp = session.get(url)
        resp.raise_for_status()
        html = resp.text

    # Find parent movie VOD item ID from data-movie-id attributes
    movie_ids = re.findall(r'data-movie-id="(\d+)"', html)
    if not movie_ids:
        raise ValueError("Could not find movie ID on clip page")

    vod_item_id = movie_ids[0]

    # Try to get player params from the parent movie's VOD page
    movie_slug_match = re.search(r'href="/(\d+)/([^"]+?)-porn-videos\.html"', html)
    if movie_slug_match:
        parent_vod_id = movie_slug_match.group(1)
        parent_slug = movie_slug_match.group(2)
        u = urlparse(url)
        host = f"{u.scheme or 'https'}://{u.netloc or 'www.adultdvdempire.com'}"
        vod_url = f"{host}/{parent_vod_id}/{parent_slug}-porn-videos.html"

        if "dvderotik" in url.lower():
            vod_resp = session.get(vod_url)
        else:
            vod_resp = session.get(vod_url + "?viewpart=videoplayer&stream_type=0&tc=")
        if vod_resp.ok:
            params = extract_player_params(vod_resp.text)
            if params and params.get("key"):
                result = get_playlist_url_from_verify(
                    session=session,
                    item_id=params["item_id"],
                    key=params["key"],
                    timestamp=params["timestamp"],
                    sig=params["sig"],
                    site=params["site"],
                    stream_type="VOD",
                )
                if result.get("is_authorized") and result.get("playlist_url"):
                    item_detail = result.get("item_detail", {})
                    raw_title = item_detail.get("title") or item_detail.get("vod_title") or "Unknown"
                    title = resolve_ade_title(raw_title, item_detail, scene_id)
                    dur_s = extract_ade_duration_seconds(item_detail, scene_id, result.get("playlist_url", ""))
                    scene_thumb = extract_scene_thumbnail(html, target_tc=url_tc)
                    return {
                        "title": title,
                        "item_id": params["item_id"],
                        "scene_id": scene_id,
                        "duration_s": dur_s,
                        "playlist_url": result.get("playlist_url"),
                        "base_url": result.get("base_url"),
                        "streams": result.get("streams", []),
                        "is_authorized": result.get("is_authorized", False),
                        "item_detail": item_detail,
                        "ppm_remaining": result.get("customer_ppm_time_remaining_free", 0),
                        "scene_thumb": scene_thumb,
                    }

    # Fallback: use preview
    result = get_playlist_url_from_verify(
        session=session,
        item_id=vod_item_id,
        key="",
        timestamp="",
        sig="",
        stream_type="preview",
    )

    item_detail = result.get("item_detail", {})
    raw_title = item_detail.get("title") or item_detail.get("vod_title") or "Preview"
    title = resolve_ade_title(raw_title, item_detail, scene_id)
    dur_s = extract_ade_duration_seconds(item_detail, scene_id, result.get("playlist_url", ""))
    scene_thumb = extract_scene_thumbnail(html, target_tc=url_tc)

    return {
        "title": title,
        "item_id": vod_item_id,
        "scene_id": scene_id,
        "duration_s": dur_s,
        "playlist_url": result.get("playlist_url"),
        "base_url": result.get("base_url"),
        "streams": result.get("streams", []),
        "is_authorized": result.get("is_authorized", False),
        "item_detail": item_detail,
        "ppm_remaining": result.get("customer_ppm_time_remaining_free", 0),
        "scene_thumb": scene_thumb,
    }


def get_ade_manifest(url: str, cookies_str: str | None = None) -> dict[str, Any]:
    """
    Get the streaming manifest URL for an AdultDVDEmpire / Elegant Angel video.
    """
    if not cookies_str:
        cookies_str = os.getenv("ADE_COOKIES", "")

    session = get_session(cookies_str)

    clip_match = ADE_CLIP_RE.search(url)
    ea_scene_match = EA_SCENE_RE.search(url)
    ea_movie_match = EA_MOVIE_RE.search(url)
    movie_match = ADE_MOVIE_RE.search(url)

    scene_id = None
    vod_item_id = None
    url_tc_m = re.search(r"[?&]tc=(\d+)", url)
    url_tc = url_tc_m.group(1) if url_tc_m else None
    if clip_match:
        scene_id = clip_match.group(1)
    elif ea_scene_match:
        scene_id = ea_scene_match.group(1)
    elif movie_match:
        vod_item_id = movie_match.group(1)

    # Clip / scene pages
    if clip_match or ea_scene_match:
        logger.info("Fetching clip page: %s", url)
        resp = session.get(url)
        try:
            resp.raise_for_status()
        except Exception as e:
            logger.error("HTTP %d fetching %s: %s", resp.status_code, url, e)
            if resp.status_code == 500:
                preview = resp.text[:800] if resp.text else "(empty)"
                logger.error("Response preview: %s", preview)
                site_name, box = site_for_url(url)
                if "elegantangel.com" in url.lower():
                    raise ValueError(
                        f"{site_name}: Server returned HTTP 500. This may indicate missing or expired "
                        f"cookies. {upper_first(cookie_hint(cookies_str, site_name, box))}"
                    ) from e
            raise

        html = resp.text
        params = extract_player_params(html)
        if not params or not params.get("key") or not params.get("sig"):
            site, box = site_for_url(resp.url)
            raise no_player_error(html, resp.url, cookies_str, site, box)

        logger.info(
            "Clip player params: item=%s scene=%s type=%s site=%s key=%s...",
            params["item_id"], params.get("scene_id"), params.get("type"), params["site"], params["key"][:10],
        )

        stream_type = params.get("type") or "scene"
        if stream_type.lower() == "previewscene":
            stream_type = "scene"

        result = get_playlist_url_from_verify(
            session=session,
            item_id=params["item_id"],
            key=params["key"],
            timestamp=params["timestamp"],
            sig=params["sig"],
            site=params["site"],
            stream_type=stream_type if stream_type in ("scene", "VOD", "preview") else "scene",
            scene_id=params.get("scene_id") or scene_id,
        )

        if result.get("is_authorized") and result.get("playlist_url"):
            item_detail = result.get("item_detail", {})
            raw_movie_title = html_unescape(item_detail.get("title") or item_detail.get("vod_title") or "Unknown").strip()
            cur_scene_id = params.get("scene_id") or scene_id
            scene_title = ""
            if cur_scene_id:
                for sc in item_detail.get("scenes", []):
                    if str(sc.get("id")) == str(cur_scene_id):
                        scene_title = html_unescape(sc.get("title", "")).strip()
                        break

            title = resolve_ade_title(raw_movie_title, item_detail, cur_scene_id)
            dur_s = extract_ade_duration_seconds(item_detail, cur_scene_id, result.get("playlist_url", ""))
            master_id = str(item_detail.get("master_id") or "")
            real_shots = extract_ea_screenshots(html, master_id or None)
            flat_shots = real_shots or extract_ea_screenshots(html) or synth_screenshots(item_detail, cur_scene_id)
            scene_groups = build_screenshot_groups(item_detail, extract_ea_screenshots(html) or None)
            caps_probe = None
            scene_thumb = None

            try:
                pm = re.search(r'href="((?:/shop)?/(\d+)/(?!category/)([^"]+?)-porn-videos\.html)"', html or "")
                if pm and cur_scene_id:
                    u = urlparse(url)
                    movie_url = f"{u.scheme or 'https'}://{u.netloc or 'www.adultdvdempire.com'}{pm.group(1)}"
                    logger.info("Clip parent movie page: %s", movie_url)
                    mresp = session.get(movie_url, timeout=20)
                    if mresp.ok and mresp.text:
                        widgets = extract_scene_widgets(mresp.text)
                        mw = next((w for w in widgets if w.get("scene_id") == str(cur_scene_id)), None)
                        if not mw and scene_title:
                            want = re.sub(r"\W+", " ", scene_title).strip().lower()
                            mw = next((w for w in widgets if re.sub(r"\W+", " ", w.get("title", "")).strip().lower() == want), None)

                        if mw and mw.get("frame"):
                            frame_thumb = upgrade_frame_width(mw["frame"], 1280)
                            tc_m = re.search(r"[?&]tc=(\d+)", mw["frame"])
                            logger.info("Scene thumb (frame) from parent movie scene %s: tc=%s (w=1280)",
                                        mw.get("scene_id"), tc_m.group(1) if tc_m else "?")
                            if not scene_thumb:
                                scene_thumb = extract_scene_backdrop(html) or frame_thumb

                        _mfull, mblocks = extract_movie_page_blocks(mresp.text)
                        blk = next((b for b in mblocks if str(b.get("clip_id")) == str(cur_scene_id)), None)
                        if blk and (blk.get("shots") or extract_more_screens_params(mresp.text)):
                            more2 = [p for p in extract_more_screens_params(mresp.text) if str(p["scene"]) == str(cur_scene_id)]
                            if more2:
                                mu = urlparse(movie_url)
                                mhost = f"{mu.scheme or 'https'}://{mu.netloc}"
                                fmap = fetch_full_scene_shots(session, mhost, more2)
                                if str(cur_scene_id) in fmap:
                                    blk["shots"] = merge_shots(fmap[str(cur_scene_id)], blk.get("shots"))

                            scene_shots = merge_shots(blk.get("shots"))
                            if scene_shots:
                                flat_shots = merge_shots(scene_shots, flat_shots)
                                infos = scenes_info(item_detail)
                                info = next((s for s in infos if s.get("id") == str(cur_scene_id)), {})
                                if more2:
                                    caps_probe = caps_probe_info(
                                        scene_shots, start=more2[0]["start"],
                                        end=more2[0]["end"], step=10,
                                    )
                                scene_groups = dedupe_groups([{
                                    "key": f"scene-{info.get('n') or 1}",
                                    "scene_id": str(cur_scene_id),
                                    "n": info.get("n") or 1,
                                    "title": blk.get("title") or info.get("title") or scene_title or f"Scene {cur_scene_id}",
                                    "start_s": info.get("start_s"),
                                    "end_s": info.get("end_s"),
                                    "screenshots": scene_shots,
                                }])
                                logger.info("Parent-movie exact scene %s: %d stills", cur_scene_id, len(scene_shots))
            except Exception as e:
                logger.warning("Parent-movie scene stills failed: %s", e)

            scene_thumb = scene_thumb or extract_scene_thumbnail(html, target_tc=url_tc)
            return {
                "title": title,
                "movie_title": raw_movie_title,
                "scene_title": scene_title,
                "item_id": params["item_id"],
                "scene_id": cur_scene_id,
                "duration_s": dur_s,
                "playlist_url": result.get("playlist_url"),
                "base_url": result.get("base_url"),
                "streams": result.get("streams", []),
                "is_authorized": result.get("is_authorized", False),
                "item_detail": item_detail,
                "ppm_remaining": result.get("customer_ppm_time_remaining_free", 0),
                "screenshots": flat_shots,
                "screenshot_groups": scene_groups,
                "caps_probe": caps_probe,
                "scenes": scenes_info(item_detail),
                "scene_thumb": scene_thumb,
            }

        try:
            return _get_clip_preview(session, scene_id, url, html)
        except Exception as preview_err:
            logger.warning("Preview fallback failed: %s", preview_err)
            raise auth_error(cookies_str, url) from preview_err

    # Elegant Angel movie pages
    if ea_movie_match and not ea_scene_match:
        logger.info("Fetching Elegant Angel movie page: %s", url)
        resp = session.get(url)
        resp.raise_for_status()
        html = resp.text
        params = extract_player_params(html)
        if not params:
            raise no_player_error(html, resp.url, cookies_str, "Elegant Angel", "ea")

        logger.info(
            "EA movie player params: item_id=%s, site=%s, key=%s...",
            params["item_id"], params["site"], params["key"][:10],
        )
        result = get_playlist_url_from_verify(
            session=session,
            item_id=params["item_id"],
            key=params["key"],
            timestamp=params["timestamp"],
            sig=params["sig"],
            site=params["site"],
            stream_type="VOD",
            scene_id=params.get("scene_id") or None,
        )
        if not result.get("is_authorized"):
            raise auth_error(cookies_str, resp.url)

        item_detail = result.get("item_detail", {})
        raw_movie_title = html_unescape(item_detail.get("title") or item_detail.get("vod_title") or "Unknown").strip()
        title = resolve_ade_title(raw_movie_title, item_detail, None)
        dur_s = extract_ade_duration_seconds(item_detail, None, result.get("playlist_url", ""))
        return {
            "title": title,
            "movie_title": raw_movie_title,
            "scene_title": "",
            "item_id": params["item_id"],
            "scene_id": None,
            "duration_s": dur_s,
            "playlist_url": result.get("playlist_url"),
            "base_url": result.get("base_url"),
            "streams": result.get("streams", []),
            "is_authorized": result.get("is_authorized", False),
            "item_detail": item_detail,
            "ppm_remaining": result.get("customer_ppm_time_remaining_free", 0),
            "screenshots": synth_screenshots(item_detail, None),
            "screenshot_groups": build_screenshot_groups(item_detail, None),
            "scenes": scenes_info(item_detail),
        }

    # Movie/VOD pages
    is_dvderotik = "dvderotik" in url.lower()
    if is_dvderotik:
        logger.info("Fetching DVDErotik movie page: %s", url)
        resp = session.get(url)
        resp.raise_for_status()
        html = resp.text
        params = extract_player_params(html)
    else:
        base_url = url.rstrip("/")
        player_url = base_url + ("&" if "?" in base_url else "?") + "viewpart=videoplayer&stream_type=0&tc="
        logger.info("Fetching player page: %s", player_url)
        resp = session.get(player_url)
        resp.raise_for_status()
        html = resp.text

        params = extract_player_params(html)
        if not params:
            logger.info("No player params in viewpart page (%d bytes), retrying plain page", len(html))
            try:
                plain = session.get(url)
                plain.raise_for_status()
                plain_params = extract_player_params(plain.text)
                if plain_params:
                    params, resp, html = plain_params, plain, plain.text
                    logger.info("Plain page had the player params — using them")
            except Exception as e:
                logger.warning("Plain-page retry failed: %s", e)

    if not params:
        site, box = site_for_url(resp.url)
        raise no_player_error(html, resp.url, cookies_str, site, box)

    logger.info(
        "Player params: item_id=%s, site=%s, key=%s...",
        params["item_id"], params["site"], params["key"][:10],
    )

    stream_type = params.get("type") or "VOD"
    result = get_playlist_url_from_verify(
        session=session,
        item_id=params["item_id"],
        key=params["key"],
        timestamp=params["timestamp"],
        sig=params["sig"],
        site=params["site"],
        stream_type=stream_type if stream_type in ("VOD", "scene", "preview") else "VOD",
        scene_id=params.get("scene_id") or None,
    )

    if not result.get("is_authorized"):
        raise auth_error(cookies_str, resp.url)

    item_detail = result.get("item_detail", {})
    raw_movie_title = html_unescape(item_detail.get("title") or item_detail.get("vod_title") or "Unknown").strip()
    scene_title = ""
    if scene_id:
        for sc in item_detail.get("scenes", []):
            if str(sc.get("id")) == str(scene_id):
                scene_title = html_unescape(sc.get("title", "")).strip()
                break
    title = resolve_ade_title(raw_movie_title, item_detail, scene_id)
    dur_s = extract_ade_duration_seconds(item_detail, scene_id, result.get("playlist_url", ""))

    ea_shots = extract_ea_screenshots(html)
    page_full: list[dict[str, str]] = []
    page_blocks: list[dict[str, Any]] = []
    more_params: list[dict[str, int]] = []
    try:
        plain_resp = resp if is_dvderotik else session.get(url, timeout=20)
        if plain_resp.ok and plain_resp.text:
            if not is_dvderotik and plain_resp.text != html:
                ea_shots = merge_shots(ea_shots, extract_ea_screenshots(plain_resp.text))
            page_full, page_blocks = extract_movie_page_blocks(plain_resp.text)
            ea_shots = merge_shots(ea_shots, page_full, *[b.get("shots") or [] for b in page_blocks])
            more_params = extract_more_screens_params(plain_resp.text)
            if more_params and page_blocks:
                u = urlparse(url)
                host = f"{u.scheme or 'https'}://{u.netloc or 'www.adultdvdempire.com'}"
                full_map = fetch_full_scene_shots(session, host, more_params)
                if full_map:
                    by_clip = {str(b.get("clip_id")): b for b in page_blocks}
                    for sid, shots in full_map.items():
                        if sid in by_clip:
                            by_clip[sid]["shots"] = merge_shots(shots, by_clip[sid].get("shots"))
                        else:
                            page_blocks.append({"clip_id": sid, "title": f"Scene {sid}", "shots": shots})
                    ea_shots = merge_shots(ea_shots, *[s for s in full_map.values()])
    except Exception as e:
        logger.warning("Plain-page stills fetch failed: %s", e)

    flat_shots = merge_shots(ea_shots, page_full, *[b.get("shots") or [] for b in page_blocks]) or synth_screenshots(item_detail, scene_id)
    probe_end = max([p["end"] for p in more_params], default=0) or None
    caps_probe = caps_probe_info(ea_shots, start=0, end=probe_end, step=10)
    groups = dedupe_groups(
        build_groups_from_page_blocks(item_detail, page_full, page_blocks)
        or build_screenshot_groups(item_detail, ea_shots or None)
        or []
    )
    scene_thumb = extract_scene_thumbnail(html, target_tc=url_tc)
    return {
        "title": title,
        "movie_title": raw_movie_title,
        "scene_title": scene_title,
        "item_id": params["item_id"],
        "scene_id": scene_id,
        "duration_s": dur_s,
        "playlist_url": result.get("playlist_url"),
        "base_url": result.get("base_url"),
        "streams": result.get("streams", []),
        "is_authorized": result.get("is_authorized", False),
        "item_detail": item_detail,
        "ppm_remaining": result.get("customer_ppm_time_remaining_free", 0),
        "screenshots": flat_shots,
        "screenshot_groups": groups,
        "caps_probe": caps_probe,
        "scenes": scenes_info(item_detail),
        "scene_thumb": scene_thumb,
    }


def get_ade_preview_manifest(url: str) -> dict[str, Any]:
    """
    Get the free preview/trailer manifest URL for an ADE video.
    """
    session = get_session()

    clip_match = ADE_CLIP_RE.search(url)
    movie_match = ADE_MOVIE_RE.search(url)

    item_id = None
    if clip_match:
        item_id = clip_match.group(1)
    elif movie_match:
        resp = session.get(url)
        resp.raise_for_status()
        item_ids = _ITEM_ID_RE.findall(resp.text)
        if item_ids:
            item_id = item_ids[-1]

    if not item_id:
        raise ValueError("Could not extract item_id from URL")

    result = get_playlist_url_from_verify(
        session=session,
        item_id=item_id,
        key="",
        timestamp="",
        sig="",
        stream_type="preview",
    )

    return {
        "title": result.get("item_detail", {}).get("vod_title", "Preview"),
        "item_id": item_id,
        "playlist_url": result.get("playlist_url"),
        "streams": result.get("streams", []),
        "is_authorized": result.get("is_authorized", False),
    }
