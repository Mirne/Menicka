"""PadThai's daily menu is rendered from /data.json, not the HTML shell."""
from datetime import date
from urllib.parse import urlparse

from . import messages as msg
from .base import MenuItem, MenuResult, MenuSection, clean_space


def is_padthai(url: str) -> bool:
    return urlparse(url).hostname in ("padthairestaurace.cz", "www.padthairestaurace.cz")


def _item(raw: dict | None) -> MenuItem | None:
    if not isinstance(raw, dict):
        return None
    text = raw.get("cs") or raw.get("en") or {}
    name = clean_space(text.get("name", ""))
    if not name or name == "—":
        return None
    try:
        price = float(str(raw["price"]).replace(",", ".")) if raw.get("price") is not None else None
    except (ValueError, TypeError):
        price = None
    return MenuItem(name=name, price=price, description=clean_space(text.get("desc", "")))


def parse_padthai(data: dict, url: str, today: date) -> MenuResult:
    # Like the live site, days are Monday=1 through Friday=5. Its legacy weekTitle
    # is unused by the renderer; do not infer validity dates from that old field.
    day = (data.get("days") or {}).get(str(today.isoweekday())) or {}
    if today.weekday() >= 5 or not day:
        return MenuResult(source_url=url, error=msg.NOTHING_TODAY)
    soup = _item(day.get("polevka"))
    mains = [item for raw in day.get("hlavniChody", []) if (item := _item(raw))]
    sections = []
    if soup:
        sections.append(MenuSection("Polévka", [soup], True))
    if mains:
        sections.append(MenuSection("Hlavní chody", mains, True))
        specials = [item for raw in data.get("weeklySpecials", []) if (item := _item(raw))]
        if specials:
            sections.append(MenuSection("Týdenní speciální nabídka", specials, True))
    return MenuResult(source_url=url, sections=sections, error=None if sections else msg.NOTHING_TODAY)
