from __future__ import annotations

from html import unescape as html_unescape
import json
import logging
import os
import re
from typing import Any

try:
    from .custom_session import CustomSession
except ImportError:
    from aebn_dl.custom_session import CustomSession  # type: ignore

try:
    from dotenv import load_dotenv

    load_dotenv()
    load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"), override=False)
    load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"), override=False)
except ImportError:
    pass

logger = logging.getLogger(__name__)

ADE_SITE_API_KEY = "60f039441fff44b4b08c64a3b4a64afe"
ADE_VERIFY_URL = "https://player.digiflix.video/verify"

# Regex: adultdvdempire.com, adultempire.com or elegantangel.com (same Empire backend) URLs
ADE_URL_RE = re.compile(
    r"https?://(?:www\.)?(?:adultdvdempire|adultempire|elegantangel)\.com/\S+",
    re.IGNORECASE,
)

# Patterns for movie/clip pages
# Movie:  /628754/milf-gangbang-3-porn-movies.html
# VOD:    /641690/milf-gangbang-3-porn-videos.html
# Clip:   /clip/1786404/hot-stepsis-wants-creampie-streaming-scene.html
ADE_MOVIE_RE = re.compile(
    r"/(\d+)/([^/]+?)(?:-porn-movies|-porn-videos)?\.html",
    re.IGNORECASE,
)
ADE_CLIP_RE = re.compile(
    r"/clip/(\d+)/([^/]+?)(?:-streaming-scene)?\.html",
    re.IGNORECASE,
)

# Elegant Angel (same Empire/digiflix backend) page patterns
# Scene:  /1789087/elegant-angel-all-fucks-given-from-summer-vixen-streaming-scene-video.html
# Movie:  /5099205/big-wet-asses-34-streaming-porn-videos.html
EA_SCENE_RE = re.compile(
    r"/(\d+)/[^/]*?streaming-scene-video\.html",
    re.IGNORECASE,
)
EA_MOVIE_RE = re.compile(
    r"/(\d+)/[^/]*?streaming-porn-videos\.html",
    re.IGNORECASE,
)

# Extract player init params from HTML — handles both item/item_id and scene/scene_id
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
_ITEM_ID_RE = re.compile(r"(?:item_id|item):\s*(\d+)")
_SCENE_ID_RE = re.compile(r"(?:scene_id|scene):\s*(\d+)")
_TYPE_RE = re.compile(r"type:\s*['\"]([^'\"]+)['\"]")
_SITE_RE = re.compile(r"site:\s*['\"]([^'\"]+)['\"]")
_KEY_RE = re.compile(r"key:\s*['\"]([^'\"]+)['\"]")
_TIMESTAMP_RE = re.compile(r"timestamp:\s*['\"]([^'\"]+)['\"]")
_SIG_RE = re.compile(r"sig:\s*['\"]([^'\"]+)['\"]")

# Trailer / preview pattern
ADE_TRAILER_RE = re.compile(
    r"preview\.adultempire\.com|trailer\.adultempire\.com",
    re.IGNORECASE,
)


def parse_ade_cookies(cookie_str: str) -> dict[str, str]:
    """Parse Netscape cookie file format or semicolon-separated cookies into a dict."""
    cookies: dict[str, str] = {}
    if not cookie_str:
        return cookies

    for line in cookie_str.strip().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # Try tab-separated first (real Netscape format)
        parts = line.split("\t")
        if len(parts) >= 7:
            name = parts[5]
            value = parts[6]
            cookies[name] = value
            continue
        # Try 2+ spaces (Discord/chat may convert tabs to spaces)
        parts = re.split(r"\s{2,}", line)
        if len(parts) >= 7:
            name = parts[5]
            value = parts[6]
            cookies[name] = value
            continue
        # Fallback: key=value format
        if "=" in line:
            for pair in line.split(";"):
                pair = pair.strip()
                if "=" in pair:
                    k, v = pair.split("=", 1)
                    cookies[k.strip()] = v.strip()

    return cookies


def _get_session(cookies_str: str | None = None) -> CustomSession:
    """Create a session with ADE cookies."""
    session = CustomSession(impersonate="chrome")
    session.timeout = 30
    session.headers["User-Agent"] = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
    )

    # Always set age verification cookies
    for domain in (".adultdvdempire.com", ".adultempire.com", ".elegantangel.com"):
        session.cookies.set("ageGated", "true", domain=domain, path="/", secure=True)
        session.cookies.set("ageConfirmationClicked", "true", domain=domain, path="/", secure=True)
        session.cookies.set("ageConfirmed", "true", domain=domain, path="/", secure=True)

    # Resolve cookies: explicit > ADE_COOKIES env > ADE_COOKIES_URL
    if not cookies_str:
        cookies_str = os.getenv("ADE_COOKIES", "")
    if not cookies_str:
        cookies_url = os.getenv("ADE_COOKIES_URL", "")
        if cookies_url:
            try:
                from curl_cffi.requests import Session as CurlSession
                resp = CurlSession(impersonate="chrome").get(cookies_url, timeout=10)
                if "etoken" in resp.text:
                    cookies_str = resp.text
            except Exception:
                pass

    # Load user-provided cookies (etoken, etc.)
    if cookies_str:
        user_cookies = parse_ade_cookies(cookies_str)
        for name, value in user_cookies.items():
            for domain in (".adultdvdempire.com", ".adultempire.com", ".elegantangel.com"):
                session.cookies.set(name, value, domain=domain, path="/")

    return session


def extract_ade_url(text: str) -> str | None:
    """Extract an ADE URL from text."""
    m = ADE_URL_RE.search(text)
    return m.group(0).rstrip(")") if m else None


def _extract_player_params(html: str) -> dict[str, str] | None:
    """Extract AEVideoPlayer init params from HTML."""
    # Try the combined regex first
    m = _PLAYER_INIT_RE.search(html)
    if m:
        # also try to get scene/type from nearby
        scene_m = _SCENE_ID_RE.search(html, m.start(), m.end() + 500)
        type_m = _TYPE_RE.search(html, m.start(), m.end() + 500)
        return {
            "item_id": m.group(1),
            "scene_id": scene_m.group(1) if scene_m else "",
            "type": type_m.group(1) if type_m else "",
            "site": m.group(2),
            "key": m.group(3),
            "timestamp": m.group(4),
            "sig": m.group(5),
        }

    # Fallback: extract individually
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


def _get_playlist_url_from_verify(
    session: CustomSession,
    item_id: str,
    key: str,
    timestamp: str,
    sig: str,
    site: str = ADE_SITE_API_KEY,
    stream_type: str = "VOD",
    scene_id: str | None = None,
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
        # Fallback: check master m3u8 playlist URL pattern /hls/.../{start_seconds}/{duration_seconds}/...
        if playlist_url:
            m = re.search(r"/hls/\d+/\d+/\d+/(\d+)/", playlist_url)
            if m:
                return int(m.group(1))

    # 2. Check last scene end_seconds for full movie
    scenes = item_detail.get("scenes", [])
    if scenes and scenes[-1].get("end_seconds", 0) > 0:
        return int(scenes[-1]["end_seconds"])

    # 3. Fallback to item_detail length
    raw_len = item_detail.get("length")
    if raw_len is not None:
        if isinstance(raw_len, (int, float)) and raw_len > 0:
            # In ADE API, numeric length is in minutes
            return int(raw_len * 60)
        if isinstance(raw_len, str) and raw_len.strip():
            raw_str = raw_len.strip()
            if ":" in raw_str:
                parts = raw_str.split(":")
                try:
                    if len(parts) == 3:
                        return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
                    if len(parts) == 2:
                        return int(parts[0]) * 60 + int(parts[1])
                except ValueError:
                    pass
            else:
                hr_m = re.search(r"(\d+)\s*hr", raw_str, re.I)
                min_m = re.search(r"(\d+)\s*min", raw_str, re.I)
                if hr_m or min_m:
                    h = int(hr_m.group(1)) if hr_m else 0
                    m = int(min_m.group(1)) if min_m else 0
                    return h * 3600 + m * 60
                if raw_str.isdigit():
                    return int(raw_str) * 60

    return 0


def resolve_ade_title(
    base_title: str,
    item_detail: dict[str, Any],
    scene_id: str | int | None = None,
) -> str:
    """Append scene title if this is a scene/clip page and scene title isn't already included."""
    base_title = html_unescape(base_title or "").strip()
    if not scene_id:
        return base_title
    for sc in item_detail.get("scenes", []):
        if str(sc.get("id")) == str(scene_id):
            sc_title = html_unescape(sc.get("title", "")).strip()
            if sc_title and sc_title.lower() not in base_title.lower():
                return f"{base_title} — {sc_title}"
            break
    return base_title


def get_ade_manifest(url: str, cookies_str: str | None = None) -> dict[str, Any]:
    """
    Get the streaming manifest URL for an AdultDVDEmpire / Elegant Angel video
    (same Empire/digiflix backend).

    Args:
        url: Full ADE or Elegant Angel URL (movie or clip/scene page)
        cookies_str: Netscape cookie file contents or semicolon-separated cookies
                     Must include 'etoken' for VOD content.

    Returns:
        dict with keys: title, item_id, playlist_url, streams, is_authorized, etc.
    """
    if not cookies_str:
        cookies_str = os.getenv("ADE_COOKIES", "")

    session = _get_session(cookies_str)

    # Determine the page type (check scene patterns before the broad movie pattern)
    clip_match = ADE_CLIP_RE.search(url)
    ea_scene_match = EA_SCENE_RE.search(url)
    ea_movie_match = EA_MOVIE_RE.search(url)
    movie_match = ADE_MOVIE_RE.search(url)

    scene_id = None
    vod_item_id = None
    if clip_match:
        scene_id = clip_match.group(1)
    elif ea_scene_match:
        scene_id = ea_scene_match.group(1)
    elif movie_match:
        vod_item_id = movie_match.group(1)

    # Clip / scene pages: extract player directly (contains item + scene + type=scene)
    # Covers ADE /clip/... pages and Elegant Angel ...-streaming-scene-video.html pages
    if clip_match or ea_scene_match:
        logger.info("Fetching clip page: %s", url)
        resp = session.get(url)
        resp.raise_for_status()
        html = resp.text
        params = _extract_player_params(html)
        if params and params.get("key") and params.get("sig"):
            logger.info(
                "Clip player params: item=%s scene=%s type=%s site=%s key=%s...",
                params["item_id"], params.get("scene_id"), params.get("type"), params["site"], params["key"][:10],
            )
            # clip VOD uses type=scene
            stream_type = params.get("type") or "scene"
            # normalize: previewscene -> scene for verify? verify expects scene
            if stream_type.lower() == "previewscene":
                stream_type = "scene"
            result = _get_playlist_url_from_verify(
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
                }
        # fallback to preview logic
        return _get_clip_preview(session, scene_id, url, html)

    # Elegant Angel movie pages (...-streaming-porn-videos.html):
    # player params are embedded directly in the page (no viewpart URL like ADE).
    if ea_movie_match and not ea_scene_match:
        logger.info("Fetching Elegant Angel movie page: %s", url)
        resp = session.get(url)
        resp.raise_for_status()
        html = resp.text
        params = _extract_player_params(html)
        if not params:
            raise ValueError(
                "Could not extract player parameters from the page. "
                "Ensure cookies contain a valid login session (etoken)."
            )
        logger.info(
            "EA movie player params: item_id=%s, site=%s, key=%s...",
            params["item_id"], params["site"], params["key"][:10],
        )
        result = _get_playlist_url_from_verify(
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
            raise ValueError(
                "Not authorized to stream this content. "
                "Check your cookies - etoken may be expired."
            )
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
        }

    # Movie/VOD pages: get full VOD stream
    # Build the viewpart=videoplayer URL to get the player init params
    base_url = url.rstrip("/")
    if "?" in base_url:
        player_url = base_url + "&viewpart=videoplayer&stream_type=0&tc="
    else:
        player_url = base_url + "?viewpart=videoplayer&stream_type=0&tc="

    logger.info("Fetching player page: %s", player_url)
    resp = session.get(player_url)
    resp.raise_for_status()
    html = resp.text

    # Extract player params
    params = _extract_player_params(html)
    if not params:
        raise ValueError(
            "Could not extract player parameters from the page. "
            "Ensure ADE_COOKIES contains valid login cookies (etoken)."
        )

    logger.info(
        "Player params: item_id=%s, site=%s, key=%s...",
        params["item_id"], params["site"], params["key"][:10],
    )

    # Call verify endpoint
    stream_type = params.get("type") or "VOD"
    result = _get_playlist_url_from_verify(
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
        raise ValueError(
            "Not authorized to stream this content. "
            "Check your ADE_COOKIES - etoken may be expired."
        )

    # Extract title and duration
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
    }


def _get_clip_preview(session: CustomSession, scene_id: str, url: str, html: str | None = None) -> dict[str, Any]:
    """Fallback: preview trailer for clip when VOD not authorized."""
    if html is None:
        resp = session.get(url)
        resp.raise_for_status()
        html = resp.text

    # Find parent movie VOD item ID from data-movie-id attributes
    movie_ids = re.findall(r'data-movie-id="(\d+)"', html)
    if not movie_ids:
        raise ValueError("Could not find movie ID on clip page")

    # Use the first data-movie-id (parent movie)
    vod_item_id = movie_ids[0]

    # Try to get player params from the parent movie's VOD page
    # First get the movie slug from the clip page
    movie_slug_match = re.search(r'href="/(\d+)/([^"]+?)-porn-videos\.html"', html)
    if movie_slug_match:
        parent_vod_id = movie_slug_match.group(1)
        parent_slug = movie_slug_match.group(2)
        vod_url = f"https://www.adultdvdempire.com/{parent_vod_id}/{parent_slug}-porn-videos.html"

        # Try to get player params from the VOD page
        vod_resp = session.get(vod_url + "?viewpart=videoplayer&stream_type=0&tc=")
        if vod_resp.ok:
            params = _extract_player_params(vod_resp.text)
            if params and params.get("key"):
                result = _get_playlist_url_from_verify(
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
                    }

    # Fallback: use preview
    result = _get_playlist_url_from_verify(
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
    }


def get_ade_preview_manifest(url: str) -> dict[str, Any]:
    """
    Get the free preview/trailer manifest URL for an ADE video.
    Works without login cookies.
    """
    session = _get_session()

    # Extract item_id from URL
    clip_match = ADE_CLIP_RE.search(url)
    movie_match = ADE_MOVIE_RE.search(url)

    item_id = None
    if clip_match:
        item_id = clip_match.group(1)
    elif movie_match:
        # For movie pages, we need the VOD item ID
        # Fetch the page to find it
        resp = session.get(url)
        resp.raise_for_status()
        item_ids = _ITEM_ID_RE.findall(resp.text)
        if item_ids:
            # Filter out the generic aeplayer.js item_id, take the one from the player init
            item_id = item_ids[-1]  # Usually the player-specific one

    if not item_id:
        raise ValueError("Could not extract item_id from URL")

    # Call verify with preview type
    result = _get_playlist_url_from_verify(
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
