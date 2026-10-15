"""Fetch a restaurant page and pick the right parser. Only today's daily menu is returned."""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import date
from urllib.parse import urldefrag

import httpx

from . import ocr
from . import messages as msg
from .base import MenuResult, day_heading
from .choiceqr import is_choiceqr, parse_choiceqr
from .html_generic import NotFound, daily_document, parse_html, sections_from_lines
from .pdf import lines_from_pdf

log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "cs,sk;q=0.9,en;q=0.8",
}

KINDS = ("auto", "choiceqr", "html")
IMAGE_EXT = (".jpg", ".jpeg", ".png", ".webp")
MAX_FILE_BYTES = 15 * 1024 * 1024


@dataclass
class Options:
    """Per-restaurant settings that every parser needs."""
    today: date = field(default_factory=date.today)
    selector: str | None = None
    daily_section: str | None = None
    also: list[str] = field(default_factory=list)


def parse_also(value) -> list[str]:
    """`also` from yaml (list or "a, b") or the database ("a, b")."""
    if not value:
        return []
    items = value if isinstance(value, list) else str(value).split(",")
    return [str(x).strip() for x in items if str(x).strip()]


def detect_kind(url: str) -> str:
    return "choiceqr" if is_choiceqr(url) else "html"


def new_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(headers=HEADERS, timeout=30, follow_redirects=True)


async def _get(client: httpx.AsyncClient, url: str) -> httpx.Response:
    r = await client.get(urldefrag(url).url)  # "#lunch-menu" is for the parser, not the server
    r.raise_for_status()
    return r


async def fetch_html(url: str, client: httpx.AsyncClient | None = None) -> str:
    own = client is None
    client = client or new_client()
    try:
        return (await _get(client, url)).text
    finally:
        if own:
            await client.aclose()


def _is_pdf(url: str, r: httpx.Response) -> bool:
    return "pdf" in r.headers.get("content-type", "") or url.lower().split("?")[0].endswith(".pdf") \
        or r.content[:5] == b"%PDF-"


def _is_image(url: str, r: httpx.Response) -> bool:
    return r.headers.get("content-type", "").startswith("image/") or url.lower().split("?")[0].endswith(IMAGE_EXT)


def drop_day_titles(result: MenuResult, today: date) -> MenuResult:
    """Section titles like "Čtvrtek", "Čt 15.10." or "Čtvrtek/ Thursday" repeat the date
    already shown in the page header, so they are left empty."""
    for sec in result.sections:
        if sec.name and day_heading(sec.name, today) is not None:
            sec.name = ""
    return result


def only_daily(result: MenuResult) -> MenuResult:
    """Drop everything except today's daily menu."""
    if result.error or not result.sections:
        return result
    result.found_sections = [s.name for s in result.sections]
    result.sections = [s for s in result.sections if s.is_daily and s.items]
    if not result.sections:
        result.error = msg.not_recognized(result.other_menus)
    return result


def parse_file_lines(lines: list[str], url: str, opts: Options, from_image: bool) -> MenuResult:
    """A PDF or a picture: the whole document is the (daily or weekly) menu."""
    try:
        sections = daily_document(lines, opts.today, opts.daily_section, opts.also)
    except NotFound as e:
        error = str(e)
        if error == msg.NO_DAILY_MENU:
            error = msg.NO_DAILY_IN_DOCUMENT if lines else msg.DOCUMENT_UNREADABLE
        return MenuResult(source_url=url, error=error, from_image=from_image)
    return MenuResult(sections=sections, source_url=url, from_image=from_image)


async def _parse(client: httpx.AsyncClient, url: str, kind: str, opts: Options,
                 daily_page: bool = False) -> MenuResult:
    r = await _get(client, url)
    if len(r.content) <= MAX_FILE_BYTES and _is_pdf(url, r):
        lines, used_ocr = await asyncio.to_thread(lines_from_pdf, r.content)
        return parse_file_lines(lines, url, opts, used_ocr)
    if len(r.content) <= MAX_FILE_BYTES and _is_image(url, r):
        if not ocr.available():
            return MenuResult(source_url=url, images=[url], error=msg.MENU_IS_PICTURE)
        lines = await asyncio.to_thread(ocr.lines_from_image, r.content)
        result = parse_file_lines(lines, url, opts, True)
        result.images = [url]
        return result
    html = r.text
    if kind == "choiceqr":
        result = only_daily(parse_choiceqr(html, url, opts.today, opts.daily_section))
        if result.error and not result.found_sections:  # page changed shape: try the visible text
            fallback = parse_html(html, url, opts.selector, opts.today, opts.daily_section, daily_page, opts.also)
            if not fallback.error:
                return fallback
        return result
    return only_daily(parse_html(html, url, opts.selector, opts.today, opts.daily_section, daily_page, opts.also))


async def read_images(client: httpx.AsyncClient, failed: MenuResult, opts: Options) -> MenuResult | None:
    """OCR the menu pictures of a page and keep today's part. None if OCR is not available."""
    if not failed.images or not ocr.available():
        return None
    reason = None
    for src in failed.images[:4]:
        try:
            r = await _get(client, src)
        except httpx.HTTPError:
            continue
        if len(r.content) > MAX_FILE_BYTES:
            continue
        lines = await asyncio.to_thread(ocr.lines_from_image, r.content)
        try:
            sections = sections_from_lines(lines, opts.today, opts.daily_section, True, opts.also)
        except NotFound as e:
            # A picture with no menu at all (a promo poster) says nothing; a stale week does.
            if str(e) not in (msg.NO_DAILY_MENU,):
                reason = reason or str(e)
            continue
        return MenuResult(sections=sections, source_url=failed.source_url, images=[src],
                          links=failed.links, from_image=True)
    return MenuResult(source_url=failed.source_url, images=failed.images, links=failed.links,
                      error=reason or msg.PICTURES_UNREADABLE)


async def fetch_menu(url: str, kind: str = "auto", selector: str | None = None,
                     today: date | None = None, client: httpx.AsyncClient | None = None,
                     daily_section: str | None = None, also=None) -> MenuResult:
    kind = detect_kind(url) if kind in (None, "", "auto") else kind
    opts = Options(today=today or date.today(), selector=selector, daily_section=daily_section,
                   also=parse_also(also))
    own = client is None
    client = client or new_client()
    try:
        result = await _parse(client, url, kind, opts)
        # The menu often lives on a "Denní menu" subpage or PDF, in an iframe, or (ChoiceQR)
        # in another menu of the same venue: follow one hop.
        if not result.error:
            return result
        best_failure: MenuResult | None = None
        sub_opts = Options(today=opts.today, daily_section=opts.daily_section, also=opts.also)
        for link in result.links[:6]:
            if re.search(r"\.(jpe?g|png|webp)(\?|$)", link, re.IGNORECASE):
                continue  # pictures are read below
            is_daily = link in result.daily_links
            try:
                sub = await _parse(client, link, detect_kind(link), sub_opts, is_daily)
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
        return await read_images(client, result, opts) or result
    except httpx.HTTPError as e:
        log.warning("fetch %s failed: %s", url, e)
        return MenuResult(source_url=url, error=msg.load_failed(f"{type(e).__name__}: {e}"))
    except Exception as e:  # a parser bug must not take down the whole page
        log.exception("parse %s failed", url)
        return MenuResult(source_url=url, error=msg.parse_failed(str(e)))
    finally:
        if own:
            await client.aclose()
