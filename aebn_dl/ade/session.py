"""Cookie parsing and HTTP session creation for ADE, Elegant Angel, and DVDErotik."""
from __future__ import annotations

import logging
import os
import re

try:
    from ..custom_session import CustomSession
except ImportError:
    from aebn_dl.custom_session import CustomSession  # type: ignore

try:
    from dotenv import load_dotenv

    load_dotenv()
    load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"), override=False)
    load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", "..", ".env"), override=False)
except ImportError:
    pass

logger = logging.getLogger(__name__)

DOMAINS = (
    ".adultdvdempire.com",
    ".adultempire.com",
    ".elegantangel.com",
    ".dvderotik.com",
    "dvderotik.com",
    "us.dvderotik.com",
    "www.dvderotik.com",
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
            name = parts[5].strip()
            value = parts[6].strip()
            if name:
                cookies[name] = value
            continue
        # Try 2+ spaces (Discord/chat may convert tabs to spaces)
        parts = re.split(r"\s{2,}", line)
        if len(parts) >= 7:
            name = parts[5].strip()
            value = parts[6].strip()
            if name:
                cookies[name] = value
            continue
        # Fallback: key=value format
        if "=" in line:
            for pair in line.split(";"):
                pair = pair.strip()
                if "=" in pair:
                    k, v = pair.split("=", 1)
                    k = k.strip()
                    v = v.strip()
                    if k:
                        cookies[k] = v

    return cookies


def get_session(cookies_str: str | None = None) -> CustomSession:
    """Create a configured CustomSession for ADE / EA / DVDErotik requests."""
    session = CustomSession(impersonate="chrome")
    session.timeout = 30
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    })

    # Always set age verification cookies for all Empire network domains
    for domain in DOMAINS:
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

    # Load user-provided cookies (etoken, etc.) across all supported domains
    if cookies_str:
        user_cookies = parse_ade_cookies(cookies_str)
        for name, value in user_cookies.items():
            for domain in DOMAINS:
                session.cookies.set(name, value, domain=domain, path="/")

    return session
