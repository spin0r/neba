"""Utility functions for ADE scraping."""
from __future__ import annotations

from .constants import ADE_URL_RE


def extract_ade_url(text: str) -> str | None:
    """Extract an ADE URL from text."""
    m = ADE_URL_RE.search(text)
    return m.group(0).rstrip(")") if m else None
