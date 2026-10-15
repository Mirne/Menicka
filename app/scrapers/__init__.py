"""Fetch a restaurant page and pick the right parser. Only today's daily menu is returned."""
from __future__ import annotations

import asyncio
import logging
from datetime import date

import httpx

from .base import MenuResult
from .choiceqr import is_choiceqr, parse_choiceqr
from . import ocr
from .html_generic import NotFound, parse_html, sections_from_lines

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
        if result.other_menus:
            result.error += " Na stránke je aj: " + ", ".join(result.other_menus) + "."
    return result


async def _parse(client: httpx.AsyncClient, url: str, kind: str, selector: str | None,
                 today: date | None, pattern: str | None, daily_page: bool = False) -> MenuResult:
    html = await fetch_html(url, client)
    if kind == "choiceqr":
        result = only_daily(parse_choiceqr(html, url, today, pattern))
        if result.error and not result.found_sections:  # page changed shape: try the visible text
            fallback = parse_html(html, url, selector, today, pattern, daily_page)
            if not fallback.error:
                return fallback
        return result
    return only_daily(parse_html(html, url, selector, today, pattern, daily_page))


MAX_IMAGE_BYTES = 15 * 1024 * 1024


async def read_images(client: httpx.AsyncClient, failed: MenuResult, today: date | None,
                      pattern: str | None) -> MenuResult | None:
    """OCR the menu pictures of a page and keep today's part. None if OCR is not available."""
    if not failed.images or not ocr.available():
        return None
    reason = None
    for src in failed.images[:4]:
        try:
            r = await client.get(src)
            r.raise_for_status()
        except httpx.HTTPError:
            continue
        if len(r.content) > MAX_IMAGE_BYTES:
            continue
        lines = await asyncio.to_thread(ocr.lines_from_image, r.content)
        try:
            sections = sections_from_lines(lines, today or date.today(), pattern, relaxed=True)
        except NotFound as e:
            # A picture with no menu at all (a promo poster) says nothing; a stale week does.
            if "týždeň" in str(e) or "dnešný" in str(e):
                reason = reason or str(e)
            continue
        return MenuResult(sections=sections, source_url=failed.source_url, images=[src],
                          links=failed.links, from_image=True)
    return MenuResult(source_url=failed.source_url, images=failed.images, links=failed.links,
                      error=reason or "Na obrázkoch som denné menu neprečítal.")


async def fetch_menu(url: str, kind: str = "auto", selector: str | None = None,
                     today: date | None = None, client: httpx.AsyncClient | None = None,
                     daily_section: str | None = None) -> MenuResult:
    kind = detect_kind(url) if kind in (None, "", "auto") else kind
    own = client is None
    client = client or new_client()
    try:
        result = await _parse(client, url, kind, selector, today, daily_section)
        # The menu often lives on a "Denní menu" subpage, in an iframe, or (ChoiceQR) in
        # another menu of the same venue: follow one hop.
        if not result.error:
            return result
        best_failure: MenuResult | None = None
        for link in result.links[:6]:
            if link.lower().split("?")[0].endswith(FILE_EXT):
                continue
            is_daily = link in result.daily_links
            try:
                sub = await _parse(client, link, detect_kind(link), None, today, daily_section, is_daily)
            except httpx.HTTPError:
                continue
            if not sub.error:
                sub.links = list(dict.fromkeys(sub.links + result.links))
                sub.images = sub.images or result.images
                return sub
            if is_daily and best_failure is None:
                best_failure = sub
        if best_failure is not None:
            # The daily-menu page exists but could not be read: its own error and images say more.
            best_failure.images = best_failure.images or result.images
            best_failure.links = list(dict.fromkeys(result.links + best_failure.links))
            best_failure.found_sections = best_failure.found_sections or result.found_sections
            result = best_failure
        # The menu may be a picture (often the whole week in one image): read it.
        return await read_images(client, result, today, daily_section) or result
    except httpx.HTTPError as e:
        log.warning("fetch %s failed: %s", url, e)
        return MenuResult(source_url=url, error=f"Stránku sa nepodarilo načítať: {type(e).__name__}: {e}")
    except Exception as e:  # a parser bug must not take down the whole page
        log.exception("parse %s failed", url)
        return MenuResult(source_url=url, error=f"Chyba pri spracovaní menu: {e}")
    finally:
        if own:
            await client.aclose()
