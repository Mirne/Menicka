"""Fetch a restaurant page and pick the right parser. Only today's daily menu is returned."""
from __future__ import annotations

import logging
from datetime import date

import httpx

from .base import MenuResult
from .choiceqr import is_choiceqr, parse_choiceqr
from .html_generic import parse_html

log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "cs,sk;q=0.9,en;q=0.8",
}

KINDS = ("auto", "choiceqr", "html")
FILE_EXT = (".pdf", ".jpg", ".jpeg", ".png", ".webp")


def detect_kind(url: str) -> str:
    return "choiceqr" if is_choiceqr(url) else "html"


def new_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(headers=HEADERS, timeout=20, follow_redirects=True)


async def fetch_html(url: str, client: httpx.AsyncClient | None = None) -> str:
    own = client is None
    client = client or new_client()
    try:
        r = await client.get(url)
        r.raise_for_status()
        return r.text
    finally:
        if own:
            await client.aclose()


def only_daily(result: MenuResult) -> MenuResult:
    """Drop everything except today's daily menu."""
    if result.error or not result.sections:
        return result
    result.found_sections = [s.name for s in result.sections]
    result.sections = [s for s in result.sections if s.is_daily and s.items]
    if not result.sections:
        result.error = "Denné menu som nerozoznal."
    return result


async def _parse(client: httpx.AsyncClient, url: str, kind: str, selector: str | None,
                 today: date | None, pattern: str | None) -> MenuResult:
    html = await fetch_html(url, client)
    if kind == "choiceqr":
        result = only_daily(parse_choiceqr(html, url, today, pattern))
        if result.error and not result.found_sections:  # page changed shape: try the visible text
            fallback = parse_html(html, url, selector, today, pattern)
            if not fallback.error:
                return fallback
        return result
    return only_daily(parse_html(html, url, selector, today, pattern))


async def fetch_menu(url: str, kind: str = "auto", selector: str | None = None,
                     today: date | None = None, client: httpx.AsyncClient | None = None,
                     daily_section: str | None = None) -> MenuResult:
    kind = detect_kind(url) if kind in (None, "", "auto") else kind
    own = client is None
    client = client or new_client()
    try:
        result = await _parse(client, url, kind, selector, today, daily_section)
        # The menu often lives in an embedded iframe or on a "Denní menu" subpage: follow one hop.
        if result.error and not result.found_sections:
            for link in result.links:
                if link.lower().split("?")[0].endswith(FILE_EXT):
                    continue
                sub_kind = detect_kind(link)
                try:
                    sub = await _parse(client, link, sub_kind, None, today, daily_section)
                except httpx.HTTPError:
                    continue
                if not sub.error:
                    sub.links = result.links
                    sub.images = sub.images or result.images
                    return sub
        return result
    except httpx.HTTPError as e:
        log.warning("fetch %s failed: %s", url, e)
        return MenuResult(source_url=url, error=f"Stránku sa nepodarilo načítať: {type(e).__name__}: {e}")
    except Exception as e:  # a parser bug must not take down the whole page
        log.exception("parse %s failed", url)
        return MenuResult(source_url=url, error=f"Chyba pri spracovaní menu: {e}")
    finally:
        if own:
            await client.aclose()
