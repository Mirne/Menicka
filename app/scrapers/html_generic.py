"""Generic parser for ordinary restaurant websites.

Strategy, in order:
1. If a CSS selector is configured for the restaurant, use only that part.
2. If the page lists the week day by day (Pondělí, Úterý, ...), take today's block.
3. Otherwise take the block after a "Denní menu / Polední menu / Lunch" heading.
4. Otherwise fall back to every line on the page that carries a price.
Lines with a price become dishes; short known headings (Polévka, Hlavní jídla...) start sections.
"""
from __future__ import annotations

import re
from datetime import date
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .base import (
    MenuItem,
    MenuResult,
    MenuSection,
    clean_space,
    find_price,
    looks_daily,
    strip_accents,
    weekday_of,
)

BLOCK_TAGS = "p div li tr td th h1 h2 h3 h4 h5 h6 br section article table dt dd span".split()
MAX_BLOCK_LINES = 60
HEADING_RE = re.compile(
    r"^(polevk|polievk|soup|hlavni|main|predkrm|predjed|starter|dezert|dessert|salat|salad|"
    r"napoj|drink|vegetarian|vegan|pizza|burger|tip|special|specialit|menu\b|denni|poledni|"
    r"obedov|lunch|tydenni|tyzdenn|weekly)"
)
ALLERGEN_ONLY = re.compile(r"^[\s(\[]*(a(lergen[yi]?)?[:\s]*)?[\d\s,.;]+[)\]]*$", re.IGNORECASE)
MENU_LINK_RE = re.compile(r"denn|poledn|obed|lunch|menu|jidelni|jedalny", re.IGNORECASE)


def page_lines(soup: BeautifulSoup) -> list[str]:
    for t in soup(["script", "style", "noscript", "template", "svg", "iframe", "nav"]):
        t.decompose()
    for t in soup.find_all(BLOCK_TAGS):
        t.insert_before("\n")
        t.insert_after("\n")
    text = soup.get_text()
    lines = [clean_space(x) for x in text.split("\n")]
    return [x for x in lines if x]


def today_block(lines: list[str], today: date) -> list[str] | None:
    heads = [(i, weekday_of(l)) for i, l in enumerate(lines) if len(l) <= 60 and weekday_of(l) is not None]
    if len({wd for _, wd in heads}) < 2:  # need a real day-by-day listing
        return None
    for n, (i, wd) in enumerate(heads):
        if wd == today.weekday():
            if n + 1 < len(heads):
                return lines[i: heads[n + 1][0]]
            return trim_tail(lines[i: i + MAX_BLOCK_LINES])
    return []  # day-by-day listing, but nothing for today (e.g. weekend)


def daily_heading_block(lines: list[str]) -> list[str] | None:
    for i, l in enumerate(lines):
        if len(l) <= 60 and looks_daily(l) and find_price(l)[0] is None:
            block, misses, seen_price = [l], 0, False
            for nxt in lines[i + 1: i + 1 + MAX_BLOCK_LINES]:
                has_price = find_price(nxt)[0] is not None
                seen_price |= has_price
                misses = 0 if has_price else misses + 1
                if seen_price and misses >= 6:
                    break
                block.append(nxt)
            if seen_price:
                return trim_tail(block)
    return None


def trim_tail(block: list[str]) -> list[str]:
    """Cut contact/footer lines that follow the last dish with a price."""
    last = max((i for i, l in enumerate(block) if find_price(l)[0] is not None), default=len(block) - 1)
    return block[: last + 1]


def lines_to_sections(lines: list[str], default_name: str) -> list[MenuSection]:
    sections: list[MenuSection] = []
    current = MenuSection(name=default_name)
    pending: MenuItem | None = None  # a dish name waiting for a price on the next line

    def flush_pending() -> None:
        nonlocal pending
        if pending is not None:
            current.items.append(pending)
            pending = None

    for raw in lines:
        price, rest = find_price(raw)
        norm = strip_accents(raw)
        if price is None and len(raw) <= 40 and (HEADING_RE.match(norm) or raw.endswith(":")):
            flush_pending()
            if current.items:
                sections.append(current)
            current = MenuSection(name=raw.rstrip(":").strip())
            continue
        if ALLERGEN_ONLY.match(raw):
            continue
        if price is not None:
            if rest:
                flush_pending()
                current.items.append(MenuItem(name=rest, price=price))
            elif pending is not None:
                pending.price = price
                flush_pending()
            elif current.items and current.items[-1].price is None:
                current.items[-1].price = price
            continue
        # Line without price: a dish whose price follows, or a description.
        if pending is not None:
            if len(pending.name) < 120:
                current.items.append(pending)
            pending = None
        if len(raw) >= 3 and len(raw) <= 200:
            pending = MenuItem(name=raw)
    flush_pending()
    if current.items:
        sections.append(current)
    # Drop sections that are only priceless text lines (navigation, contact info...)
    return [s for s in sections if any(i.price is not None for i in s.items) or len(s.items) <= 8]


def menu_links(soup: BeautifulSoup, base_url: str) -> list[str]:
    host = urlparse(base_url).netloc
    out: list[str] = []
    for a in soup.find_all("a", href=True):
        href = urljoin(base_url, a["href"])
        label = clean_space(a.get_text()) + " " + href
        if not MENU_LINK_RE.search(strip_accents(label)):
            continue
        is_file = re.search(r"\.(pdf|jpe?g|png|webp)(\?|$)", href, re.IGNORECASE)
        if urlparse(href).netloc == host or is_file:
            if href.split("#")[0] != base_url.split("#")[0] and href not in out:
                out.append(href)
    return out[:8]


def parse_html(html: str, url: str, selector: str | None = None, today: date | None = None) -> MenuResult:
    today = today or date.today()
    soup = BeautifulSoup(html, "lxml")
    links = menu_links(soup, url)
    root = soup
    if selector:
        picked = soup.select(selector)
        if not picked:
            return MenuResult(source_url=url, links=links, error=f"Selektor '{selector}' na stránke nič nenašiel.")
        root = BeautifulSoup("".join(str(p) for p in picked), "lxml")
    lines = page_lines(root)

    if selector:
        block, title, daily = lines, "Denné menu", True
    else:
        block = today_block(lines, today)
        title, daily = "Denné menu", True
        if block == []:
            return MenuResult(source_url=url, links=links, error="Na dnešný deň stránka menu neuvádza.")
        if block:
            title = block[0]
            block = block[1:]
        else:
            block = daily_heading_block(lines)
            if block:
                title, block = block[0], block[1:]
            else:
                block = [l for l in lines if find_price(l)[0] is not None]
                title, daily = "Položky s cenou nájdené na stránke", False

    sections = lines_to_sections(block, title)
    for s in sections:
        s.is_daily = daily
    if not any(s.items for s in sections):
        return MenuResult(source_url=url, links=links, error="Na stránke som nenašiel menu.")
    return MenuResult(sections=sections, source_url=url, links=links)
