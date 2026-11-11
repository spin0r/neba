"""Cookie parsing and HTTP session creation for ADE."""
from __future__ import annotations

import logging
import os

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


def parse_ade_cookies(cookie_str: str) -> dict[str, str]:
    """Parse ADE cookies from various formats into a dict."""
    cookies: dict[str, str] = {}
    if not cookie_str:
        return cookies

    cookie_str = cookie_str.strip()

    # Netscape format
    if "\t" in cookie_str or "\n" in cookie_str:
        for line in cookie_str.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) >= 7:
                name = parts[5].strip()
                val = parts[6].strip()
                if name:
                    cookies[name] = val
        if cookies:
            return cookies

    # Simple name=value; format
    for item in cookie_str.split(";"):
        item = item.strip()
        if "=" in item:
            name, val = item.split("=", 1)
            name = name.strip()
            val = val.strip()
            if name:
                cookies[name] = val

    return cookies


def get_session(cookies_str: str | None = None) -> CustomSession:
    """Create a configured CustomSession for ADE requests."""
    session = CustomSession()

    parsed = parse_ade_cookies(cookies_str or "")
    if not parsed:
        env_cookies = os.getenv("ADE_COOKIES", "")
        if env_cookies:
            parsed = parse_ade_cookies(env_cookies)

    for k, v in parsed.items():
        session.cookies.set(k, v)

    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/128.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    })
    return session
