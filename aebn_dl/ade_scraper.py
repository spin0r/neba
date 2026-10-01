from __future__ import annotations

from html import unescape as html_unescape
import json
import logging
import os
import re
from typing import Any
from urllib.parse import urlparse

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

# Scene screenshot thumbs: https://caps1cdn.adultempire.com/n/0399/10/5090399_06670_10.jpg
# Full size:                            .../n/0399/1280/5090399_06670_1280c.jpg
_EA_THUMB_RE = re.compile(
    r"https://caps\d?cdn\.adultempire\.com/n/(\d+)/(10|320)/(\d+)_(\d+)_(?:10|320)\.jpg",
    re.IGNORECASE,
)

# Broad fallback: any caps CDN still (ADE movie pages use other widths/prefixes,
# e.g. /m/ galleries or 640/768 thumbs). We normalize everything to 1280c/3840.
_ANY_CAPS_RE = re.compile(
    r"https://caps\d?cdn\.adultempire\.com/([a-z])/(\d+)/(\d+)/(\d+)_(\d+)_\d+[a-z]?\.jpg",
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


def _page_title(html: str) -> str:
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
    return re.sub(r"\s+", " ", html_unescape(m.group(1))).strip()[:90] if m else ""


def _no_player_cause(html: str, final_url: str) -> str:
    """Explain *why* a fetched page carried no player init params."""
    low = html.lower()

    if "aevideoplayer" in low:
        return "the page does contain a video player, but its parameters could not be parsed"
    if any(m in low for m in (
        "cf-browser-verification", "challenge-platform", "cf-chl", "turnstile",
        "just a moment", "checking your browser", "enable javascript and cookies",
    )):
        return "the site answered with a bot-check challenge page"

    # Sessions without a valid etoken get bounced to the site root (HTTP 200).
    u = urlparse(final_url)
    if u.netloc and not u.path.strip("/"):
        return "the site bounced the request back to its homepage — the login session (etoken) is missing or expired"
    if any(m in low for m in ("member login", "forgot password", "sign in to", "account/login")):
        return "the site redirected to a login page — the session cookies are missing or expired"
    if any(m in low for m in ("are you 18", "age verification", "agegate", "verify your age")):
        return "the site is asking for age verification — the cookies are missing"

    title = _page_title(html)
    return f"the page came back with no video player (page title: '{title}')" if title \
        else "the page came back empty, with no video player"


def _cookie_hint(cookies_str: str | None, site: str, box: str) -> str:
    if not cookies_str:
        return f"no cookies were supplied — paste your {site} session in the Cookies page, box '{box}'"
    if not re.search(r"\betoken\b", cookies_str):
        return f"the cookies in use contain no etoken — paste a fresh {site} session in the Cookies page, box '{box}'"
    return f"the session was refused, so the etoken is likely expired — refresh your {site} session in the Cookies page, box '{box}'"


def _upper_first(s: str) -> str:
    return s[0].upper() + s[1:] if s else s


def _site_for_url(url: str) -> tuple[str, str]:
    host = urlparse(url or "").netloc.lower()
    return ("Elegant Angel", "ea") if "elegantangel" in host else ("AdultDVDEmpire", "ade")


def _auth_error(cookies_str: str | None, final_url: str = "") -> ValueError:
    site, box = _site_for_url(final_url)
    logger.warning("Not authorized for %s (final_url=%s, cookies=%d bytes)",
                   site, final_url or "?", len(cookies_str or ""))
    return ValueError(f"{site}: not authorized to stream this content. {_upper_first(_cookie_hint(cookies_str, site, box))}.")


def _no_player_error(html: str, final_url: str, cookies_str: str | None,
                     site: str, box: str) -> ValueError:
    """Build an actionable error for a page without player params."""
    cause = _no_player_cause(html, final_url)
    logger.warning(
        "No player params: %s | final_url=%s | bytes=%d | title=%r",
        cause, final_url, len(html or ""), _page_title(html or ""),
    )
    return ValueError(f"{site}: {cause}. {_upper_first(_cookie_hint(cookies_str, site, box))}.")


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


def resolve_ade_title(    base_title: str,
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


def _extract_ea_screenshots(html: str, master: str | int | None = None) -> list[dict[str, str]]:
    """Extract caps stills, optionally filtered to one master id.

    Unfiltered clip pages also carry related-title thumbs (other masters) —
    pass the verify ``master_id`` to keep only the scene's own stills.
    """
    want = str(master) if master not in (None, "") else ""
    seen: set[tuple[str, ...]] = set()
    shots: list[dict[str, str]] = []
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


def _merge_shots(*lists: list[dict[str, str]] | None) -> list[dict[str, str]]:
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


def _dedupe_groups(groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop cross-group duplicate stills (by full URL), keeping first occurrence.

    Covers preview-8 vs More-Screenshots full sets, 320 vs 3840 variants
    (already normalized), and synth overview vs per-scene synth.
    """
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


def _extract_more_screens_params(html: str) -> list[dict[str, int]]:
    """Parse ShowMoreScreens2017(item, start, end, sceneID, ...) call params.

    The movie page only embeds ~8 preview stills per scene; the full set
    (70-100 per scene on Mon Amour) loads via More Screenshots buttons through
    GET /Item/LoadSceneScreenshots?item=&start=&end=&sceneID=.
    """
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


def _fetch_full_scene_shots(session: CustomSession, base_host: str,
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
                shots = _extract_ea_screenshots(r.text)
                if shots:
                    out[str(p["scene"])] = shots
                    logger.info("Full stills scene %s: %d", p["scene"], len(shots))
        except Exception as e:
            logger.warning("LoadSceneScreenshots failed scene %s: %s", p["scene"], e)
    return out


def _extract_movie_page_blocks(html: str) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    """Split an ADE movie page into full-list stills + per-scene blocks.

    Movie pages (e.g. /4997491/mon-amour-...-porn-videos.html) render
    ``<a name=\"scene_<clipId>\">`` anchors, one block per scene, each with
    its own stills and an ``/clip/<id>/<slug>-streaming-scene.html`` title
    link. The top chunk (before the first anchor) is the full-movie list —
    on Mon Amour that's 1 still vs 8 per scene, i.e. scenes carry more
    screenshots than the full list.
    Returns (full_shots, [{clip_id, title, shots}]).
    """
    parts = re.split(r'<a name="scene_(\d+)"', html or "")
    full_shots = _extract_ea_screenshots(parts[0]) if parts else []
    blocks: list[dict[str, Any]] = []
    for i in range(1, len(parts), 2):
        clip_id = parts[i]
        block = parts[i + 1] if i + 1 < len(parts) else ""
        title_m = re.search(
            r"/clip/" + re.escape(clip_id) + r"/[^\"]*?\"[^>]*>(.*?)</a>",
            block, re.S | re.I,
        )
        title = re.sub(r"\s+", " ", html_unescape(title_m.group(1)) if title_m else "").strip()
        blocks.append({
            "clip_id": clip_id,
            "title": title or f"Scene {len(blocks) + 1}",
            "shots": _extract_ea_screenshots(block),
        })
    return full_shots, blocks


def _build_groups_from_page_blocks(
    item_detail: dict[str, Any],
    full_shots: list[dict[str, str]],
    blocks: list[dict[str, Any]],
    combined_limit: int = 40,
) -> list[dict[str, Any]] | None:
    """Build screenshot groups from real movie-page scene blocks.

    Returns None when the page has no scene blocks (caller falls back to
    offset bucketing / synth). Verify scene boundaries are attached by order
    (block n ↔ verify scene n) so the UI can show time ranges.
    """
    if not blocks:
        return None
    scenes = _scenes_info(item_detail)
    total_end = max((s["end_s"] for s in scenes), default=0)
    combined = list(full_shots) or _synth_screenshots(item_detail, None, limit=combined_limit)
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


def _synth_screenshots(item_detail: dict[str, Any], scene_id: str | int | None = None, limit: int = 40) -> list[dict[str, str]]:
    """Synthesize screenshot URLs from verify data (works for any ADE/EA title).

    Uses master_id + frames interval + scene boundaries to build caps CDN URLs.
    """
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


def _scenes_info(item_detail: dict[str, Any]) -> list[dict[str, Any]]:
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


def _shot_offset_seconds(shot: dict[str, str]) -> int | None:
    """Parse the frame offset (seconds) out of a caps CDN URL."""
    m = re.search(r"_(\d{4,6})_(?:10|320|1280c|3840)\.jpg", (shot.get("full") or "") + " " + (shot.get("thumb") or ""))
    if not m:
        m = re.search(r"_(\d+)_", shot.get("full") or shot.get("thumb") or "")
    try:
        return int(m.group(1)) if m else None
    except (TypeError, ValueError):
        return None


def _caps_probe_info(shots: list[dict[str, str]], start: int = 0,
                     end: int | None = None, step: int = 10) -> dict[str, Any] | None:
    """Describe the full caps range behind a movie (for the UI opt-in toggle).

    Parses prefix/gallery/master from the first real still and spans
    start..end at step 10 — the same range ``check_caps_limit.py`` probes
    (Mon Amour: 0..9203 → 921 stills). The frontend generates the URLs only
    when the toggle is switched on (default off), so no extra traffic.
    """
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
        offs = [o for o in (_shot_offset_seconds(s) for s in shots) if o is not None]
        end = max(offs) if offs else 0
    if end <= start:
        return None
    return {"prefix": prefix, "gallery": gallery, "master": master,
            "start": start, "end": end, "step": step,
            "count": (end - start) // step + 1}


def _build_screenshot_groups(
    item_detail: dict[str, Any],
    html_shots: list[dict[str, str]] | None = None,
    per_scene_limit: int = 30,
    combined_limit: int = 40,
) -> list[dict[str, Any]]:
    """Group screenshots per scene + a combined (full-movie) group.

    Movie pages (e.g. /4997491/mon-amour-...-porn-videos.html) list one
    combined player on top plus one entry per scene. The flat `screenshots`
    list mixes them, so the UI needs explicit groups:
    ``all`` (combined) first, then Scene 1..N with title + boundaries.
    """
    scenes = _scenes_info(item_detail)
    if not scenes:
        return []
    html_shots = html_shots or []

    # Bucket HTML thumbs by scene boundaries (offset seconds within [start, end]).
    buckets: dict[str, list[dict[str, str]]] = {s["id"]: [] for s in scenes if s["id"]}
    leftover: list[dict[str, str]] = []
    for shot in html_shots:
        off = _shot_offset_seconds(shot)
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
    # Combined group first (the top player on movie pages).
    # NOTE: when the page carries real stills, those belong to the individual
    # scenes (bucketed below). The combined entry is a synth overview so the
    # scene counts add up to the site's total (e.g. 4x30=120) instead of
    # showing every still twice.
    total_end = max((s["end_s"] for s in scenes), default=0)
    combined = _synth_screenshots(item_detail, None, limit=combined_limit)
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
        # Fall back to synthesized caps URLs when the page carries no
        # stills for this scene (ADE movie pages usually don't).
        shots = bucketed if bucketed else _synth_screenshots(item_detail, sid, limit=per_scene_limit)
        # Any unbucketable thumbs belong to the combined cut — already shown.
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
        if not params or not params.get("key") or not params.get("sig"):
            site, box = _site_for_url(resp.url)
            raise _no_player_error(html, resp.url, cookies_str, site, box)
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
            master_id = str(item_detail.get("master_id") or "")
            real_shots = _extract_ea_screenshots(html, master_id or None)
            flat_shots = real_shots or _extract_ea_screenshots(html) or _synth_screenshots(item_detail, cur_scene_id)
            scene_groups = _build_screenshot_groups(item_detail, _extract_ea_screenshots(html) or None)
            caps_probe = None
            # Parent-movie flow: the clip page's own stills mix in related
            # titles, so resolve the parent movie page (clip → movie link),
            # find this exact scene block (preview stills) plus its More
            # Screenshots full set.
            try:
                pm = re.search(r'href="(/(\d+)/([^"]+?)-porn-videos\.html)"', html or "")
                if pm and cur_scene_id:
                    u = urlparse(url)
                    movie_url = f"{u.scheme or 'https'}://{u.netloc or 'www.adultdvdempire.com'}{pm.group(1)}"
                    logger.info("Clip parent movie page: %s", movie_url)
                    mresp = session.get(movie_url, timeout=20)
                    if mresp.ok and mresp.text:
                        _mfull, mblocks = _extract_movie_page_blocks(mresp.text)
                        blk = next((b for b in mblocks
                                    if str(b.get("clip_id")) == str(cur_scene_id)), None)
                        if blk and (blk.get("shots") or _extract_more_screens_params(mresp.text)):
                            more2 = [p for p in _extract_more_screens_params(mresp.text)
                                     if str(p["scene"]) == str(cur_scene_id)]
                            if more2:
                                mu = urlparse(movie_url)
                                mhost = f"{mu.scheme or 'https'}://{mu.netloc}"
                                fmap = _fetch_full_scene_shots(session, mhost, more2)
                                if str(cur_scene_id) in fmap:
                                    blk["shots"] = _merge_shots(fmap[str(cur_scene_id)],
                                                                blk.get("shots"))
                            scene_shots = _merge_shots(blk.get("shots"))
                            if scene_shots:
                                flat_shots = _merge_shots(scene_shots, flat_shots)
                                infos = _scenes_info(item_detail)
                                info = next((s for s in infos
                                             if s.get("id") == str(cur_scene_id)), {})
                                if more2:
                                    caps_probe = _caps_probe_info(
                                        scene_shots, start=more2[0]["start"],
                                        end=more2[0]["end"], step=10)
                                scene_groups = _dedupe_groups([{
                                    "key": f"scene-{info.get('n') or 1}",
                                    "scene_id": str(cur_scene_id),
                                    "n": info.get("n") or 1,
                                    "title": blk.get("title") or info.get("title")
                                             or scene_title or f"Scene {cur_scene_id}",
                                    "start_s": info.get("start_s"),
                                    "end_s": info.get("end_s"),
                                    "screenshots": scene_shots,
                                }])
                                logger.info("Parent-movie exact scene %s: %d stills",
                                            cur_scene_id, len(scene_shots))
            except Exception as e:
                logger.warning("Parent-movie scene stills failed: %s", e)
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
                "scenes": _scenes_info(item_detail),
            }
        # Not authorized for the VOD — the free preview may still be available.
        # If that fails too, explain the authorization problem instead of a
        # cryptic "could not find movie ID".
        try:
            return _get_clip_preview(session, scene_id, url, html)
        except Exception as preview_err:
            logger.warning("Preview fallback failed: %s", preview_err)
            raise _auth_error(cookies_str, url) from preview_err

    # Elegant Angel movie pages (...-streaming-porn-videos.html):
    # player params are embedded directly in the page (no viewpart URL like ADE).
    if ea_movie_match and not ea_scene_match:
        logger.info("Fetching Elegant Angel movie page: %s", url)
        resp = session.get(url)
        resp.raise_for_status()
        html = resp.text
        params = _extract_player_params(html)
        if not params:
            raise _no_player_error(html, resp.url, cookies_str, "Elegant Angel", "ea")
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
            raise _auth_error(cookies_str, resp.url)
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
            "screenshots": _synth_screenshots(item_detail, None),
            "screenshot_groups": _build_screenshot_groups(item_detail, None),
            "scenes": _scenes_info(item_detail),
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
        # Some pages (Elegant Angel, certain ADE layouts) only embed the player
        # in the document itself — retry the plain URL before giving up.
        logger.info("No player params in viewpart page (%d bytes), retrying plain page", len(html))
        try:
            plain = session.get(url)
            plain.raise_for_status()
            plain_params = _extract_player_params(plain.text)
            if plain_params:
                params, resp, html = plain_params, plain, plain.text
                logger.info("Plain page had the player params — using them")
        except Exception as e:
            logger.warning("Plain-page retry failed: %s", e)

    if not params:
        site, box = _site_for_url(resp.url)
        raise _no_player_error(html, resp.url, cookies_str, site, box)

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
        raise _auth_error(cookies_str, resp.url)

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

    # Screenshots: the viewpart page (player) rarely carries stills — the real
    # scene thumbs live on the normal movie page. Fetch it best-effort and
    # merge, so we show the site's actual stills instead of only synth guesses.
    # The movie page itself splits stills per scene (<a name="scene_<id>">
    # blocks, 8 each on Mon Amour vs 1 on the full list), so prefer those
    # exact blocks over offset bucketing.
    ea_shots = _extract_ea_screenshots(html)
    page_full: list[dict[str, str]] = []
    page_blocks: list[dict[str, Any]] = []
    more_params: list[dict[str, int]] = []
    try:
        plain_resp = session.get(url, timeout=20)
        if plain_resp.ok and plain_resp.text and plain_resp.text != html:
            ea_shots = _merge_shots(ea_shots, _extract_ea_screenshots(plain_resp.text))
            page_full, page_blocks = _extract_movie_page_blocks(plain_resp.text)
            ea_shots = _merge_shots(ea_shots, page_full,
                                    *[b.get("shots") or [] for b in page_blocks])
            # More Screenshots buttons: each scene block previews ~8 stills,
            # the full set (70-100/scene) loads via /Item/LoadSceneScreenshots.
            more_params = _extract_more_screens_params(plain_resp.text)
            if more_params and page_blocks:
                u = urlparse(url)
                host = f"{u.scheme or 'https'}://{u.netloc or 'www.adultdvdempire.com'}"
                full_map = _fetch_full_scene_shots(session, host, more_params)
                if full_map:
                    by_clip = {str(b.get("clip_id")): b for b in page_blocks}
                    for sid, shots in full_map.items():
                        if sid in by_clip:
                            by_clip[sid]["shots"] = _merge_shots(shots, by_clip[sid].get("shots"))
                        else:
                            page_blocks.append({"clip_id": sid, "title": f"Scene {sid}", "shots": shots})
                    ea_shots = _merge_shots(ea_shots, *[s for s in full_map.values()])
    except Exception as e:
        logger.warning("Plain-page stills fetch failed: %s", e)
    logger.info("Stills: viewpart+page=%d real, scenes=%d, page-blocks=%d", len(ea_shots), len(item_detail.get("scenes", []) or []), len(page_blocks))
    flat_shots = _merge_shots(ea_shots, page_full, *[b.get("shots") or [] for b in page_blocks]) or _synth_screenshots(item_detail, scene_id)
    probe_end = max([p["end"] for p in more_params], default=0) or None
    caps_probe = _caps_probe_info(ea_shots, start=0, end=probe_end, step=10)
    groups = _dedupe_groups(
        _build_groups_from_page_blocks(item_detail, page_full, page_blocks)
        or _build_screenshot_groups(item_detail, ea_shots or None)
        or []
    )
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
        "scenes": _scenes_info(item_detail),
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
