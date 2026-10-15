"""Generic parser for ordinary restaurant websites.

Strategy, in order:
1. If a CSS selector is configured for the restaurant, use only that part.
2. If the page lists the week day by day (Pondělí / Čt 15.10. / 15.10.), take today's block.
3. Otherwise take the block after a "Denní menu / Polední menu / Lunch" heading.
4. On a page that is itself the daily menu (reached through a "Denní menu" link, or its
   URL says so), take the page's main text.
5. Otherwise report that no daily menu was found (the rest of the menu is not wanted).
Lines with a price become dishes; short known headings (Polévka, Hlavní jídla...) start sections.
On daily-menu pages a bare number at the end of a line also counts as a price.
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
    day_heading,
    find_price,
    looks_daily,
    strip_accents,
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
DAILY_URL_RE = re.compile(r"denn|poledn|obed|lunch|daily|tydenn|weekly|menu-dne|hotovk", re.IGNORECASE)
CHROME_TAGS = ["header", "footer", "aside", "form"]


def is_daily_url(url: str, label: str = "") -> bool:
    return bool(DAILY_URL_RE.search(strip_accents(url + " " + label)))


def page_lines(soup: BeautifulSoup) -> list[str]:
    for t in soup(["script", "style", "noscript", "template", "svg", "iframe", "nav"]):
        t.decompose()
    for t in soup.find_all(BLOCK_TAGS):
        t.insert_before("\n")
        t.insert_after("\n")
    text = soup.get_text()
    lines = [clean_space(x) for x in text.split("\n")]
    return [x for x in lines if x]


def today_block(lines: list[str], today: date, relaxed: bool = False) -> list[str] | None:
    heads = []
    for i, l in enumerate(lines):
        h = day_heading(l, today)
        if h is not None and find_price(l)[0] is None:
            heads.append((i, h))
    if len({key for _, (key, _) in heads}) < 2:  # need a real day-by-day listing
        return None
    for n, (i, (_, is_today)) in enumerate(heads):
        if is_today:
            if n + 1 < len(heads):
                return lines[i: heads[n + 1][0]]
            return trim_tail(lines[i: i + MAX_BLOCK_LINES], relaxed)
    return []  # day-by-day listing, but nothing for today (weekend, or last week's menu)


def daily_heading_block(lines: list[str], pattern: str | None = None, relaxed: bool = False) -> list[str] | None:
    want = strip_accents(pattern.strip()) if pattern and pattern.strip() else None
    for i, l in enumerate(lines):
        is_head = (want in strip_accents(l)) if want else looks_daily(l)
        if len(l) <= 60 and is_head and find_price(l)[0] is None:
            block, misses, seen_price = [l], 0, False
            for nxt in lines[i + 1: i + 1 + MAX_BLOCK_LINES]:
                has_price = find_price(nxt, relaxed)[0] is not None
                seen_price |= has_price
                misses = 0 if has_price else misses + 1
                if seen_price and misses >= 6:
                    break
                block.append(nxt)
            if seen_price:
                return trim_tail(block, relaxed)
    return None


def trim_tail(block: list[str], relaxed: bool = False) -> list[str]:
    """Cut contact/footer lines that follow the last dish with a price."""
    last = max((i for i, l in enumerate(block) if find_price(l, relaxed)[0] is not None), default=len(block) - 1)
    return block[: last + 1]


def main_content(soup: BeautifulSoup) -> BeautifulSoup:
    """The page without header/footer/sidebars, preferably just <main>/<article>."""
    for t in soup(CHROME_TAGS):
        t.decompose()
    for sel in ("main", "article", "[role=main]", ".entry-content", ".content", "#content"):
        found = soup.select(sel)
        if found and len(found[0].get_text(strip=True)) > 40:
            return BeautifulSoup("".join(str(f) for f in found), "lxml")
    return soup


def lines_to_sections(lines: list[str], default_name: str, relaxed: bool = False) -> list[MenuSection]:
    sections: list[MenuSection] = []
    current = MenuSection(name=default_name)
    pending: MenuItem | None = None  # a dish name waiting for a price on the next line

    def flush_pending() -> None:
        nonlocal pending
        if pending is not None:
            current.items.append(pending)
            pending = None

    for raw in lines:
        price, rest = find_price(raw, relaxed)
        norm = strip_accents(raw)
        short_heading = HEADING_RE.match(norm) and ":" not in raw and len(raw.split()) <= 3
        if price is None and len(raw) <= 40 and (short_heading or raw.endswith(":")):
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


IMAGE_RE = re.compile(r"\.(jpe?g|png|webp)(\?|$)", re.IGNORECASE)
NOT_MENU_IMAGE = re.compile(r"logo|icon|favicon|sprite|banner|avatar", re.IGNORECASE)


def menu_images(soup: BeautifulSoup, base_url: str, any_image: bool = False) -> list[str]:
    """Pictures whose file name, alt text or link mention a (daily) menu.

    With `any_image` (a page that is itself the daily menu) every content picture counts.
    """
    out: list[str] = []
    for img in soup.find_all("img"):
        src = img.get("data-src") or img.get("data-lazy-src") or img.get("src") or ""
        if src.startswith("data:"):
            continue
        label = strip_accents(" ".join([src, img.get("alt") or "", img.get("title") or ""]))
        parent = img.find_parent("a")
        if parent is not None and parent.get("href"):
            label += " " + strip_accents(parent["href"] + " " + clean_space(parent.get_text()))
        small = any(str(img.get(k) or "").isdigit() and int(img.get(k)) < 120 for k in ("width", "height"))
        if src and (any_image or MENU_LINK_RE.search(label)) and not NOT_MENU_IMAGE.search(src) and not small:
            out.append(urljoin(base_url, src))
    for a in soup.find_all("a", href=True):
        href = urljoin(base_url, a["href"])
        if IMAGE_RE.search(href) and MENU_LINK_RE.search(strip_accents(href + " " + a.get_text())):
            out.append(href)
    return list(dict.fromkeys(out))[:4]


def menu_links(soup: BeautifulSoup, base_url: str) -> list[str]:
    host = urlparse(base_url).netloc
    out: list[str] = []
    # Embedded menus (menicka.cz widgets, Google Docs, ...) come first, from any host.
    for fr in soup.find_all("iframe", src=True):
        src = urljoin(base_url, fr["src"])
        if src.startswith("http") and not re.search(r"youtube|google\.com/maps|facebook|instagram", src):
            out.append(src)
    daily: list[str] = []
    for a in soup.find_all("a", href=True):
        href = urljoin(base_url, a["href"]).split("#")[0]
        text = clean_space(a.get_text())
        if not MENU_LINK_RE.search(strip_accents(text + " " + href)):
            continue
        is_file = re.search(r"\.(pdf|jpe?g|png|webp)(\?|$)", href, re.IGNORECASE)
        if (urlparse(href).netloc == host or is_file) and href != base_url.split("#")[0]:
            (daily if is_daily_url(href, text) and not is_file else out).append(href)
    # Daily-menu pages first, then iframes and other menu links.
    return list(dict.fromkeys(daily + out))[:8]


def daily_menu_links(soup: BeautifulSoup, base_url: str) -> list[str]:
    host = urlparse(base_url).netloc
    out = []
    for a in soup.find_all("a", href=True):
        href = urljoin(base_url, a["href"]).split("#")[0]
        if urlparse(href).netloc == host and is_daily_url(href, clean_space(a.get_text())) \
                and not re.search(r"\.(pdf|jpe?g|png|webp)(\?|$)", href, re.IGNORECASE):
            out.append(href)
    return list(dict.fromkeys(out))


def parse_html(html: str, url: str, selector: str | None = None, today: date | None = None,
               pattern: str | None = None, daily_page: bool = False) -> MenuResult:
    """`daily_page`: the whole page is the daily menu (e.g. reached via a "Denní menu" link)."""
    today = today or date.today()
    daily_page = daily_page or is_daily_url(url)
    relaxed = daily_page or bool(selector)
    soup = BeautifulSoup(html, "lxml")
    links = menu_links(soup, url)
    daily_links = daily_menu_links(soup, url)
    images = menu_images(soup, url)
    root = soup
    if selector:
        picked = soup.select(selector)
        if not picked:
            return MenuResult(source_url=url, links=links, images=images, daily_links=daily_links,
                              error=f"Selektor '{selector}' na stránke nič nenašiel.")
        root = BeautifulSoup("".join(str(p) for p in picked), "lxml")
    if daily_page and not selector:
        root = main_content(root)
    if daily_page:
        images = menu_images(root, url, any_image=True) or images
    lines = page_lines(root)
    # A daily-menu page with some text is shown as text later, so only a truly empty one counts.
    min_text = 40 if daily_page else 150
    almost_empty = sum(len(l) for l in lines) < min_text and not any(find_price(l, relaxed)[0] for l in lines)
    if almost_empty and not selector and not images:
        return MenuResult(source_url=url, links=links, images=images, daily_links=daily_links,
                          error="Stránka nemá skoro žiadny text. Menu sa asi načítava až JavaScriptom.")

    if selector:
        block, title = lines, "Denné menu"
    else:
        block = today_block(lines, today, relaxed)
        title = "Denné menu"
        if block == []:
            return MenuResult(source_url=url, links=links, images=images, daily_links=daily_links,
                              error="Na dnešný deň stránka menu neuvádza.")
        if block:
            title = block[0]
            block = block[1:]
        else:
            block = daily_heading_block(lines, pattern, relaxed)
            if block:
                title, block = block[0], block[1:]
            elif daily_page:
                # The page is the daily menu: its lines with a price are the dishes.
                block = [l for l in lines if find_price(l, True)[0] is not None]
                if not block:
                    if images:
                        return MenuResult(source_url=url, links=links, images=images, daily_links=daily_links,
                                          error="Denné menu je na obrázku.")
                    # No prices at all: show the page text itself rather than nothing.
                    text = [MenuItem(name=l) for l in lines
                            if 3 <= len(l) <= 200 and not (len(l) <= 60 and looks_daily(l))][:MAX_BLOCK_LINES]
                    return MenuResult(sections=[MenuSection("Text stránky s denným menu", text, True)],
                                      source_url=url, links=links, images=images, daily_links=daily_links)
            else:
                # Only the daily menu matters: no guessing from the whole page.
                return MenuResult(source_url=url, links=links, images=images, daily_links=daily_links,
                                  error="Na stránke som nenašiel denné menu.")

    sections = lines_to_sections(block, title, relaxed)
    for s in sections:
        s.is_daily = True
    if not any(s.items for s in sections):
        return MenuResult(source_url=url, links=links, images=images, daily_links=daily_links, error="Na stránke som nenašiel denné menu.")
    return MenuResult(sections=sections, source_url=url, links=links, images=images, daily_links=daily_links)
