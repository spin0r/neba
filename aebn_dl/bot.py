from __future__ import annotations

import asyncio
import hashlib
from html import unescape as html_unescape
import json
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from telegram import Bot, CopyTextButton, InlineKeyboardButton, InlineKeyboardMarkup, Message, Update
from telegram.constants import ParseMode
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

try:
    from .downloader import Downloader
except ImportError:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from aebn_dl.downloader import Downloader  # type: ignore[no-redef]

try:
    from dotenv import load_dotenv
    load_dotenv()
    load_dotenv(dotenv_path=Path(__file__).with_name(".env"), override=False)
    load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env", override=False)
except ImportError:
    pass

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
OUTPUT_DIR = os.getenv("AEBN_OUTPUT_DIR", os.path.join(os.getcwd(), "output_dir"))
WORK_DIR = os.getenv("AEBN_WORK_DIR", os.path.join(os.getcwd(), "work_dir"))
DEFAULT_PROXY = os.getenv("AEBN_PROXY", "")
DEFAULT_THREADS = int(os.getenv("AEBN_THREADS", "5"))
ALLOWED_USER_IDS = {int(x.strip()) for x in os.getenv("ALLOWED_USER_IDS", "").split(",") if x.strip().isdigit()}
MAX_CONCURRENT_DOWNLOADS = int(os.getenv("MAX_CONCURRENT_DOWNLOADS", "2"))
MAX_TELEGRAM_FILESIZE = int(os.getenv("MAX_TELEGRAM_FILESIZE_MB", "50")) * 1024 * 1024
ADE_COOKIES_URL = os.getenv("ADE_COOKIES_URL", "")

AEBN_URL_RE = re.compile(r"https?://[^\s]*aebn\.com[^\s]*|https?://m\.aebn\.net[^\s]*", re.IGNORECASE)
ADE_URL_RE = re.compile(r"https?://(?:www\.)?(?:adultdvdempire|adultempire|elegantangel)\.com/\S+", re.IGNORECASE)

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s|%(levelname)s|%(message)s", datefmt="%H:%M:%S")

download_semaphore = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)
executor = ThreadPoolExecutor(max_workers=MAX_CONCURRENT_DOWNLOADS * 2)

# ---------------------------------------------------------------------------
# URL store: maps short keys (≤64 bytes) to full URLs
# ---------------------------------------------------------------------------
_url_store: dict[str, str] = {}
_user_ade_cookies: dict[int, str] = {}
_awaiting_cookies: set[int] = set()
_COOKIES_FILE = Path(__file__).with_name("ade_cookies.json")


def _load_cookies() -> None:
    """Load saved cookies from disk and optionally from URL."""
    # Load from file
    if _COOKIES_FILE.exists():
        try:
            data = json.loads(_COOKIES_FILE.read_text())
            _user_ade_cookies.update({int(k): v for k, v in data.items()})
            logger.info("Loaded ADE cookies for %d users", len(_user_ade_cookies))
        except Exception as e:
            logger.warning("Failed to load cookies: %s", e)

    # Fetch from URL if configured (used as global default)
    if ADE_COOKIES_URL:
        try:
            try:
                from curl_cffi.requests import Session as CurlSession
                resp = CurlSession(impersonate="chrome").get(ADE_COOKIES_URL, timeout=10)
                cookie_text = resp.text.strip()
            except ImportError:
                import urllib.request
                req = urllib.request.Request(ADE_COOKIES_URL, headers={"User-Agent": "Mozilla/5.0"})
                resp = urllib.request.urlopen(req, timeout=10)
                cookie_text = resp.read().decode("utf-8").strip()
            if "etoken" in cookie_text:
                _user_ade_cookies[0] = cookie_text
                _save_cookies()
                logger.info("Fetched ADE cookies from URL")
            else:
                logger.warning("ADE_COOKIES_URL returned no etoken")
        except Exception as e:
            logger.warning("Failed to fetch ADE cookies from URL: %s", e)


def _save_cookies() -> None:
    """Persist cookies to disk."""
    try:
        _COOKIES_FILE.write_text(json.dumps({str(k): v for k, v in _user_ade_cookies.items()}, indent=2))
    except Exception as e:
        logger.warning("Failed to save cookies: %s", e)


def _store_url(url: str) -> str:
    key = hashlib.md5(url.encode()).hexdigest()[:10]
    _url_store[key] = url
    return key


def _get_url(key: str) -> str | None:
    return _url_store.get(key)


HELP_RICH_TEXT = (
    "<h3>📖 AEBN / ADE / EA Manifest Bot Guide</h3>\n\n"
    "<table bordered compact>\n"
    "  <tr><th>Command</th><th>Usage & Details</th></tr>\n"
    "  <tr><td><code>/m3u8 &lt;url&gt;</code></td><td>Extract DASH/m3u8 playback manifests</td></tr>\n"
    "  <tr><td><code>/info &lt;url&gt;</code></td><td>Inspect movie info, cast & scenes</td></tr>\n"
    "  <tr><td><code>/cookies</code></td><td>Manage AdultDVDEmpire login session</td></tr>\n"
    "  <tr><td><code>/help</code></td><td>Show this comprehensive guide</td></tr>\n"
    "</table><br/>\n"
    "<blockquote expandable>\n"
    "  💡 <b>Features & Tips:</b><br/>\n"
    "  • <b>Direct Link Detection:</b> Simply send any AEBN or ADE movie link directly without typing commands.<br/>\n"
    "  • <b>Variant Resolution Ranking:</b> For ADE movies, master playlists are inspected to provide 4K, 1080p, and 720p direct links.<br/>\n"
    "  • <b>One-Tap Clipboard Copy:</b> Tap any monospace URL to copy it immediately.<br/>\n"
    "  • <b>Timezone-Aware Timers:</b> Token expirations render in your local device time with live relative timers.<br/>\n"
    "  • <b>Session Persistence:</b> Saved ADE cookies persist across bot restarts.\n"
    "</blockquote>"
)

HELP_TEXT = HELP_RICH_TEXT


# ---------------------------------------------------------------------------
# Helpers & Rich Formatting Utilities
# ---------------------------------------------------------------------------
def is_allowed(user_id: int) -> bool:
    return not ALLOWED_USER_IDS or user_id in ALLOWED_USER_IDS


def extract_url(text: str) -> str | None:
    if not text:
        return None
    # Try ADE first (more specific)
    m = ADE_URL_RE.search(text)
    if m:
        return m.group(0).strip()
    m = AEBN_URL_RE.search(text)
    return m.group(0).strip() if m else None


def is_ade_url(url: str) -> bool:
    return bool(ADE_URL_RE.search(url))


def site_label_for(url: str) -> str:
    if "elegantangel.com" in url.lower():
        return "EA"
    return "ADE" if is_ade_url(url) else "AEBN"


def cb(action: str, url: str) -> str:
    """Build callback_data under 64 bytes: 'action|<10-char-md5>'"""
    return f"{action}|{_store_url(url)}"


def resolve_cb(data: str) -> tuple[str, str | None]:
    """Parse 'action|key' → (action, url_or_None)"""
    if "|" not in data:
        return data, None
    action, key = data.split("|", 1)
    return action, _get_url(key)


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if abs(n) < 1024:
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


def _get_expiry_ts(url: str) -> int | None:
    """Extract unix timestamp from url e= param if present."""
    m = re.search(r"[?&]e=(\d+)", url)
    return int(m.group(1)) if m else None


def _format_expiry_display(ts: int) -> tuple[str, str]:
    """Return (localized_ist_str, relative_str) for a unix timestamp."""
    try:
        import datetime
        utc = datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc)
        ist = utc.astimezone(datetime.timezone(datetime.timedelta(hours=5, minutes=30)))
        now = datetime.datetime.now(tz=datetime.timezone.utc)
        delta = ts - int(now.timestamp())
        ist_str = ist.strftime("%d-%m-%Y %I:%M %p IST")
        if delta <= 0:
            return f"expired at {ist_str}", "expired"
        days = delta // 86400
        h = (delta % 86400) // 3600
        mnt = (delta % 3600) // 60
        if days > 0:
            rel = f"in {days}d {h}h"
        elif h > 0:
            rel = f"in {h}h {mnt}m"
        else:
            rel = f"in {mnt}m"
        return ist_str, rel
    except Exception:
        return "", ""


def _expiry_ist(url: str) -> str | None:
    """Parse e= from URL and return IST expiry string."""
    ts = _get_expiry_ts(url)
    if not ts:
        return None
    ist_str, rel = _format_expiry_display(ts)
    return f"{ist_str} ({rel})" if ist_str else None


def _get_cookie_expiry(cookie_text: str) -> tuple[int, str, str] | None:
    """Extract expiry unix timestamp, localized date, and relative time from Netscape cookies."""
    if not cookie_text:
        return None
    etoken_exp = None
    min_exp = None
    for line in cookie_text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) >= 7:
            name = parts[5].strip()
            try:
                exp = int(parts[4].strip())
            except ValueError:
                continue
            if exp > 0:
                if name == "etoken":
                    etoken_exp = exp
                    break
                if min_exp is None or exp < min_exp:
                    min_exp = exp
    target_exp = etoken_exp or min_exp
    if not target_exp:
        return None
    date_str, rel_str = _format_expiry_display(target_exp)
    if not date_str:
        return None
    return target_exp, date_str, rel_str


def rich_to_fallback_html(rich_html: str) -> str:
    """Convert Rich HTML (headings, tables, details, lists) to standard Telegram HTML."""
    s = rich_html
    s = re.sub(r"<br\s*/?>\n?", "\n", s)
    # Headings -> bold
    s = re.sub(r"<h[1-6][^>]*>(.*?)</h[1-6]>", r"<b>\1</b>\n", s, flags=re.DOTALL)
    # Collapsible details -> expandable blockquote
    def _repl_details(m: re.Match) -> str:
        summary = m.group(1).strip()
        body = m.group(2).strip()
        return f"<blockquote expandable>{summary}\n{body}</blockquote>"
    s = re.sub(r"<details[^>]*>\s*<summary>(.*?)</summary>(.*?)</details>", _repl_details, s, flags=re.DOTALL)
    # Tables -> clean formatted rows
    def _repl_table(m: re.Match) -> str:
        tbl = m.group(1)
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", tbl, flags=re.DOTALL)
        out_rows = []
        headers = []
        for r in rows:
            th = re.findall(r"<th[^>]*>(.*?)</th>", r, flags=re.DOTALL)
            td = re.findall(r"<td[^>]*>(.*?)</td>", r, flags=re.DOTALL)
            if th and not headers:
                if len(th) == 1 and "colspan" in r:
                    out_rows.append(f"<b>{re.sub(r'<[^>]+>', '', th[0]).strip()}</b>")
                    headers = []
                else:
                    headers = [re.sub(r"<[^>]+>", "", h).strip() for h in th]
                continue
            if td:
                if headers and len(headers) == len(td):
                    items = [f"<b>{h}:</b> {d.strip()}" for h, d in zip(headers, td)]
                    out_rows.append(" • ".join(items))
                else:
                    items = [d.strip() for d in td]
                    out_rows.append(" | ".join(items))
        return "\n".join(out_rows) + "\n"
    s = re.sub(r"<table[^>]*>(.*?)</table>", _repl_table, s, flags=re.DOTALL)
    # Lists
    s = re.sub(r"<ul>(.*?)</ul>", lambda m: "\n".join("• " + x.strip() for x in re.findall(r"<li[^>]*>(.*?)</li>", m.group(1), re.DOTALL)) + "\n", s, flags=re.DOTALL)
    def _repl_ol(m: re.Match) -> str:
        items = re.findall(r"<li[^>]*>(.*?)</li>", m.group(1), re.DOTALL)
        return "\n".join(f"{i+1}. {x.strip()}" for i, x in enumerate(items)) + "\n"
    s = re.sub(r"<ol[^>]*>(.*?)</ol>", _repl_ol, s, flags=re.DOTALL)
    # Strip collage / img tags for standard HTML
    s = re.sub(r"<tg-collage[^>]*>(.*?)</tg-collage>", "", s, flags=re.DOTALL)
    s = re.sub(r"<img[^>]*src=[\"']([^\"']+)[\"'][^>]*>", r'<a href="\1">&#8203;</a>', s)
    s = re.sub(r"<figure[^>]*>(.*?)</figure>", r"\1", s, flags=re.DOTALL)
    s = re.sub(r"<figcaption[^>]*>(.*?)</figcaption>", r"\n<i>\1</i>\n", s, flags=re.DOTALL)
    s = re.sub(r"<hr\s*/?>", "——————————", s)
    s = re.sub(r"<mark[^>]*>(.*?)</mark>", r"<u>\1</u>", s, flags=re.DOTALL)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def _resolve_bot(obj: Any) -> Bot:
    """Safely extract the Bot instance without triggering ExtBot.bot which returns a User."""
    if isinstance(obj, Bot):
        return obj
    if hasattr(obj, "bot"):
        bot_attr = getattr(obj, "bot")
        if isinstance(bot_attr, Bot):
            return bot_attr
    return obj


async def send_rich_or_html(
    context_or_bot: Any,
    chat_id: int | str,
    rich_html: str,
    reply_markup: InlineKeyboardMarkup | None = None,
    fallback_html: str | None = None,
    disable_web_page_preview: bool = False,
) -> Message:
    """Send message using Telegram Rich Messages (Bot API 10.1+) with fallback to standard HTML."""
    bot = _resolve_bot(context_or_bot)
    data: dict[str, Any] = {
        "chat_id": chat_id,
        "rich_message": {"html": rich_html},
    }
    if reply_markup:
        data["reply_markup"] = reply_markup.to_dict()

    try:
        res = await bot._post("sendRichMessage", data=data)
        return Message.de_json(res, bot)
    except Exception as e:
        logger.debug("sendRichMessage failed, falling back to standard HTML: %s", e)
        fb = fallback_html or rich_to_fallback_html(rich_html)
        return await bot.send_message(
            chat_id=chat_id,
            text=fb,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup,
            disable_web_page_preview=disable_web_page_preview,
        )


async def edit_rich_or_html(
    context_or_bot: Any,
    chat_id: int | str,
    message_id: int,
    rich_html: str,
    reply_markup: InlineKeyboardMarkup | None = None,
    fallback_html: str | None = None,
    disable_web_page_preview: bool = False,
) -> Message | bool:
    """Edit message using Telegram Rich Messages (Bot API 10.1+) with fallback to standard HTML."""
    bot = _resolve_bot(context_or_bot)
    data: dict[str, Any] = {
        "chat_id": chat_id,
        "message_id": message_id,
        "rich_message": {"html": rich_html},
    }
    if reply_markup:
        data["reply_markup"] = reply_markup.to_dict()

    try:
        res = await bot._post("editMessageText", data=data)
        if isinstance(res, dict):
            return Message.de_json(res, bot)
        return bool(res)
    except Exception as e:
        logger.debug("editMessageText (rich) failed, falling back to standard HTML: %s", e)
        fb = fallback_html or rich_to_fallback_html(rich_html)
        return await bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=fb,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup,
            disable_web_page_preview=disable_web_page_preview,
        )


# ---------------------------------------------------------------------------
# Blocking logic (run in executor)
# ---------------------------------------------------------------------------
def _blocking_m3u8(url: str) -> dict:
    try:
        from .custom_session import CustomSession
        from .manifest_parser import Manifest
        from .movie_scraper import Movie
    except ImportError:
        from aebn_dl.custom_session import CustomSession  # type: ignore
        from aebn_dl.manifest_parser import Manifest  # type: ignore
        from aebn_dl.movie_scraper import Movie  # type: ignore

    session = CustomSession(impersonate="chrome")
    session.timeout = 30
    session.headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
    session.headers["Connection"] = "keep-alive"
    session.cookies.update({"ageGated": "", "terms": ""})
    for d in ("straight.aebn.com", "gay.aebn.com", "m.aebn.net", "vod.aebn.com"):
        session.cookies.set(name="ageGated", value="true", domain=d, path="/", secure=True)
    if DEFAULT_PROXY:
        session.proxies = {"all": DEFAULT_PROXY}

    movie = Movie(url, session)
    url_content_type = url.split("/")[3]
    movie_id = url.split("/")[5]
    headers = {"content-type": "application/x-www-form-urlencoded"}
    data = f"movieId={movie_id}&isPreview=true&format=DASH"
    deliver_url = f"https://{url_content_type}.aebn.com/{url_content_type}/deliver"
    resp = session.post(deliver_url, headers=headers, data=data).json()
    manifest_url = resp["url"]
    base_stream_url = manifest_url.rsplit("/", 1)[0]

    resolutions = None
    try:
        m = Manifest(url, movie.total_duration_seconds, session)
        m.base_stream_url = base_stream_url
        m.parse_content(session.get(manifest_url).content)
        resolutions = m.avaliable_resulutions
    except Exception:
        pass

    return {
        "studio": movie.studio_name,
        "title": movie.title,
        "movie_id": movie_id,
        "duration_s": movie.total_duration_seconds,
        "manifest_url": manifest_url,
        "base_stream_url": base_stream_url,
        "resolutions": resolutions,
        "cover_front": movie.cover_url_front,
    }


def _parse_m3u8_variants(master_url: str, cookies: str = "") -> dict[int, str]:
    """Fetch master m3u8 and return {height: variant_url}. Prefers highest."""
    try:
        try:
            from .ade_scraper import _get_session
        except ImportError:
            from aebn_dl.ade_scraper import _get_session  # type: ignore
        sess = _get_session(cookies or None)
        txt = sess.get(master_url, timeout=15).text
    except Exception:
        return {}
    variants: dict[int, str] = {}
    lines = txt.splitlines()
    for i, line in enumerate(lines):
        if "RESOLUTION=" in line:
            m = re.search(r"RESOLUTION=\d+x(\d+)", line)
            if m and i + 1 < len(lines):
                h = int(m.group(1))
                url = lines[i + 1].strip()
                if url and not url.startswith("#"):
                    variants[h] = url
    return variants


def _pick_preferred_links(variants: dict[int, str]) -> list[tuple[int, str]]:
    """Return links sorted by preference: 2160 > 1080 > 720 > rest descending."""
    pref_order = [2160, 1080, 720, 480, 360, 240, 144]
    picked: list[tuple[int, str]] = []
    for h in pref_order:
        if h in variants:
            picked.append((h, variants[h]))
    # add any remaining not in pref_order (higher first)
    for h in sorted(variants, reverse=True):
        if h not in {p[0] for p in picked}:
            picked.append((h, variants[h]))
    return picked


def _format_duration(duration_s: int | None) -> str:
    """Format duration in seconds into a human-readable string (e.g. '28 min', '2h 22m')."""
    if not duration_s or duration_s <= 0:
        return "?"
    hours = duration_s // 3600
    mins = (duration_s % 3600) // 60
    if hours > 0:
        return f"{hours}h {mins:02d}m" if mins else f"{hours}h"
    return f"{mins} min" if mins > 0 else f"{duration_s}s"


def _blocking_ade_m3u8(url: str, cookies: str = "") -> dict:
    try:
        from .ade_scraper import extract_ade_duration_seconds, get_ade_manifest
    except ImportError:
        from aebn_dl.ade_scraper import extract_ade_duration_seconds, get_ade_manifest  # type: ignore

    result = get_ade_manifest(url, cookies_str=cookies or None)

    # Extract resolutions from streams
    resolutions = []
    for s in result.get("streams", []):
        h = s.get("source_height", 0)
        if h and h not in resolutions:
            resolutions.append(h)
    resolutions.sort()

    item_detail = result.get("item_detail", {})
    scene_id = result.get("scene_id")
    playlist_url = result.get("playlist_url", "")
    duration_s = result.get("duration_s", 0)
    if not duration_s:
        duration_s = extract_ade_duration_seconds(item_detail, scene_id, playlist_url)

    # Fetch variant links — prefer 2160p/1080p, fallback to 720p/lower
    preferred_links: list[tuple[int, str]] = []
    try:
        variants = _parse_m3u8_variants(result["playlist_url"], cookies)
        preferred_links = _pick_preferred_links(variants)
    except Exception:
        pass

    return {
        "studio": html_unescape(item_detail.get("studio", {}).get("name", "AdultDVDEmpire")),
        "title": html_unescape(result.get("title", "")),
        "movie_title": html_unescape(result.get("movie_title") or result.get("title", "")),
        "scene_title": html_unescape(result.get("scene_title", "")),
        "movie_id": result["item_id"],
        "scene_id": result.get("scene_id"),
        "duration_s": duration_s,
        "manifest_url": result["playlist_url"],
        "preferred_links": preferred_links,
        "front_cover": item_detail.get("front_cover"),
        "back_cover": item_detail.get("back_cover"),
        "poster": item_detail.get("poster"),
        "streams": result.get("streams", []),
        "resolutions": resolutions,
        "is_authorized": result.get("is_authorized", False),
        "ppm_remaining": result.get("ppm_remaining", 0),
    }


def _blocking_ade_account(cookies: str = "") -> dict:
    """Fetch ADE account info: PPM minutes, membership status, email."""
    try:
        from .ade_scraper import _get_session
    except ImportError:
        from aebn_dl.ade_scraper import _get_session  # type: ignore

    session = _get_session(cookies or None)
    r = session.get("https://www.adultdvdempire.com/account/accounthomepage")
    r.raise_for_status()
    html = r.text

    import re as _re

    # Email
    email_match = _re.search(r'text-success"></i>\s*([^<]+)', html)
    email = email_match.group(1).strip() if email_match else "Unknown"

    # Total PPM minutes
    ppm_match = _re.search(r'ppm-minutes__total-minutes">(\d+)', html)
    total_ppm = int(ppm_match.group(1)) if ppm_match else 0

    # Breakdown
    breakdown = _re.findall(r'<dt>(Mins|Bonus Mins)</dt><dd>(\d+)</dd>', html)
    mins = next((int(v) for k, v in breakdown if k == "Mins"), 0)
    bonus = next((int(v) for k, v in breakdown if k == "Bonus Mins"), 0)

    # Membership
    membership_match = _re.search(r'membership-status.*?total-minutes">(.*?)</p>', html, _re.DOTALL)
    membership = membership_match.group(1).strip() if membership_match else "Unknown"

    return {
        "email": email,
        "total_ppm": total_ppm,
        "mins": mins,
        "bonus_mins": bonus,
        "membership": membership,
    }


def _build_manifest_section(data: dict[str, Any]) -> str:
    """Build an organized, elegant manifest section with one-tap copyable links."""
    pref_links = data.get("preferred_links", [])
    master_url = data.get("manifest_url", "")

    if not pref_links:
        return (
            "<b>📹 Manifest Stream URL</b> (tap link to copy):<br/>\n"
            f"<code>{_esc(master_url)}</code>"
        )

    sorted_links = sorted(pref_links, key=lambda x: x[0], reverse=True)
    cutoff = 1080 if any(h >= 1080 for h, _ in sorted_links) else sorted_links[0][0]

    top_streams: list[str] = []
    other_streams: list[str] = []

    for h, link in sorted_links:
        if h >= 2160:
            label = f"⭐ <b>{h}p (4K UHD):</b>"
        elif h >= 1440:
            label = f"⭐ <b>{h}p (2K QHD):</b>"
        elif h >= 1080:
            label = f"⭐ <b>{h}p (Full HD):</b>"
        elif h >= 720:
            label = f"<b>{h}p (HD):</b>"
        elif h >= 480:
            label = f"<b>{h}p (SD):</b>"
        else:
            label = f"<b>{h}p:</b>"

        block = f"{label}<br/>\n<code>{_esc(link)}</code>"
        if h >= cutoff:
            top_streams.append(block)
        else:
            other_streams.append(block)

    top_streams.append(f"🌐 <b>Master Playlist (Adaptive Bitrate):</b><br/>\n<code>{_esc(master_url)}</code>")

    out = [
        "<b>📹 Stream Manifest Links</b> (tap link to copy):<br/><br/>\n",
        "<br/><br/>\n".join(top_streams),
    ]

    if other_streams:
        other_labels = ", ".join(f"{h}p" for h, _ in sorted_links if h < cutoff)
        out.append(
            f"<br/><br/>\n<blockquote expandable>"
            f"<b>🔽 Other Resolutions ({other_labels})</b><br/><br/>\n"
            + "<br/><br/>\n".join(other_streams)
            + "</blockquote>"
        )

    return "".join(out)


# ---------------------------------------------------------------------------
# Bot actions
# ---------------------------------------------------------------------------
async def do_m3u8(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str, edit: bool = False):
    chat_id = update.effective_chat.id
    if edit:
        try:
            await context.bot.answer_callback_query(update.callback_query.id)
        except Exception:
            pass
        msg = update.callback_query.message
        msg_id = msg.message_id
    else:
        esc_url = _esc(url)
        msg = await context.bot.send_message(chat_id, f"🔍 <b>Fetching manifest…</b>\n<code>{esc_url}</code>", parse_mode=ParseMode.HTML)
        msg_id = msg.message_id

    try:
        if is_ade_url(url):
            uid = update.effective_user.id if update.effective_user else 0
            cookies = _user_ade_cookies.get(uid) or _user_ade_cookies.get(0, "")
            data = await asyncio.get_running_loop().run_in_executor(executor, _blocking_ade_m3u8, url, cookies)
        else:
            data = await asyncio.get_running_loop().run_in_executor(executor, _blocking_m3u8, url)
    except Exception as e:
        err_rich = (
            "<h3>❌ Extraction Failed</h3>\n"
            "<blockquote expandable>\n"
            f"<b>Error Details:</b>\n<code>{_esc(str(e))}</code>\n"
            "</blockquote>"
        )
        kb = None
        if is_ade_url(url) and ("Not authorized" in str(e) or "etoken" in str(e).lower() or "cookies" in str(e).lower()):
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("🍪 Update Cookies", callback_data="update_cookies")],
            ])
        await edit_rich_or_html(context.bot, chat_id, msg_id, err_rich, reply_markup=kb)
        return

    dur = _format_duration(data.get("duration_s"))
    if data.get("resolutions"):
        r_sorted = sorted(data["resolutions"])
        res_summary = f"{r_sorted[0]}p – {r_sorted[-1]}p" if len(r_sorted) > 2 else ", ".join(f"{r}p" for r in r_sorted)
    else:
        res_summary = "N/A"

    site_label = site_label_for(url)
    studio = _esc(html_unescape(data.get("studio") or "Unknown"))
    movie_title = _esc(html_unescape(data.get("movie_title") or data.get("title") or "Unknown"))
    scene_title = _esc(html_unescape(data.get("scene_title") or ""))

    if scene_title:
        header_block = (
            f"<h3>🎬 [{site_label}] {movie_title}</h3>\n"
            f"🎭 <b>Scene:</b> <i>{scene_title}</i><br/>\n"
            f"🏢 <b>Studio:</b> {studio}<br/>"
        )
    else:
        header_block = (
            f"<h3>🎬 [{site_label}] {movie_title}</h3>\n"
            f"🏢 <b>Studio:</b> {studio}<br/>"
        )

    movie_id = _esc(str(data["movie_id"]))
    id_header = "Scene ID" if data.get("scene_id") else "Movie ID"
    id_val = _esc(str(data.get("scene_id") or movie_id))

    exp_ts = _get_expiry_ts(data["manifest_url"])
    if exp_ts:
        date_str, rel_str = _format_expiry_display(exp_ts)
        expiry_line = (
            f'⏰ <b>Expires:</b> <tg-time unix="{exp_ts}" format="wDT">{_esc(date_str)}</tg-time> '
            f'(<tg-time unix="{exp_ts}" format="r">{_esc(rel_str)}</tg-time>)<br/><br/>\n'
        )
    else:
        expiry_line = ""

    covers = [c for c in (data.get("front_cover"), data.get("back_cover"), data.get("poster")) if c]
    if not covers and data.get("cover_front"):
        covers = [data["cover_front"]]

    media_block = ""
    if len(covers) >= 2:
        media_block = f'<tg-collage><img src="{_esc(covers[0])}"/><img src="{_esc(covers[1])}"/></tg-collage>\n'
    elif covers:
        media_block = f'<img src="{_esc(covers[0])}"/>\n'

    preview_links = "".join(f'<a href="{_esc(c)}">&#8203;</a>' for c in covers[:2])

    copy_url = data["manifest_url"]
    if is_ade_url(url) and data.get("preferred_links"):
        copy_url = data["preferred_links"][0][1]

    manifest_section = _build_manifest_section(data)

    rich_text = (
        f"{media_block}"
        f"{header_block}\n"
        f"<table bordered compact>\n"
        f"  <tr><th>Duration</th><th>Resolutions</th><th>{id_header}</th></tr>\n"
        f"  <tr><td>{dur}</td><td>{res_summary}</td><td><code>{id_val}</code></td></tr>\n"
        f"</table><br/>\n"
        f"{expiry_line}"
        f"{manifest_section}<br/><br/>\n"
        f"<blockquote expandable><b>🔗 Source URL:</b><br/><code>{_esc(url)}</code></blockquote>"
    )

    fallback_text = f"{preview_links}{rich_to_fallback_html(rich_text)}"

    buttons = [
        [
            InlineKeyboardButton("📋 Copy Manifest", copy_text=CopyTextButton(copy_url)),
            InlineKeyboardButton("🔄 Refresh", callback_data=cb("m3u8", url)),
        ]
    ]
    kb = InlineKeyboardMarkup(buttons)

    await edit_rich_or_html(
        context.bot,
        chat_id,
        msg_id,
        rich_text,
        reply_markup=kb,
        fallback_html=fallback_text,
        disable_web_page_preview=False,
    )


async def do_info(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str, edit: bool = False):
    chat_id = update.effective_chat.id
    if edit:
        try:
            await context.bot.answer_callback_query(update.callback_query.id)
        except Exception:
            pass
        msg = update.callback_query.message
        msg_id = msg.message_id
    else:
        esc_url = _esc(url)
        msg = await context.bot.send_message(chat_id, f"🔍 <b>Fetching info…</b>\n<code>{esc_url}</code>", parse_mode=ParseMode.HTML)
        msg_id = msg.message_id

    # ADE URLs: reuse the m3u8 flow (it already returns title, duration, streams)
    if is_ade_url(url):
        try:
            uid = update.effective_user.id if update.effective_user else 0
            cookies = _user_ade_cookies.get(uid) or _user_ade_cookies.get(0, "")
            data = await asyncio.get_running_loop().run_in_executor(executor, _blocking_ade_m3u8, url, cookies)
        except Exception as e:
            err_rich = (
                "<h3>❌ Request Failed</h3>\n"
                "<blockquote expandable>\n"
                f"<b>Error Details:</b>\n<code>{_esc(str(e))}</code>\n"
                "</blockquote>"
            )
            kb = None
            if "Not authorized" in str(e) or "etoken" in str(e).lower() or "cookies" in str(e).lower():
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🍪 Update Cookies", callback_data="update_cookies")],
                ])
            await edit_rich_or_html(context.bot, chat_id, msg_id, err_rich, reply_markup=kb)
            return

        dur = _format_duration(data.get("duration_s"))
        if data.get("resolutions"):
            r_sorted = sorted(data["resolutions"])
            res_summary = f"{r_sorted[0]}p – {r_sorted[-1]}p" if len(r_sorted) > 2 else ", ".join(f"{r}p" for r in r_sorted)
        else:
            res_summary = "N/A"

        site_label = site_label_for(url)
        studio = _esc(html_unescape(data.get("studio") or "Unknown"))
        movie_title = _esc(html_unescape(data.get("movie_title") or data.get("title") or "Unknown"))
        scene_title = _esc(html_unescape(data.get("scene_title") or ""))

        if scene_title:
            header_block = (
                f"<h3>ℹ️ [{site_label}] {movie_title}</h3>\n"
                f"🎭 <b>Scene:</b> <i>{scene_title}</i><br/>\n"
                f"🏢 <b>Studio:</b> {studio}<br/>"
            )
        else:
            header_block = (
                f"<h3>ℹ️ [{site_label}] {movie_title}</h3>\n"
                f"🏢 <b>Studio:</b> {studio}<br/>"
            )

        movie_id = _esc(str(data["movie_id"]))
        id_header = "Scene ID" if data.get("scene_id") else "Movie ID"
        id_val = _esc(str(data.get("scene_id") or movie_id))
        covers = [c for c in (data.get("front_cover"), data.get("back_cover"), data.get("poster")) if c]
        media_block = f'<img src="{_esc(covers[0])}"/>\n' if covers else ""
        preview_links = f'<a href="{_esc(covers[0])}">&#8203;</a>' if covers else ""

        rich_text = (
            f"{media_block}"
            f"{header_block}\n"
            f"<table bordered compact>\n"
            f"  <tr><th>Duration</th><th>Available Quality</th><th>{id_header}</th></tr>\n"
            f"  <tr><td>{dur}</td><td>{res_summary}</td><td><code>{id_val}</code></td></tr>\n"
            f"</table><br/>\n"
            f"<blockquote>Tap <b>Get m3u8</b> below to extract playback manifests and variant streams.</blockquote>"
        )
        fallback_text = f"{preview_links}{rich_to_fallback_html(rich_text)}"
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📄 Get m3u8", callback_data=cb("m3u8", url))],
        ])
        await edit_rich_or_html(context.bot, chat_id, msg_id, rich_text, reply_markup=kb, fallback_html=fallback_text)
        return

    try:
        dl = Downloader(url=url, proxy=DEFAULT_PROXY or None, proxy_metadata_only=bool(DEFAULT_PROXY), show_progress=False, log_level="ERROR")
        dl._initialize_download()
        movie = dl._scrape_movie_info()
        dl._process_manifest(movie, requires_scene_boundaries=True)
    except Exception as e:
        err_rich = (
            "<h3>❌ Request Failed</h3>\n"
            "<blockquote expandable>\n"
            f"<b>Error Details:</b>\n<code>{_esc(str(e))}</code>\n"
            "</blockquote>"
        )
        await edit_rich_or_html(context.bot, chat_id, msg_id, err_rich)
        return

    dur = _format_duration(movie.total_duration_seconds)
    if dl.manifest.avaliable_resulutions:
        r_sorted = sorted(dl.manifest.avaliable_resulutions)
        res_summary = f"{r_sorted[0]}p – {r_sorted[-1]}p" if len(r_sorted) > 2 else ", ".join(f"{r}p" for r in r_sorted)
    else:
        res_summary = "N/A"
    studio = _esc(html_unescape(movie.studio_name or "Unknown"))
    title = _esc(html_unescape(movie.title or "Unknown"))

    performers_section = ""
    if movie.performers:
        p_items = "\n".join(f"  <li>{_esc(p)}</li>" for p in movie.performers)
        performers_section = (
            f"<details open>\n"
            f"  <summary><b>🌟 Performers ({len(movie.performers)})</b></summary>\n"
            f"  <ul>\n{p_items}\n  </ul>\n"
            f"</details>\n"
        )

    media_block = f'<img src="{_esc(movie.cover_url_front)}"/>\n' if movie.cover_url_front else ""
    preview_links = f'<a href="{_esc(movie.cover_url_front)}">&#8203;</a>' if movie.cover_url_front else ""

    rich_text = (
        f"{media_block}"
        f"<h3>ℹ️ [AEBN] {title}</h3>\n"
        f"🏢 <b>Studio:</b> {studio}<br/><br/>\n"
        f"<table bordered compact>\n"
        f"  <tr><th>Duration</th><th>Scenes</th><th>Resolutions</th></tr>\n"
        f"  <tr><td>{dur}</td><td>{len(movie.scenes)}</td><td>{res_summary}</td></tr>\n"
        f"</table><br/>\n"
        f"{performers_section}\n"
        f"<blockquote>Tap <b>Get m3u8</b> below to extract DASH playback manifests.</blockquote>"
    )
    fallback_text = f"{preview_links}{rich_to_fallback_html(rich_text)}"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📄 Get m3u8", callback_data=cb("m3u8", url))],
    ])
    await edit_rich_or_html(context.bot, chat_id, msg_id, rich_text, reply_markup=kb, fallback_html=fallback_text)


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------
async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        return

    uid = update.effective_user.id
    cookies = _user_ade_cookies.get(uid) or _user_ade_cookies.get(0, "")

    # Check cookie expiry
    cookie_exp_row = ""
    if cookies:
        c_info = _get_cookie_expiry(cookies)
        if c_info:
            c_ts, c_date, c_rel = c_info
            cookie_exp_row = (
                f'  <tr><td><b>Cookie Expiry</b></td><td>'
                f'<tg-time unix="{c_ts}" format="wDT">{_esc(c_date)}</tg-time> '
                f'(<tg-time unix="{c_ts}" format="r">{_esc(c_rel)}</tg-time>)</td></tr>\n'
            )

    # Fetch account info
    account = None
    if cookies:
        try:
            account = await asyncio.get_running_loop().run_in_executor(
                executor, _blocking_ade_account, cookies
            )
        except Exception as e:
            logger.warning("Failed to fetch ADE account: %s", e)

    if account:
        rich_text = (
            f"<h3>👋 Welcome Back to AEBN & ADE Bot</h3>\n\n"
            f"<table bordered striped compact>\n"
            f"  <tr><th colspan=\"2\">👤 AdultDVDEmpire Account</th></tr>\n"
            f"  <tr><td><b>Account Email</b></td><td><code>{_esc(account['email'])}</code></td></tr>\n"
            f"  <tr><td><b>PPM Minutes</b></td><td><b>{account['total_ppm']} min</b> ({_esc(str(account['mins']))} paid + {_esc(str(account['bonus_mins']))} bonus)</td></tr>\n"
            f"  <tr><td><b>Membership</b></td><td>{_esc(account['membership'])}</td></tr>\n"
            f"{cookie_exp_row}"
            f"</table>\n\n"
            f"<details open>\n"
            f"  <summary><b>🚀 Quick Actions</b></summary>\n"
            f"  <ul>\n"
            f"    <li>Paste any <b>AEBN</b> or <b>AdultDVDEmpire</b> link to get DASH/m3u8 manifests.</li>\n"
            f"    <li>Use <code>/info &lt;url&gt;</code> to inspect movie duration, scenes and cast.</li>\n"
            f"    <li>Use <code>/cookies</code> to refresh or manage your ADE session.</li>\n"
            f"  </ul>\n"
            f"</details>"
        )
    else:
        cookie_status_block = ""
        if cookie_exp_row:
            cookie_status_block = (
                "<table bordered compact>\n"
                "  <tr><th colspan=\"2\">🍪 Saved ADE Cookies</th></tr>\n"
                f"{cookie_exp_row}"
                "</table>\n\n"
            )
        rich_text = (
            "<h3>👋 Welcome to AEBN & ADE Manifest Bot</h3>\n\n"
            f"{cookie_status_block}"
            "<details open>\n"
            "  <summary><b>🚀 Getting Started</b></summary>\n"
            "  <ul>\n"
            "    <li>Paste any <b>AEBN</b> or <b>AdultDVDEmpire</b> URL to get stream manifests.</li>\n"
            "    <li>Use <code>/m3u8 &lt;url&gt;</code> or just paste a link directly.</li>\n"
            "    <li>For full ADE VODs, configure your session with <code>/cookies</code>.</li>\n"
            "  </ul>\n"
            "</details>\n\n"
            "<table bordered compact>\n"
            "  <tr><th>Command</th><th>Action</th></tr>\n"
            "  <tr><td><code>/m3u8 &lt;url&gt;</code></td><td>Extract DASH/m3u8 manifests</td></tr>\n"
            "  <tr><td><code>/info &lt;url&gt;</code></td><td>Movie info, scenes & cast</td></tr>\n"
            "  <tr><td><code>/cookies</code></td><td>Set ADE login session</td></tr>\n"
            "  <tr><td><code>/help</code></td><td>Full command guide & tips</td></tr>\n"
            "</table>"
        )

    buttons = [
        [InlineKeyboardButton("👤 ADE Account", url="https://www.adultdvdempire.com/account/accounthomepage")],
        [InlineKeyboardButton("🍪 Update Cookies", callback_data="update_cookies")],
    ]
    kb = InlineKeyboardMarkup(buttons)
    await send_rich_or_html(context.bot, update.effective_chat.id, rich_text, reply_markup=kb)


async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        return
    await send_rich_or_html(context.bot, update.effective_chat.id, HELP_RICH_TEXT)


async def m3u8_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        return
    text = " ".join(context.args) if context.args else (update.message.text or "")
    if not extract_url(text):
        raw = update.message.text or ""
        text = re.sub(r"^/(m3u8|dash|mpd|manifest|url)\S*\s*", "", raw, flags=re.IGNORECASE)
    url = extract_url(text)
    if not url:
        await send_rich_or_html(
            context.bot,
            update.effective_chat.id,
            "<h3>⚠️ Missing URL</h3>\n<blockquote>Usage: <code>/m3u8 &lt;url&gt;</code></blockquote>",
        )
        return
    await do_m3u8(update, context, url)


async def info_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        return
    text = " ".join(context.args) if context.args else (update.message.text or "")
    url = extract_url(text)
    if not url:
        await send_rich_or_html(
            context.bot,
            update.effective_chat.id,
            "<h3>⚠️ Missing URL</h3>\n<blockquote>Usage: <code>/info &lt;url&gt;</code></blockquote>",
        )
        return
    await do_info(update, context, url)


async def cookies_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        return
    uid = update.effective_user.id
    chat_id = update.effective_chat.id

    raw = update.message.text or ""
    cookie_text = re.sub(r"^/cookies\s*", "", raw, count=1, flags=re.IGNORECASE).strip()

    if not cookie_text:
        _awaiting_cookies.add(uid)
        has_cookies = bool(_user_ade_cookies.get(uid))
        if has_cookies:
            c_info = _get_cookie_expiry(_user_ade_cookies[uid])
            exp_row = ""
            if c_info:
                c_ts, c_date, c_rel = c_info
                exp_row = (
                    f"<br/><br/>⏰ <b>Cookie Expiry:</b> <tg-time unix=\"{c_ts}\" format=\"wDT\">{_esc(c_date)}</tg-time> "
                    f"(<tg-time unix=\"{c_ts}\" format=\"r\">{_esc(c_rel)}</tg-time>)"
                )
            rich_text = (
                "<h3>🍪 ADE Cookies Configured</h3>\n\n"
                f"<blockquote>Send new cookies to replace them, or send <code>/cookies clear</code> to remove saved cookies.{exp_row}</blockquote>"
            )
        else:
            rich_text = (
                "<h3>🍪 AdultDVDEmpire / Elegant Angel Cookies Setup</h3>\n\n"
                "<ol>\n"
                "  <li>Install <b>Cookie-Editor</b> extension in your browser.</li>\n"
                "  <li>Log in to <code>adultdvdempire.com</code> or <code>elegantangel.com</code>.</li>\n"
                "  <li>Open Cookie-Editor → click <b>Export</b> → select <b>Netscape format</b>.</li>\n"
                "  <li>Paste the exported text into this chat (or send <code>/cookies &lt;text&gt;</code>).</li>\n"
                "</ol>\n"
                "<blockquote>Session cookies unlock full VOD manifests and account PPM balance.</blockquote>"
            )
        await send_rich_or_html(context.bot, chat_id, rich_text)
        return

    if cookie_text.lower() == "clear":
        _user_ade_cookies.pop(uid, None)
        _awaiting_cookies.discard(uid)
        _save_cookies()
        rich_text = (
            "<h3>🗑️ ADE Cookies Cleared</h3>\n\n"
            "<blockquote>Your saved AdultDVDEmpire cookies have been cleared.</blockquote>"
        )
        await send_rich_or_html(context.bot, chat_id, rich_text)
        return

    if "etoken" not in cookie_text:
        rich_text = (
            "<h3>⚠️ Invalid Cookies Format</h3>\n\n"
            "<blockquote>No <code>etoken</code> was found in the provided cookies.<br/>\n"
            "Make sure to export in <b>Netscape format</b> from <code>adultdvdempire.com</code> and paste the full export.</blockquote>"
        )
        await send_rich_or_html(context.bot, chat_id, rich_text)
        return

    _user_ade_cookies[uid] = cookie_text
    _awaiting_cookies.discard(uid)
    _save_cookies()
    c_info = _get_cookie_expiry(cookie_text)
    exp_text = ""
    if c_info:
        c_ts, c_date, c_rel = c_info
        exp_text = (
            f"<br/><br/>⏰ <b>Cookie Expiry:</b> <tg-time unix=\"{c_ts}\" format=\"wDT\">{_esc(c_date)}</tg-time> "
            f"(<tg-time unix=\"{c_ts}\" format=\"r\">{_esc(c_rel)}</tg-time>)"
        )
    rich_text = (
        "<h3>✅ ADE Cookies Saved Successfully!</h3>\n\n"
        f"<blockquote>Your AdultDVDEmpire session cookies have been saved successfully.{exp_text}<br/><br/>\n"
        "Now paste any AdultDVDEmpire movie URL to extract authorized stream manifests.</blockquote>"
    )
    await send_rich_or_html(context.bot, chat_id, rich_text)


async def url_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        return
    text = update.message.text or ""
    uid = update.effective_user.id
    chat_id = update.effective_chat.id

    if uid in _awaiting_cookies:
        if "etoken" in text:
            _user_ade_cookies[uid] = text
            _awaiting_cookies.discard(uid)
            _save_cookies()
            c_info = _get_cookie_expiry(text)
            exp_text = ""
            if c_info:
                c_ts, c_date, c_rel = c_info
                exp_text = (
                    f"<br/><br/>⏰ <b>Cookie Expiry:</b> <tg-time unix=\"{c_ts}\" format=\"wDT\">{_esc(c_date)}</tg-time> "
                    f"(<tg-time unix=\"{c_ts}\" format=\"r\">{_esc(c_rel)}</tg-time>)"
                )
            rich_text = (
                "<h3>✅ ADE Cookies Saved Successfully!</h3>\n\n"
                f"<blockquote>Your AdultDVDEmpire session cookies have been saved successfully.{exp_text}<br/><br/>\n"
                "Now paste any AdultDVDEmpire movie URL to extract stream manifests.</blockquote>"
            )
            await send_rich_or_html(context.bot, chat_id, rich_text)
            return
        else:
            rich_text = (
                "<h3>⚠️ Invalid Cookies</h3>\n\n"
                "<blockquote>No <code>etoken</code> found. Please paste the full Netscape cookie export.</blockquote>"
            )
            await send_rich_or_html(context.bot, chat_id, rich_text)
            return

    if "etoken" in text and not extract_url(text):
        _user_ade_cookies[uid] = text
        _save_cookies()
        c_info = _get_cookie_expiry(text)
        exp_text = ""
        if c_info:
            c_ts, c_date, c_rel = c_info
            exp_text = (
                f"<br/><br/>⏰ <b>Cookie Expiry:</b> <tg-time unix=\"{c_ts}\" format=\"wDT\">{_esc(c_date)}</tg-time> "
                f"(<tg-time unix=\"{c_ts}\" format=\"r\">{_esc(c_rel)}</tg-time>)"
            )
        rich_text = (
            "<h3>✅ ADE Cookies Saved Successfully!</h3>\n\n"
            f"<blockquote>Your AdultDVDEmpire session cookies have been saved successfully.{exp_text}<br/><br/>\n"
            "Now paste any AdultDVDEmpire movie URL to extract stream manifests.</blockquote>"
        )
        await send_rich_or_html(context.bot, chat_id, rich_text)
        return

    url = extract_url(text)
    if not url or text.strip().startswith("/"):
        return
    await do_m3u8(update, context, url)


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        await update.callback_query.answer("Unauthorized", show_alert=True)
        return
    data = update.callback_query.data or ""

    if data == "update_cookies":
        await update.callback_query.answer()
        _awaiting_cookies.add(update.effective_user.id)
        rich_text = (
            "<h3>🍪 Send New ADE Cookies</h3>\n\n"
            "<blockquote>Paste your Netscape cookie export from <code>adultdvdempire.com</code>.</blockquote>"
        )
        await send_rich_or_html(context.bot, update.effective_chat.id, rich_text)
        return

    action, url = resolve_cb(data)
    if not url:
        await update.callback_query.answer("Expired — send URL again", show_alert=True)
        return
    if action == "m3u8":
        await do_m3u8(update, context, url, edit=True)
    elif action == "info":
        await do_info(update, context, url, edit=True)
    else:
        await update.callback_query.answer("Unknown action")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
def build_app(token: str | None = None) -> Application:
    token = token or BOT_TOKEN or os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN not set.")
    _load_cookies()
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("help", help_handler))
    app.add_handler(CommandHandler(["m3u8", "dash", "mpd", "manifest", "url"], m3u8_handler))
    app.add_handler(CommandHandler("info", info_handler))
    app.add_handler(CommandHandler("cookies", cookies_handler))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, url_message_handler))
    return app


def _start_health_server() -> None:
    port = os.getenv("PORT")
    if not port:
        return
    try:
        try:
            from .web import start_in_background
        except ImportError:
            from aebn_dl.web import start_in_background  # type: ignore
        start_in_background(int(port))
        logger.info("Web UI + API listening on port %s", port)
    except Exception as e:
        logger.warning("Could not start web server on port %s: %s", port, e)


def main():
    token = BOT_TOKEN or os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not token:
        print("TELEGRAM_BOT_TOKEN not set.\nExport it or create .env file.")
        raise SystemExit(1)
    _start_health_server()
    print(f"Starting AEBN Bot — m3u8/DASH only\n  ALLOWED={'all' if not ALLOWED_USER_IDS else ALLOWED_USER_IDS}")
    build_app(token).run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
