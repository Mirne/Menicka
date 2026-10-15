"""Every message the server shows on the menu cards, in Slovak, kept in one place."""
from __future__ import annotations

NO_DAILY_MENU = "Na stránke som nenašiel denné menu."
NOTHING_TODAY = "Na dnešný deň stránka menu neuvádza."
ALMOST_EMPTY = "Stránka nemá skoro žiadny text. Menu sa asi načítava až JavaScriptom."
NOTHING_IN_SELECTION = "Vo vybranej časti stránky som nenašiel menu."
MENU_IS_PICTURE = "Denné menu je na obrázku."
PICTURES_UNREADABLE = "Na obrázkoch som denné menu neprečítal."
NO_DAILY_IN_DOCUMENT = "V dokumente som nenašiel denné menu."
DOCUMENT_UNREADABLE = "Dokument sa nepodarilo prečítať."
NO_CHOICEQR_DATA = "Na stránke ChoiceQR som nenašiel dáta menu."
RESTAURANT_MISSING = "Reštaurácia neexistuje"
SECTION_DAILY = "Denné menu"
SECTION_PAGE_TEXT = "Text stránky s denným menu"
SKIP_NAME = "Nejdem na obed"


def not_recognized(other_menus: list[str]) -> str:
    msg = "Denné menu som nerozoznal."
    if other_menus:
        msg += " Na stránke je aj: " + ", ".join(other_menus) + "."
    return msg


def selector_empty(selector: str) -> str:
    return f"Selektor '{selector}' na stránke nič nenašiel."


def stale_week(start, end) -> str:
    return f"Menu na stránke je pre týždeň {start.day}.{start.month}.–{end.day}.{end.month}., nie pre dnešok."


def load_failed(detail: str) -> str:
    return f"Stránku sa nepodarilo načítať: {detail}"


def parse_failed(detail: str) -> str:
    return f"Chyba pri spracovaní menu: {detail}"

