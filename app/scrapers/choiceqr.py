"""ChoiceQR menus (https://<venue>.choiceqr.com).

ChoiceQR pages are Next.js apps that ship the whole menu as JSON inside
<script id="__NEXT_DATA__">. The exact schema is not documented, so this
parser walks the JSON and recognises menu items by shape: an object with a
name and a price. Sections come either from the parent object that holds the
item list, or from a category/section id that the item points to.
"""
from __future__ import annotations

import json
import re
import statistics
from datetime import date
from typing import Any

from bs4 import BeautifulSoup

from .base import MenuItem, MenuResult, MenuSection, clean_space, mark_daily

NAME_KEYS = ("name", "title", "label")
PRICE_KEYS = ("price", "cost", "amount", "priceValue")
DESC_KEYS = ("description", "desc", "text", "subtitle")
REF_KEYS = ("category", "categoryId", "section", "sectionId", "menuSection", "group", "groupId", "parentId")
ID_KEYS = ("_id", "id", "uuid", "slug")
HIDDEN_KEYS = ("hidden", "isHidden", "archived", "deleted")
LANG_ORDER = ("cs", "cz", "sk", "en")


def is_choiceqr(url: str) -> bool:
    return "choiceqr.com" in url.lower()


def _text(value: Any) -> str:
    """Strings, or localised dicts like {"cs": "...", "en": "..."}."""
    if isinstance(value, str):
        return clean_space(re.sub(r"<[^>]+>", " ", value))
    if isinstance(value, dict):
        for lang in LANG_ORDER:
            if isinstance(value.get(lang), str) and value[lang].strip():
                return _text(value[lang])
        for v in value.values():
            if isinstance(v, str) and v.strip():
                return _text(v)
    return ""


def _name(d: dict) -> str:
    for k in NAME_KEYS:
        if k in d:
            t = _text(d[k])
            if t:
                return t
    return ""


def _price(d: dict) -> float | None:
    for k in PRICE_KEYS:
        v = d.get(k)
        if isinstance(v, bool):
            continue
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str):
            m = re.search(r"\d+(?:[.,]\d+)?", v)
            if m:
                return float(m.group(0).replace(",", "."))
        if isinstance(v, dict):  # {"value": 129, "currency": "CZK"}
            for kk in ("value", "amount", "price"):
                if isinstance(v.get(kk), (int, float)) and not isinstance(v.get(kk), bool):
                    return float(v[kk])
    return None


def _is_item(d: dict) -> bool:
    return bool(_name(d)) and _price(d) is not None


def _hidden(d: dict) -> bool:
    return any(d.get(k) is True for k in HIDDEN_KEYS) or d.get("available") is False


def _ref_name(d: dict, by_id: dict[str, str]) -> str:
    for k in REF_KEYS:
        v = d.get(k)
        if isinstance(v, str) and v in by_id:
            return by_id[v]
        if isinstance(v, dict) and _name(v):
            return _name(v)
        if isinstance(v, list):
            for x in v:
                if isinstance(x, str) and x in by_id:
                    return by_id[x]
    return ""


def extract_from_json(data: Any, today: date | None = None, pattern: str | None = None) -> list[MenuSection]:
    # 1) every named object that has an id -> possible section name for references
    by_id: dict[str, str] = {}

    def index(node: Any) -> None:
        if isinstance(node, dict):
            n = _name(node)
            if n and not _is_item(node):
                for k in ID_KEYS:
                    if isinstance(node.get(k), (str, int)):
                        by_id[str(node[k])] = n
            for v in node.values():
                index(v)
        elif isinstance(node, list):
            for v in node:
                index(v)

    index(data)

    # 2) collect items, remembering the nearest named non-item ancestor
    found: list[tuple[str, dict]] = []

    def walk(node: Any, parent_name: str) -> None:
        if isinstance(node, dict):
            if _is_item(node):
                found.append((parent_name, node))
                return  # don't descend into modifiers/options of an item
            n = _name(node) or parent_name
            for v in node.values():
                walk(v, n)
        elif isinstance(node, list):
            for v in node:
                walk(v, parent_name)

    walk(data, "")

    # 3) ChoiceQR-style prices may be stored in minor units (12900 = 129 Kč)
    prices = [_price(d) for _, d in found if _price(d)]
    divide = False
    if prices and statistics.median(prices) >= 1000 and all(p == int(p) and int(p) % 10 == 0 for p in prices):
        divide = True

    sections: dict[str, MenuSection] = {}
    seen: set[tuple[str, str, float | None]] = set()
    for parent_name, d in found:
        if _hidden(d):
            continue
        sec = _ref_name(d, by_id) or parent_name or "Menu"
        price = _price(d)
        if price is not None and divide:
            price = price / 100
        name = _name(d)
        key = (sec, name, price)
        if key in seen:
            continue
        seen.add(key)
        desc = next((_text(d[k]) for k in DESC_KEYS if k in d and _text(d[k])), "")
        sections.setdefault(sec, MenuSection(name=sec)).items.append(
            MenuItem(name=name, price=price, description=desc)
        )

    result = list(sections.values())
    mark_daily(result, today, pattern)
    return result


def parse_choiceqr(html: str, url: str, today: date | None = None, pattern: str | None = None) -> MenuResult:
    soup = BeautifulSoup(html, "lxml")
    payloads: list[Any] = []
    tag = soup.find("script", id="__NEXT_DATA__")
    if tag and tag.string:
        try:
            payloads.append(json.loads(tag.string))
        except json.JSONDecodeError:
            pass
    # Other inline JSON blobs (application/json, ld+json) as a fallback.
    for s in soup.find_all("script", type=re.compile(r"json")):
        if s is tag or not s.string:
            continue
        try:
            payloads.append(json.loads(s.string))
        except json.JSONDecodeError:
            continue

    for data in payloads:
        sections = extract_from_json(data, today, pattern)
        if sections:
            return MenuResult(sections=sections, source_url=url)
    return MenuResult(source_url=url, error="Na stránke ChoiceQR som nenašiel dáta menu.")
