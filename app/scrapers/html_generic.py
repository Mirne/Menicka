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
    SHORT_WEEKDAYS,
    MenuSection,
    clean_space,
    day_heading,
    find_price,
    looks_daily,
    stale_week,
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
DAILY_URL_RE = re.compile(r"denn|poledn|obed|lunch|daily|tydenn|weekly|menu-dne|hotovk", re.IGNORECASE)
CHROME_TAGS = ["header", "footer", "aside", "form"]
# Where a day's menu ends: drinks list, notes, allergen legend, wifi, contact.
STOP_RE = re.compile(
    r"^[*\s]*(tocene|pivo\b|beer|napoje|drinks|poznamk|alergen|seznam alergen|wifi|nazev wifi|heslo|"
    r"kontakt|oteviraci|for more info)"
)


# Name day notes ("Čtvrtek: svátek má Tereza") are not part of the menu.
NAME_DAY_RE = re.compile(r"\s*[-–—:,]?\s*\b(sv[aá]tek|jmeniny|meniny)\b.*$", re.IGNORECASE)
# Promotions and conditions around a lunch menu (matched without accents).
NOISE_RE = re.compile(
    r"zvyhodnen|doprodej|objednav|doporucujeme|plati pri|v dobe poledniho|po dobu poledniho|"
    r"po celou dobu|kohoutkov|menu box|na odnos|vcetne polevky|cena menu|cena je|rezervac|"
    r"\bza\s+\d+\s*(?:kc|,-)|\btel\.|telefon"
)
# "MENU 1, 2 ... 165 Kč": the price of the numbered dishes 1) and 2)
MENU_PRICE_RE = re.compile(r"^(?:menu|menu c\.?|cislo)\s*(\d{1,2}(?:\s*(?:,|a|&|\+|-|–)\s*\d{1,2})*)\s*[:\-–.]*$")
NUMBERED_RE = re.compile(r"^(?:menu\s*)?(\d{1,2})\s*[).:]")
# "Pátek 16.10. Polévka: ..." -> heading and the rest on separate lines
GLUED_HEAD_RE = re.compile(
    r"^([^\W\d_]+\.?(?:\s*/\s*[^\W\d_]+)?\s+\d{1,2}\.\s?\d{1,2}\.(?:\s?\d{4})?)\s*[-–—:,]?\s+(\S.*)$"
)


def split_glued_headings(lines: list[str]) -> list[str]:
    out = []
    for line in lines:
        m = GLUED_HEAD_RE.match(line)
        if m and day_heading(m.group(1), date.today()) is not None:
            out += [m.group(1), m.group(2)]
        else:
            out.append(line)
    return out


def menu_price_table(lines: list[str]) -> dict[int, float]:
    """Prices given per dish number for the whole menu ("MENU 1, 2 165 Kč")."""
    table: dict[int, float] = {}
    for line in lines:
        price, rest = find_price(line)
        m = MENU_PRICE_RE.match(strip_accents(rest)) if price else None
        if not m:
            continue
        spec = m.group(1)
        if re.fullmatch(r"\d+\s*[-–]\s*\d+", spec):
            a, b = map(int, re.split(r"\s*[-–]\s*", spec))
            nums = range(a, b + 1)
        else:
            nums = [int(n) for n in re.findall(r"\d+", spec)]
        for n in nums:
            table.setdefault(n, price)
    return table


def is_noise(line: str) -> bool:
    t = strip_accents(line)
    if not re.search(r"[^\W_]", line):  # only punctuation, e.g. "```"
        return True
    price, rest = find_price(line)
    if price and MENU_PRICE_RE.match(strip_accents(rest)):
        return True
    return bool(NOISE_RE.search(t)) or bool(re.match(r"^\s*(sv[aá]tek|jmeniny|meniny)\b", line, re.IGNORECASE))


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
        if is_noise(raw):
            continue
        if raw.startswith("**"):  # "***Zvláštní nabídka ...***": a note, not a dish
            flush_pending()
            note = raw.strip("* ").strip()
            if note:
                current.items.append(MenuItem(name=note))
            continue
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
        is_pdf = re.search(r"\.pdf(\?|$)", href, re.IGNORECASE)
        if (urlparse(href).netloc == host or is_file) and href != base_url.split("#")[0]:
            (daily if is_daily_url(href, text) and (is_pdf or not is_file) else out).append(href)
    # Daily-menu pages first, then iframes and other menu links.
    return list(dict.fromkeys(daily + out))[:8]


def daily_menu_links(soup: BeautifulSoup, base_url: str) -> list[str]:
    host = urlparse(base_url).netloc
    out = []
    for a in soup.find_all("a", href=True):
        href = urljoin(base_url, a["href"]).split("#")[0]
        is_pdf = re.search(r"\.pdf(\?|$)", href, re.IGNORECASE)
        if (urlparse(href).netloc == host or is_pdf) and is_daily_url(href, clean_space(a.get_text())) \
                and not re.search(r"\.(jpe?g|png|webp)(\?|$)", href, re.IGNORECASE):
            out.append(href)
    return list(dict.fromkeys(out))


class NotFound(Exception):
    """No daily menu in the given lines; the message says why."""


def clean_title(line: str) -> str:
    """'Čtvrtek/ Thursday © BRNO, Denní Menu 11:00' -> 'Čtvrtek/ Thursday'."""
    line = NAME_DAY_RE.sub("", line).strip() or line
    if len(line) <= 25:
        return line
    if weekday_of(line) is None:
        # weekday in the middle ("Wifi Upstairs Pondělí / Monday Wifi Downstairs")
        for m in re.finditer(r"[^\W\d_]+(?:\s*/\s*[^\W\d_]+)?", line):
            if weekday_of(m.group(0)) is not None:
                return m.group(0)
    m = re.match(r"^[^\W\d_]+\.?(?:\s*/\s*[^\W\d_]+)?(?:\s+\d{1,2}\.\s?\d{1,2}\.(?:\s?\d{4})?)?", line)
    return m.group(0).strip() if m else line


def cut_at_stop(block: list[str]) -> list[str]:
    """End a day's block where drinks, notes or contact info start."""
    for i, line in enumerate(block):
        if i and STOP_RE.match(strip_accents(line)):
            return block[:i]
    return block


def per_day_filter(block: list[str], today: date) -> list[str] | None:
    """Keep today's part of a block that lists the week ("Pondělí: Pizza Diavola 179 Kč").

    Returns the block unchanged when it is not split by days, None when it is but has
    nothing for today.
    """
    def day_of(line: str):
        if find_price(line)[0] is not None:
            return None
        h = day_heading(line, today)
        if h is not None:
            return h
        short = strip_accents(line).strip(" .:")
        if short in SHORT_WEEKDAYS:  # "Čt" alone on a line
            idx = SHORT_WEEKDAYS.index(short)
            return idx, idx == today.weekday()
        return None

    heads = [(i, h) for i, line in enumerate(block) if (h := day_of(line)) is not None]
    if len({key for _, (key, _) in heads}) >= 2:
        for n, (i, (_, is_today)) in enumerate(heads):
            if is_today:
                end = heads[n + 1][0] if n + 1 < len(heads) else len(block)
                return block[i + 1: end] or None
        return None
    dated = [(weekday_of(l), l) for l in block]
    if sum(1 for wd, _ in dated if wd is not None) >= 2:
        keep = []
        for wd, line in dated:
            if wd == today.weekday():
                rest = re.sub(r"^[^\W\d_]+\.?\s*(?:/\s*[^\W\d_]+\s*)?[:\-–—]?\s*", "", line)
                if rest:
                    keep.append(rest)
        return keep or None
    return block


def extra_sections(lines: list[str], today: date, texts: list[str], relaxed: bool,
                   have: list[MenuSection]) -> list[MenuSection]:
    """Sections the restaurant asked for on top of the daily menu (e.g. "pizz" for the pizza offer)."""
    out: list[MenuSection] = []
    shown = {strip_accents(i.name) for sec in have for i in sec.items}
    for text in texts:
        block = daily_heading_block(lines, text, relaxed)
        if not block:
            continue
        body = block[1:]
        heads = [i for i, l in enumerate(body) if day_heading(l, today) is not None]
        if len(heads) == 1 or (heads and heads[0] > 0 and len(heads) < 2):
            body = body[: heads[0]]
        body = per_day_filter(body, today)
        if not body:
            continue
        for sec in lines_to_sections(cut_at_stop(body), block[0], relaxed):
            sec.items = [i for i in sec.items if strip_accents(i.name) not in shown]
            if sec.items:
                sec.is_daily = True
                out.append(sec)
                shown |= {strip_accents(i.name) for i in sec.items}
    return out


def sections_from_lines(lines: list[str], today: date, pattern: str | None = None,
                        relaxed: bool = False, also: list[str] | None = None) -> list[MenuSection]:
    """Today's menu from text lines (a web page or a picture read by OCR).

    Raises NotFound when the lines hold no menu for today.
    """
    lines = split_glued_headings(lines)
    stale = stale_week(lines, today)
    block = today_block(lines, today, relaxed)
    if stale and block is not None:
        raise NotFound(stale)
    if block == []:
        raise NotFound("Na dnešný deň stránka menu neuvádza.")
    if block:
        title, block = clean_title(block[0]), cut_at_stop(block[1:])
    else:
        block = daily_heading_block(lines, pattern, relaxed)
        if not block:
            raise NotFound("Na stránke som nenašiel denné menu.")
        title, block = block[0], cut_at_stop(block[1:])
    sections = lines_to_sections(block, title, relaxed)
    for sec in sections:
        sec.is_daily = True
    if not any(sec.items for sec in sections):
        raise NotFound("Na stránke som nenašiel denné menu.")
    prices = menu_price_table(lines)
    for sec in sections:
        for item in sec.items:
            m = NUMBERED_RE.match(strip_accents(item.name))
            if item.price is None and m and int(m.group(1)) in prices:
                item.price = prices[int(m.group(1))]
    if also:
        sections += extra_sections(lines, today, also, relaxed, sections)
    return sections


def daily_document(lines: list[str], today: date, pattern: str | None = None,
                   also: list[str] | None = None) -> list[MenuSection]:
    """Lines of a page/PDF/picture that is itself the daily menu.

    Tries the day-by-day and heading structure first; without it, the lines with a
    price are the dishes. Raises NotFound when there is nothing usable.
    """
    try:
        return sections_from_lines(lines, today, pattern, True, also)
    except NotFound as e:
        if str(e) != "Na stránke som nenašiel denné menu.":
            raise
    block = cut_at_stop([l for l in lines if find_price(l, True)[0] is not None])
    sections = lines_to_sections(block, "Denné menu", True) if block else []
    for sec in sections:
        sec.is_daily = True
    if not any(sec.items for sec in sections):
        raise NotFound("Na stránke som nenašiel denné menu.")
    return sections


def fragment_root(soup: BeautifulSoup, url: str) -> BeautifulSoup | None:
    """The part of a one-page site that "#lunch-menu" in the URL points at."""
    frag = urlparse(url).fragment
    if not frag:
        return None
    el = soup.find(id=frag) or soup.find(attrs={"name": frag})
    if el is None:
        return None
    parts = [el]
    if len(el.get_text(strip=True)) < 80:
        # Only an anchor or a heading: the menu follows it.
        parts += [sib for sib in el.find_next_siblings()][:30]
    return BeautifulSoup("".join(str(p) for p in parts), "lxml")


def parse_html(html: str, url: str, selector: str | None = None, today: date | None = None,
               pattern: str | None = None, daily_page: bool = False,
               also: list[str] | None = None) -> MenuResult:
    """`daily_page`: the whole page is the daily menu (e.g. reached via a "Denní menu" link)."""
    today = today or date.today()
    daily_page = daily_page or is_daily_url(url)
    relaxed = daily_page or bool(selector)
    soup = BeautifulSoup(html, "lxml")
    base = {"source_url": url, "links": menu_links(soup, url), "daily_links": daily_menu_links(soup, url)}
    images = menu_images(soup, url)
    root = soup
    if selector:
        picked = soup.select(selector)
        if not picked:
            return MenuResult(**base, images=images, error=f"Selektor '{selector}' na stránke nič nenašiel.")
        root = BeautifulSoup("".join(str(p) for p in picked), "lxml")
    elif (frag := fragment_root(soup, url)) is not None:
        root, daily_page = frag, True
    elif daily_page:
        root = main_content(root)
    if daily_page:
        images = menu_images(root, url, any_image=True) or images
    lines = page_lines(root)
    # A daily-menu page with some text is shown as text later, so only a truly empty one counts.
    min_text = 40 if daily_page else 150
    almost_empty = sum(len(l) for l in lines) < min_text and not any(find_price(l, relaxed)[0] for l in lines)
    if almost_empty and not selector and not images:
        return MenuResult(**base, images=images,
                          error="Stránka nemá skoro žiadny text. Menu sa asi načítava až JavaScriptom.")

    if selector:
        sections = lines_to_sections(lines, "Denné menu", relaxed)
        for sec in sections:
            sec.is_daily = True
        if not any(sec.items for sec in sections):
            return MenuResult(**base, images=images, error="Vo vybranej časti stránky som nenašiel menu.")
        return MenuResult(**base, sections=sections, images=images)
    try:
        if daily_page:
            sections = daily_document(lines, today, pattern, also)
        else:
            sections = sections_from_lines(lines, today, pattern, relaxed, also)
        return MenuResult(**base, sections=sections, images=images)
    except NotFound as e:
        if not daily_page or str(e) != "Na stránke som nenašiel denné menu.":
            return MenuResult(**base, images=images, error=str(e))
    if images:
        return MenuResult(**base, images=images, error="Denné menu je na obrázku.")
    # No prices at all: show the page text itself rather than nothing.
    text = [MenuItem(name=l) for l in lines
            if 3 <= len(l) <= 200 and not (len(l) <= 60 and looks_daily(l))][:MAX_BLOCK_LINES]
    return MenuResult(**base, sections=[MenuSection("Text stránky s denným menu", text, True)], images=images)
