"""Standalone web server + JSON API mirroring the Telegram bot actions.

Serves the Vite + TypeScript frontend (``frontend/dist``, built with
``npm run build``) and exposes:

- ``GET  /``                 frontend
- ``GET  /health``           health check (``OK``)
- ``GET  /api/auth-check``   200 when open or logged in, else 401
- ``POST /api/login``        ``{"password": ...}`` -> auth cookie (only if WEB_PASSWORD set)
- ``POST /api/logout``       clear auth cookie
- ``POST /api/extract``      ``{"url": ..., "mode": "manifest"|"info", "cookies": "..."}``
- ``GET  /api/cookies``      per-site session status (``ade`` + ``ea``)
- ``POST /api/cookies``      ``{"site": "ade"|"ea", "cookies": "..."}`` save session
- ``DELETE /api/cookies?site=ade|ea``  clear one (or both) saved session(s)
- ``GET  /api/plainraw?site=ade``      pull site paste content from PlainRaw
- ``POST /api/plainraw``     ``{"site": ..., "content": ...}`` push to PlainRaw

Only the standard library is used so this works without the ``bot`` extra.
Run standalone with ``aebndl-web`` (or ``python -m aebn_dl.web``).
When the Telegram bot runs with ``PORT`` set, it serves this same app in a
background thread instead of the plain ``OK`` health responder.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from html import unescape as html_unescape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

logger = logging.getLogger(__name__)

HERE = Path(__file__).resolve().parent
COOKIES_FILE = HERE / "ade_cookies.json"
FRONTEND_DIST = HERE.parent / "frontend" / "dist"

_ASSET_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".png": "image/png",
    ".woff2": "font/woff2",
}


def _frontend_index() -> Path | None:
    dist_index = FRONTEND_DIST / "index.html"
    return dist_index if dist_index.exists() else None

try:
    from dotenv import load_dotenv
    load_dotenv()
    load_dotenv(dotenv_path=HERE / ".env", override=False)
    load_dotenv(dotenv_path=HERE.parent / ".env", override=False)
except ImportError:
    pass

WEB_PASSWORD = os.getenv("WEB_PASSWORD", "")
DEFAULT_PROXY = os.getenv("AEBN_PROXY", "")
DEFAULT_THREADS = int(os.getenv("AEBN_THREADS", "5"))

executor = ThreadPoolExecutor(max_workers=8)
_auth_tokens: set[str] = set()


# ---------------------------------------------------------------------------
# Small helpers (telegram-free copies of the bot logic)
# ---------------------------------------------------------------------------

def _is_open() -> bool:
    return not WEB_PASSWORD


def _authed(headers) -> bool:
    if _is_open():
        return True
    cookie = headers.get("Cookie", "")
    m = re.search(r"wauth=([a-f0-9]+)", cookie)
    return bool(m) and m.group(1) in _auth_tokens


def _cookie_expiry(cookie_text: str) -> dict[str, Any] | None:
    """Extract etoken (or earliest) expiry from Netscape cookie text."""
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
            try:
                exp = int(parts[4].strip())
            except ValueError:
                continue
            if exp > 0:
                if parts[5].strip() == "etoken":
                    etoken_exp = exp
                    break
                if min_exp is None or exp < min_exp:
                    min_exp = exp
    target = etoken_exp or min_exp
    if not target:
        return None
    import datetime
    utc = datetime.datetime.fromtimestamp(target, tz=datetime.timezone.utc)
    now = int(datetime.datetime.now(tz=datetime.timezone.utc).timestamp())
    delta = target - now
    return {
        "ts": target,
        "date": utc.strftime("%d-%m-%Y %H:%M UTC"),
        "expired": delta <= 0,
        "seconds_left": max(delta, 0),
    }


def _load_all_cookies() -> dict:
    try:
        data = json.loads(COOKIES_FILE.read_text())
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _load_saved_cookies() -> str:
    """Legacy global session (key "0", shared with the Telegram bot)."""
    return _load_all_cookies().get("0", "")


def _load_site_cookies(site: str) -> str:
    """Site session. "ade" falls back to the legacy global key ("0", shared
    with the Telegram bot); "ea" is strictly separate."""
    data = _load_all_cookies()
    if site == "ade":
        return data.get("ade", "") or data.get("0", "")
    return data.get("ea", "")


def _save_site_cookies(site: str, cookie_text: str) -> None:
    data = _load_all_cookies()
    data[site] = cookie_text
    if site == "ade":
        # Mirror ADE cookies to the legacy global key so the Telegram bot
        # (which reads key "0") keeps working with existing logic.
        data["0"] = cookie_text
    COOKIES_FILE.write_text(json.dumps(data, indent=2))


# ---------------------------------------------------------------------------
# PlainRaw sync (https://api.plainraw.com/api) — one paste per site.
# Configure with PLAINRAW_ADE_UUID / PLAINRAW_ADE_KEY
# (and PLAINRAW_EA_UUID / PLAINRAW_EA_KEY for Elegant Angel).
# ---------------------------------------------------------------------------
PLAINRAW_API = "https://api.plainraw.com/api"
PLAINRAW_MAX = 30000
PLAINRAW_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"


def _plainraw_cfg(site: str) -> tuple[str, str]:
    site = site.lower()
    if site not in ("ade", "ea"):
        return "", ""
    return (
        os.getenv(f"PLAINRAW_{site.upper()}_UUID", ""),
        os.getenv(f"PLAINRAW_{site.upper()}_KEY", ""),
    )


def _plainraw_pull(site: str) -> dict[str, Any]:
    uuid, key = _plainraw_cfg(site)
    if not uuid or not key:
        return {"configured": False}
    try:
        qs = urllib.parse.urlencode({"uuid": uuid, "editKey": key})
        req = urllib.request.Request(f"{PLAINRAW_API}/snippet?{qs}", method="GET",
                                     headers={"User-Agent": PLAINRAW_UA})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
        return {
            "configured": True,
            "content": data.get("content", ""),
            "updated_at": data.get("updatedAt", ""),
        }
    except Exception as e:
        return {"configured": True, "error": str(e)}


def _plainraw_push(site: str, content: str) -> dict[str, Any]:
    uuid, key = _plainraw_cfg(site)
    if not uuid or not key:
        return {"success": False, "error": f"No PlainRaw paste configured for '{site}'"}
    if len(content) > PLAINRAW_MAX:
        return {"success": False, "error": f"Content too large for PlainRaw (max {PLAINRAW_MAX} chars)"}
    try:
        body = json.dumps({"uuid": uuid, "editKey": key, "content": content}).encode()
        req = urllib.request.Request(
            f"{PLAINRAW_API}/update", data=body,
            headers={"Content-Type": "application/json", "User-Agent": PLAINRAW_UA},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode())
        return {"success": True, "updated_at": data.get("updatedAt", "")}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _format_duration(duration_s: int | None) -> str:
    if not duration_s or duration_s <= 0:
        return "?"
    h, rem = divmod(int(duration_s), 3600)
    m = rem // 60
    if h:
        return f"{h}h {m:02d}m" if m else f"{h}h"
    return f"{m} min" if m else f"{duration_s}s"


def _parse_m3u8_variants(master_url: str, cookies: str = "") -> dict[int, str]:
    from .ade_scraper import _get_session

    try:
        txt = _get_session(cookies or None).get(master_url, timeout=15).text
    except Exception:
        return {}
    variants: dict[int, str] = {}
    lines = txt.splitlines()
    for i, line in enumerate(lines):
        if "RESOLUTION=" in line:
            m = re.search(r"RESOLUTION=\d+x(\d+)", line)
            if m and i + 1 < len(lines):
                url = lines[i + 1].strip()
                if url and not url.startswith("#"):
                    variants[int(m.group(1))] = url
    return variants


def _pick_preferred(variants: dict[int, str]) -> list[tuple[int, str]]:
    picked = [(h, variants[h]) for h in (2160, 1080, 720, 480, 360, 240, 144) if h in variants]
    seen = {h for h, _ in picked}
    picked += [(h, variants[h]) for h in sorted(variants, reverse=True) if h not in seen]
    return picked


# ---------------------------------------------------------------------------
# Extraction (mirrors bot._blocking_m3u8 / _blocking_ade_m3u8 / do_info)
# ---------------------------------------------------------------------------

def _extract_aebn(url: str) -> dict[str, Any]:
    from .custom_session import CustomSession
    from .manifest_parser import Manifest
    from .movie_scraper import Movie

    session = CustomSession(impersonate="chrome")
    session.timeout = 30
    session.headers["User-Agent"] = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
    )
    for d in ("straight.aebn.com", "gay.aebn.com", "m.aebn.net", "vod.aebn.com"):
        session.cookies.set(name="ageGated", value="true", domain=d, path="/", secure=True)
    if DEFAULT_PROXY:
        session.proxies = {"all": DEFAULT_PROXY}

    movie = Movie(url, session)
    try:
        url_content_type = url.split("/")[3]
        movie_id = url.split("/")[5]
    except IndexError:
        raise ValueError("Could not parse AEBN movie id from URL")
    headers = {"content-type": "application/x-www-form-urlencoded"}
    data = f"movieId={movie_id}&isPreview=true&format=DASH"
    deliver_url = f"https://{url_content_type}.aebn.com/{url_content_type}/deliver"
    manifest_url = session.post(deliver_url, headers=headers, data=data).json()["url"]
    base_stream_url = manifest_url.rsplit("/", 1)[0]

    resolutions = None
    try:
        m = Manifest(url, movie.total_duration_seconds, session)
        m.base_stream_url = base_stream_url
        m.parse_content(session.get(manifest_url).content)
        resolutions = m.avaliable_resulutions
    except Exception as e:
        logger.warning("AEBN resolution probe failed: %s", e)

    return {
        "site": "AEBN",
        "studio": movie.studio_name,
        "title": movie.title,
        "movie_title": movie.title,
        "scene_title": "",
        "movie_id": movie_id,
        "scene_id": None,
        "duration_s": movie.total_duration_seconds,
        "duration": _format_duration(movie.total_duration_seconds),
        "manifest_url": manifest_url,
        "base_stream_url": base_stream_url,
        "resolutions": resolutions,
        "preferred_links": [],
        "covers": [c for c in (movie.cover_url_front, movie.cover_url_back) if c],
        "is_authorized": True,
    }


def _extract_ade(url: str, cookies: str) -> dict[str, Any]:
    from .ade_scraper import extract_ade_duration_seconds, get_ade_manifest

    result = get_ade_manifest(url, cookies_str=cookies or None)
    site = "EA" if "elegantangel.com" in url.lower() else "ADE"

    resolutions = sorted({s.get("source_height", 0) for s in result.get("streams", []) if s.get("source_height")})
    item_detail = result.get("item_detail", {})
    scene_id = result.get("scene_id")
    playlist_url = result.get("playlist_url", "")
    duration_s = result.get("duration_s", 0) or extract_ade_duration_seconds(item_detail, scene_id, playlist_url)

    preferred: list[tuple[int, str]] = []
    try:
        preferred = _pick_preferred(_parse_m3u8_variants(playlist_url, cookies))
    except Exception:
        pass

    covers = [c for c in (item_detail.get("front_cover"), item_detail.get("back_cover"), item_detail.get("poster")) if c]
    return {
        "site": site,
        "studio": html_unescape((item_detail.get("studio") or {}).get("name", "") if isinstance(item_detail.get("studio"), dict) else "Unknown"),
        "title": html_unescape(result.get("title", "")),
        "movie_title": html_unescape(result.get("movie_title") or result.get("title", "")),
        "scene_title": html_unescape(result.get("scene_title", "")),
        "movie_id": result.get("item_id"),
        "scene_id": scene_id,
        "duration_s": duration_s,
        "duration": _format_duration(duration_s),
        "manifest_url": playlist_url,
        "resolutions": resolutions,
        "preferred_links": [{"height": h, "url": u} for h, u in preferred],
        "covers": covers,
        "is_authorized": result.get("is_authorized", False),
        "ppm_remaining": result.get("ppm_time_remaining", result.get("ppm_remaining", 0)),
    }


def _info_aebn(url: str) -> dict[str, Any]:
    from .downloader import Downloader

    dl = Downloader(url=url, proxy=DEFAULT_PROXY or None,
                    proxy_metadata_only=bool(DEFAULT_PROXY),
                    show_progress=False, log_level="ERROR")
    dl._initialize_download()
    movie = dl._scrape_movie_info()
    dl._process_manifest(movie, requires_scene_boundaries=True)
    data = _extract_aebn(url)
    data.update({
        "performers": movie.performers or [],
        "scene_count": len(movie.scenes),
        "scenes": [
            {
                "n": i + 1,
                "performers": s.performers or [],
                "start_s": getattr(s, "start_timing", None),
                "end_s": getattr(s, "end_timing", None),
            }
            for i, s in enumerate(movie.scenes)
        ],
    })
    return data


def do_extract(url: str, mode: str, cookies_ade: str = "", cookies_ea: str = "", cookies_legacy: str = "") -> dict[str, Any]:
    from .ade_scraper import ADE_URL_RE

    url = (url or "").strip()
    if not url:
        raise ValueError("Missing URL")
    m = re.search(r"https?://\S+", url)
    if m:
        url = m.group(0).rstrip(")")
    host = urlparse(url).netloc.lower()
    site = "ea" if "elegantangel.com" in host else "ade"

    req_cookies = ((cookies_ea or "") if site == "ea" else (cookies_ade or "")) or (cookies_legacy or "")
    req_cookies = req_cookies.strip()
    effective_cookies = req_cookies or _load_site_cookies(site) or os.getenv("ADE_COOKIES", "")
    cookies_source = f"browser:{site}" if req_cookies else (f"server:{site}" if effective_cookies else "none")

    if ADE_URL_RE.search(url):
        data = _extract_ade(url, effective_cookies)
    elif "aebn.com" in host or "m.aebn.net" in host:
        data = _info_aebn(url) if mode == "info" else _extract_aebn(url)
    else:
        raise ValueError("Unsupported URL — paste an AEBN, AdultDVDEmpire or Elegant Angel link")
    data["cookies_source"] = cookies_source
    data["cookie_site"] = site
    data["source_url"] = url
    return data


def _account_info(cookies: str) -> dict[str, Any]:
    from .ade_scraper import _get_session

    session = _get_session(cookies or None)
    r = session.get("https://www.adultdvdempire.com/account/accounthomepage")
    r.raise_for_status()
    html = r.text
    email_m = re.search(r'text-success"></i>\s*([^<]+)', html)
    ppm_m = re.search(r'ppm-minutes__total-minutes">(\d+)', html)
    breakdown = re.findall(r"<dt>(Mins|Bonus Mins)</dt><dd>(\d+)</dd>", html)
    membership_m = re.search(r"membership-status.*?total-minutes\">(.*?)</p>", html, re.DOTALL)
    return {
        "email": email_m.group(1).strip() if email_m else "Unknown",
        "total_ppm": int(ppm_m.group(1)) if ppm_m else 0,
        "mins": next((int(v) for k, v in breakdown if k == "Mins"), 0),
        "bonus_mins": next((int(v) for k, v in breakdown if k == "Bonus Mins"), 0),
        "membership": membership_m.group(1).strip() if membership_m else "Unknown",
    }


# ---------------------------------------------------------------------------
# HTTP layer
# ---------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    server_version = "aebndl-web/1.0"

    def log_message(self, fmt, *args):
        logger.info("%s %s", self.address_string(), fmt % args)

    def _send_json(self, obj: Any, status: int = 200, headers: dict | None = None):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path, ctype: str):
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            length = 0
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            return {}

    def _require_auth(self) -> bool:
        if not _authed(self.headers):
            self._send_json({"error": "unauthorized"}, 401)
            return False
        return True

    # -- GET ---------------------------------------------------------------
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/health":
            body = b"OK"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(body)
            return

        if path == "/api/auth-check":
            if _authed(self.headers):
                self._send_json({"ok": True, "locked": not _is_open()})
            else:
                self._send_json({"error": "unauthorized"}, 401)
            return

        if path == "/api/cookies":
            if not self._require_auth():
                return
            out: dict[str, Any] = {}
            for site in ("ade", "ea"):
                saved = _load_site_cookies(site)
                info: dict[str, Any] = {"configured": bool(saved and "etoken" in saved)}
                if info["configured"]:
                    info["expiry"] = _cookie_expiry(saved)
                    if site == "ade":
                        try:
                            info["account"] = executor.submit(_account_info, saved).result(timeout=30)
                        except Exception as e:
                            info["account_error"] = str(e)
                puuid, _ = _plainraw_cfg(site)
                info["plainraw"] = bool(puuid)
                out[site] = info
            self._send_json(out)
            return

        if path == "/api/plainraw":
            if not self._require_auth():
                return
            qs = parse_qs(parsed.query or "")
            sites = qs.get("site", [])
            targets = [s for s in sites if s in ("ade", "ea")] or ["ade", "ea"]
            futs = {s: executor.submit(_plainraw_pull, s) for s in targets}
            self._send_json({s: f.result(timeout=30) for s, f in futs.items()})
            return

        if path in ("/", "/index.html", "/cookies"):
            if not _authed(self.headers):
                pass  # frontend shows the login view itself
            index = _frontend_index()
            if index is not None:
                self._send_file(index, "text/html; charset=utf-8")
            else:
                self._send_json({"error": "frontend not built — run `npm run build` in frontend/"}, 500)
            return

        if path.startswith("/assets/"):
            asset = (FRONTEND_DIST / path.lstrip("/")).resolve()
            if FRONTEND_DIST.resolve() in asset.parents and asset.is_file():
                self._send_file(asset, _ASSET_TYPES.get(asset.suffix.lower(), "application/octet-stream"))
            else:
                self._send_json({"error": "not found"}, 404)
            return

        self._send_json({"error": "not found"}, 404)

    # -- POST --------------------------------------------------------------
    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/login":
            body = self._read_json()
            if _is_open() or hmac.compare_digest(str(body.get("password", "")), WEB_PASSWORD):
                token = secrets.token_hex(16)
                _auth_tokens.add(token)
                self._send_json({"success": True}, headers={"Set-Cookie": f"wauth={token}; Path=/; HttpOnly; SameSite=Lax"})
            else:
                self._send_json({"error": "wrong password"}, 401)
            return

        if path == "/api/logout":
            cookie = self.headers.get("Cookie", "")
            m = re.search(r"wauth=([a-f0-9]+)", cookie)
            if m:
                _auth_tokens.discard(m.group(1))
            self._send_json({"success": True}, headers={"Set-Cookie": "wauth=; Path=/; Max-Age=0"})
            return

        if not self._require_auth():
            return

        if path == "/api/extract":
            body = self._read_json()
            try:
                data = executor.submit(
                    do_extract,
                    str(body.get("url", "")),
                    str(body.get("mode", "manifest")),
                    str(body.get("cookies_ade", "") or ""),
                    str(body.get("cookies_ea", "") or ""),
                    str(body.get("cookies", "") or ""),
                ).result(timeout=600)
                self._send_json({"success": True, "data": data})
            except Exception as e:
                logger.warning("extract failed: %s", e)
                self._send_json({"success": False, "error": str(e)}, 200)
            return

        if path == "/api/cookies":
            body = self._read_json()
            site = str(body.get("site", "") or "").lower()
            if site not in ("ade", "ea"):
                self._send_json({"success": False, "error": "Missing site — use 'ade' or 'ea'"}, 200)
                return
            cookie_text = str(body.get("cookies", "") or "")
            if "etoken" not in cookie_text:
                self._send_json({"success": False, "error": "No etoken found — paste the full Netscape cookie export"}, 200)
                return
            _save_site_cookies(site, cookie_text)
            self._send_json({"success": True, "site": site, "expiry": _cookie_expiry(cookie_text)})
            return

        if path == "/api/plainraw":
            body = self._read_json()
            site = str(body.get("site", "") or "").lower()
            content = str(body.get("content", "") or "")
            if site not in ("ade", "ea"):
                self._send_json({"success": False, "error": "Missing site — use 'ade' or 'ea'"}, 200)
                return
            if "etoken" not in content:
                self._send_json({"success": False, "error": "No etoken found — refusing to push"}, 200)
                return
            result = executor.submit(_plainraw_push, site, content).result(timeout=30)
            self._send_json(result)
            return

        self._send_json({"error": "not found"}, 404)

    # -- DELETE ------------------------------------------------------------
    def do_DELETE(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/cookies":
            if not self._require_auth():
                return
            qs = parse_qs(parsed.query or "")
            site = (qs.get("site", [""])[0] or "").lower()
            if site not in ("ade", "ea", "", "both"):
                self._send_json({"error": "site must be 'ade' or 'ea'"}, 400)
                return
            targets = ("ade", "ea") if site in ("", "both") else (site,)
            for t in targets:
                _save_site_cookies(t, "")
            self._send_json({"success": True, "cleared": list(targets)})
            return
        self._send_json({"error": "not found"}, 404)


def create_server(port: int) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    logger.info("Web UI listening on port %s", port)
    return server


def run_blocking(port: int) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s|%(levelname)s|%(message)s", datefmt="%H:%M:%S")
    create_server(port).serve_forever()


def start_in_background(port: int) -> ThreadingHTTPServer:
    """Serve the web UI in a daemon thread (used by the Telegram bot entrypoint)."""
    import threading

    server = create_server(port)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def main():
    port = int(os.getenv("PORT", "8000"))
    print(f"Starting aebndl web UI on :{port}")
    run_blocking(port)


if __name__ == "__main__":
    main()
