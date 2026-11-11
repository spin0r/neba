"""Site detection, cookie validation hints, and error messaging."""
from __future__ import annotations

from urllib.parse import urlparse


def page_title(html: str) -> str:
    """Extract <title> from HTML for error context."""
    import re
    m = re.search(r"<title[^>]*>([^<]+)</title>", html, re.IGNORECASE)
    return m.group(1).strip() if m else ""


def site_for_url(url: str) -> tuple[str, str]:
    """Return (Site Name, input box identifier) based on URL host."""
    host = urlparse(url).netloc.lower()
    if "elegantangel.com" in host:
        return "Elegant Angel", "cookies_ea"
    if "dvderotik.com" in host:
        return "DVDErotik", "cookies_dvd"
    return "Adult Empire", "cookies"


def upper_first(s: str) -> str:
    return s[:1].upper() + s[1:] if s else ""


def cookie_hint(cookies_str: str | None, site: str, box: str) -> str:
    if cookies_str:
        return f"Current {site} cookies may be expired or invalid for this title (check the '{upper_first(box)}' box)."
    return f"Please set {site} cookies in the '{upper_first(box)}' box to access this content."


def no_player_cause(html: str, final_url: str) -> str:
    """Inspect the page for typical signs of why the player is missing."""
    hlow = html.lower()
    if "sign in" in hlow or "log in" in hlow or "login" in hlow:
        if "membership" in hlow or "join" in hlow or "subscribe" in hlow:
            return "page requires member/subscriber login"
        return "page shows a login prompt"
    if "404" in hlow or "not found" in hlow:
        return "item not found (404)"
    if "purchase" in hlow or "buy scene" in hlow or "buy movie" in hlow:
        return "title must be purchased / not owned by this account"
    title = page_title(html)
    if title:
        return f"page title: {title!r}"
    return "page structure changed or content is gated"


def auth_error(cookies_str: str | None, final_url: str = "") -> ValueError:
    site, box = site_for_url(final_url) if final_url else ("Adult Empire", "cookies")
    hint = cookie_hint(cookies_str, site, box)
    return ValueError(f"Redirected to login while fetching ADE page. {hint}")


def no_player_error(html: str, final_url: str, cookies_str: str | None) -> ValueError:
    site, box = site_for_url(final_url)
    hint = cookie_hint(cookies_str, site, box)
    cause = no_player_cause(html, final_url)
    title = page_title(html)
    detail_parts: list[str] = [cause]
    if title and cause != f"page title: {title!r}":
        detail_parts.append(f"title: {title!r}")
    detail = f" ({', '.join(detail_parts)})" if detail_parts else ""
    return ValueError(
        f"Could not find video player parameters on the page{detail}. "
        f"The title may require an active member subscription or individual purchase. {hint}"
    )
