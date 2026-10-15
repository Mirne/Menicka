"""Shared data model and text helpers for all menu parsers."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import date


@dataclass
class MenuItem:
    name: str
    price: float | None = None
    description: str = ""


@dataclass
class MenuSection:
    name: str
    items: list[MenuItem] = field(default_factory=list)
    # True = this is the daily/lunch menu (shown by default in the UI).
    is_daily: bool = False


@dataclass
class MenuResult:
    sections: list[MenuSection] = field(default_factory=list)
    source_url: str = ""
    # Links to PDFs/images/subpages that probably hold the menu, shown as a fallback.
    links: list[str] = field(default_factory=list)
    # Images that look like a menu (many places post the daily menu as a photo).
    images: list[str] = field(default_factory=list)
    # Names of every section found, kept for diagnostics when no daily one matched.
    found_sections: list[str] = field(default_factory=list)
    # Subset of `links` that point at a page which is itself the daily menu.
    daily_links: list[str] = field(default_factory=list)
    # ChoiceQR: names of other menus/sections that sound like a lunch menu (diagnostics).
    other_menus: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def item_count(self) -> int:
        return sum(len(s.items) for s in self.sections)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["item_count"] = self.item_count
        return d


def strip_accents(text: str) -> str:
    norm = unicodedata.normalize("NFKD", text)
    return "".join(c for c in norm if not unicodedata.combining(c)).lower()


def clean_space(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


# Czech + Slovak + English weekday names without diacritics, Monday = 0.
WEEKDAYS: list[tuple[str, ...]] = [
    ("pondeli", "pondelok", "monday"),
    ("utery", "utorok", "tuesday"),
    ("streda", "wednesday"),
    ("ctvrtek", "stvrtok", "thursday"),
    ("patek", "piatok", "friday"),
    ("sobota", "saturday"),
    ("nedele", "nedela", "sunday"),
]


def weekday_of(text: str) -> int | None:
    """Return the weekday index if the text *starts* with a weekday name."""
    t = strip_accents(clean_space(text))
    for idx, names in enumerate(WEEKDAYS):
        for n in names:
            if t.startswith(n) and (len(t) == len(n) or not t[len(n)].isalpha()):
                return idx
    return None


def weekday_in(text: str) -> int | None:
    """Return the weekday index if a weekday name appears anywhere as a word."""
    t = strip_accents(text)
    for idx, names in enumerate(WEEKDAYS):
        for n in names:
            if re.search(rf"\b{n}\b", t):
                return idx
    return None


_DAILY_RE = re.compile(
    r"denn|dnesn|poledn|obedov|lunch|daily|tydenn|tyzdenn|weekly|menu dne|business|"
    r"hotov|obed",
)


def looks_daily(name: str) -> bool:
    return bool(_DAILY_RE.search(strip_accents(name)))


def mark_daily(sections: list[MenuSection], today: date | None = None, pattern: str | None = None) -> None:
    """Flag the sections that form today's lunch menu.

    With `pattern` (set per restaurant) a section must contain that text,
    ignoring case and accents. Without it, the name must sound like a
    daily/lunch menu or be a weekday. A section named after a weekday counts
    only on that weekday.
    """
    today = today or date.today()
    want = strip_accents(pattern.strip()) if pattern and pattern.strip() else None
    for s in sections:
        wd = weekday_in(s.name)
        if want is not None:
            ok = want in strip_accents(s.name)
        else:
            ok = wd is not None or looks_daily(s.name)
        s.is_daily = ok and (wd is None or wd == today.weekday())


# 129 Kč | 129,- | 129.00 Kč | 129 CZK | 12,50 € ...
PRICE_RE = re.compile(
    r"(?<![\d/])(\d{1,4}(?:[.,]\d{1,2})?)\s*(?:,-|\.-|,–|kč|kc|czk|€|eur)(?![a-z])",
    re.IGNORECASE,
)


# "Kč 129" / "CZK 129"
PRICE_PREFIX_RE = re.compile(r"(?:kč|kc|czk)\s*(\d{1,4}(?:[.,]\d{1,2})?)(?![\d])", re.IGNORECASE)
# A bare number at the end of a dish line ("Chicken korma ... 159"), trusted only on daily-menu pages.
BARE_PRICE_RE = re.compile(r"(?<![\d.,/:+])(\d{2,3})(?:[.,]-)?\s*$")
PHONE_OR_TIME_RE = re.compile(r"\d{3}\s?\d{3}\s?\d{3}|\d{1,2}[:.]\d{2}\s*[-–]|tel|telefon|\bpsc\b", re.IGNORECASE)


def find_price(text: str, relaxed: bool = False) -> tuple[float | None, str]:
    """Return (price, text without the price) using the last price on the line.

    `relaxed` also accepts a bare number (30-999) at the end of a line that has words in it.
    """
    matches = list(PRICE_RE.finditer(text)) or list(PRICE_PREFIX_RE.finditer(text))
    if not matches and relaxed and re.search(r"[^\W\d_]{3}", text) and not PHONE_OR_TIME_RE.search(strip_accents(text)):
        m = BARE_PRICE_RE.search(text)
        if m and 30 <= int(m.group(1)) <= 999:
            matches = [m]
    if not matches:
        return None, text
    m = matches[-1]
    price = float(m.group(1).replace(",", "."))
    rest = clean_space(text[: m.start()] + " " + text[m.end():])
    rest = re.sub(r"[\s.…·•\-–—|:]+$", "", rest).strip()
    return price, rest



SHORT_WEEKDAYS = ("po", "ut", "st", "ct", "pa", "so", "ne")
DATE_RE = re.compile(r"(?<!\d)(\d{1,2})\.\s?(\d{1,2})\.(?:\s?(\d{4}))?")


def date_in(text: str, today: date) -> date | None:
    m = DATE_RE.search(text)
    if not m:
        return None
    try:
        return date(int(m.group(3) or today.year), int(m.group(2)), int(m.group(1)))
    except ValueError:
        return None


def day_heading(text: str, today: date) -> tuple[object, bool] | None:
    """If a short line is a day heading, return (key, is_today).

    Accepts "Čtvrtek", "Čtvrtek 15.10.", "Čt 15. 10.", "15.10.2026". When the line has
    a date, the date decides, so last week's menu does not count as today's.
    """
    if len(text) > 60:
        return None
    t = strip_accents(clean_space(text))
    d = date_in(t, today)
    if weekday_of(t) is None:
        if d is None:
            return None
        words = re.sub(r"[^a-z ]", " ", DATE_RE.sub(" ", t)).split()
        # only the date, optionally with a short weekday name ("Čt") or "menu"
        if any(w not in SHORT_WEEKDAYS and w not in ("menu", "denni", "dne") for w in words):
            return None
    if d is not None:
        return d, d == today
    wd = weekday_of(t)
    return wd, wd == today.weekday()
