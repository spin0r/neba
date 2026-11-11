"""Site detection, cookie validation hints, and error messaging."""
from __future__ import annotations

from html import unescape as html_unescape
import logging
import re
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


def page_title(html: str) -> str:
    """Extract <title> from HTML for error context."""
    m = re.search(r"<title[^>]*>(.*?)</title>", html or "", re.S | re.I)
    return re.sub(r"\s+", " ", html_unescape(m.group(1))).strip()[:90] if m else ""


def no_player_cause(html: str, final_url: str) -> str:
    """Explain why a fetched page carried no player init params."""
    low = (html or "").lower()

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
    if any(m in low for m in ("are you 18", "age verification", "agegate", "verify your age", "age-confirmation")):
        return "the site is asking for age verification — the cookies are missing"

    title = page_title(html)
    return f"the page came back with no video player (page title: '{title}')" if title \
        else "the page came back empty, with no video player"


def cookie_hint(cookies_str: str | None, site: str, box: str) -> str:
    if not cookies_str:
        return f"no cookies were supplied — paste your {site} session in the Cookies page, box '{box}'"
    if not re.search(r"\betoken\b", cookies_str):
        return f"the cookies in use contain no etoken — paste a fresh {site} session in the Cookies page, box '{box}'"
    return f"the session was refused, so the etoken is likely expired — refresh your {site} session in the Cookies page, box '{box}'"


def upper_first(s: str) -> str:
    return s[0].upper() + s[1:] if s else s


def site_for_url(url: str) -> tuple[str, str]:
    host = urlparse(url or "").netloc.lower()
    if "elegantangel" in host:
        return ("Elegant Angel", "ea")
    if "dvderotik" in host:
        return ("DVDErotik", "dvd")
    return ("AdultDVDEmpire", "ade")


def auth_error(cookies_str: str | None, final_url: str = "") -> ValueError:
    site, box = site_for_url(final_url)
    logger.warning(
        "Not authorized for %s (final_url=%s, cookies=%d bytes)",
        site, final_url or "?", len(cookies_str or ""),
    )
    return ValueError(f"{site}: not authorized to stream this content. {upper_first(cookie_hint(cookies_str, site, box))}.")


def no_player_error(
    html: str,
    final_url: str,
    cookies_str: str | None,
    site: str | None = None,
    box: str | None = None,
) -> ValueError:
    """Build an actionable error for a page without player params."""
    if site is None or box is None:
        detected_site, detected_box = site_for_url(final_url)
        site = site or detected_site
        box = box or detected_box

    cause = no_player_cause(html, final_url)
    logger.warning(
        "No player params: %s | final_url=%s | bytes=%d | title=%r",
        cause, final_url, len(html or ""), page_title(html or ""),
    )
    return ValueError(f"{site}: {cause}. {upper_first(cookie_hint(cookies_str, site, box))}.")
