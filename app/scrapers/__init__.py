"""Fetch a restaurant page and pick the right parser."""
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


def detect_kind(url: str) -> str:
    return "choiceqr" if is_choiceqr(url) else "html"


async def _get(client: httpx.AsyncClient, url: str) -> str:
    r = await client.get(url)
    r.raise_for_status()
    return r.text


async def fetch_menu(url: str, kind: str = "auto", selector: str | None = None,
                     today: date | None = None, client: httpx.AsyncClient | None = None) -> MenuResult:
    kind = detect_kind(url) if kind in (None, "", "auto") else kind
    own = client is None
    client = client or httpx.AsyncClient(headers=HEADERS, timeout=20, follow_redirects=True)
    try:
        html = await _get(client, url)
        if kind == "choiceqr":
            result = parse_choiceqr(html, url, today)
            if result.error:  # page changed shape: still try the visible text
                fallback = parse_html(html, url, selector, today)
                if not fallback.error:
                    return fallback
            return result

        result = parse_html(html, url, selector, today)
        # Menu often lives on a subpage ("Denní menu"): follow one HTML link.
        if result.error and not selector:
            for link in result.links:
                if link.lower().split("?")[0].endswith((".pdf", ".jpg", ".jpeg", ".png", ".webp")):
                    continue
                try:
                    sub = parse_html(await _get(client, link), link, None, today)
                except httpx.HTTPError:
                    continue
                if not sub.error:
                    sub.links = result.links
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
