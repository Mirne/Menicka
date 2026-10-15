"""Parser tests on synthetic pages (the real sites were not reachable when these were written)."""
import asyncio
import json
from datetime import date

import httpx

from app.scrapers import fetch_menu
from app.scrapers.base import find_price, weekday_of
from app.scrapers.choiceqr import parse_choiceqr
from app.scrapers.html_generic import parse_html

THURSDAY = date(2026, 10, 15)


def next_data(payload: dict) -> str:
    return f'<html><body><div id="__next"></div><script id="__NEXT_DATA__" type="application/json">{json.dumps(payload)}</script></body></html>'


def test_find_price_variants():
    assert find_price("Kuřecí tikka masala 189 Kč") == (189.0, "Kuřecí tikka masala")
    assert find_price("Polévka dne ........ 45,-") == (45.0, "Polévka dne")
    assert find_price("Dal makhani 149,50 Kč") == (149.5, "Dal makhani")
    assert find_price("Rýže 150 g") == (None, "Rýže 150 g")


def test_weekday_of():
    assert weekday_of("Čtvrtek 15.10.") == 3
    assert weekday_of("PONDĚLÍ") == 0
    assert weekday_of("Piatok") == 4
    assert weekday_of("Pondělní akce") is None


def test_choiceqr_nested_sections():
    payload = {"props": {"pageProps": {"menu": {"sections": [
        {"_id": "s1", "name": "Denní menu", "items": [
            {"_id": "i1", "name": {"cs": "Chicken curry", "en": "Chicken curry"}, "price": 159, "description": "s rýží"},
            {"_id": "i2", "name": "Paneer butter masala", "price": 169},
        ]},
        {"_id": "s2", "name": "Předkrmy", "items": [{"_id": "i3", "name": "Samosa", "price": 89}]},
    ]}}}}
    r = parse_choiceqr(next_data(payload), "https://x.choiceqr.com/section:menu", THURSDAY)
    assert r.error is None
    daily = [s for s in r.sections if s.is_daily]
    assert [s.name for s in daily] == ["Denní menu"]
    assert [(i.name, i.price, i.description) for i in daily[0].items] == [
        ("Chicken curry", 159.0, "s rýží"), ("Paneer butter masala", 169.0, "")]
    assert r.item_count == 3


def test_choiceqr_flat_items_with_category_ids_and_minor_units():
    payload = {"props": {"pageProps": {
        "categories": [{"_id": "c1", "name": "Polední menu - Čtvrtek"}, {"_id": "c2", "name": "Polední menu - Pátek"},
                       {"_id": "c3", "name": "Nápoje"}],
        "items": [
            {"_id": "a", "name": "Dal tadka", "price": 14900, "category": "c1"},
            {"_id": "b", "name": "Biryani", "price": 17900, "category": "c2"},
            {"_id": "c", "name": "Lassi", "price": 6900, "category": "c3"},
            {"_id": "d", "name": "Skryté", "price": 1000, "category": "c1", "hidden": True},
        ]}}}
    r = parse_choiceqr(next_data(payload), "https://x.choiceqr.com", THURSDAY)
    by = {s.name: s for s in r.sections}
    assert by["Polední menu - Čtvrtek"].is_daily is True
    assert by["Polední menu - Pátek"].is_daily is False  # other weekday
    assert by["Nápoje"].is_daily is False
    assert [(i.name, i.price) for i in by["Polední menu - Čtvrtek"].items] == [("Dal tadka", 149.0)]


def test_choiceqr_without_data_reports_error():
    r = parse_choiceqr("<html><body>Loading…</body></html>", "https://x.choiceqr.com", THURSDAY)
    assert r.error and not r.sections


WEEK_PAGE = """<html><body><nav><a href="/">Domů</a></nav>
<h2>Polední menu</h2>
<h3>Středa 14.10.</h3><p>Polévka: Dal shorba 35 Kč</p><p>1. Chicken korma 155 Kč</p>
<h3>Čtvrtek 15.10.</h3>
<p>Polévka: Tomatová 35 Kč</p>
<p>1. Butter chicken s rýží (1,7) 159 Kč</p>
<p>2. Palak paneer</p><p>149,-</p>
<p>(7)</p>
<h3>Pátek 16.10.</h3><p>1. Lamb rogan josh 179 Kč</p>
<footer>Tel. 123 456 789</footer></body></html>"""


def test_html_takes_todays_block_only():
    r = parse_html(WEEK_PAGE, "https://www.example.cz/", today=THURSDAY)
    assert r.error is None
    items = [(i.name, i.price) for s in r.sections for i in s.items]
    assert items == [("Polévka: Tomatová", 35.0), ("1. Butter chicken s rýží (1,7)", 159.0), ("2. Palak paneer", 149.0)]
    assert all(s.is_daily for s in r.sections)


def test_html_weekend_has_no_menu():
    r = parse_html(WEEK_PAGE, "https://www.example.cz/", today=date(2026, 10, 17))
    assert r.error and "dnešný" in r.error


HEADING_PAGE = """<html><body><h1>Restaurace Test</h1><p>Vítejte!</p>
<div><h2>Denní menu</h2><ul>
<li>Polévka dne 39 Kč</li><li>Vegetable jalfrezi 145 Kč</li><li>Chicken vindaloo 155 Kč</li></ul></div>
<p>Rezervace</p><p>Kontakt</p><p>Otevírací doba</p><p>Po-Pá</p><p>11-22</p><p>Mapa</p><p>Instagram</p>
<p>Stálé menu: Naan 45 Kč</p></body></html>"""


def test_html_daily_heading_block():
    r = parse_html(HEADING_PAGE, "https://www.example.cz/", today=THURSDAY)
    names = [i.name for s in r.sections for i in s.items]
    assert names == ["Polévka dne", "Vegetable jalfrezi", "Chicken vindaloo"]


def test_html_selector():
    r = parse_html(HEADING_PAGE, "https://www.example.cz/", selector="ul", today=THURSDAY)
    assert r.item_count == 3
    r2 = parse_html(HEADING_PAGE, "https://www.example.cz/", selector="#nope", today=THURSDAY)
    assert r2.error


def test_follow_menu_subpage():
    home = '<html><body><h1>Everest</h1><a href="/denni-menu">Denní menu</a><a href="https://facebook.com/x">FB</a></body></html>'
    pages = {"https://www.example.cz/": home, "https://www.example.cz/denni-menu": HEADING_PAGE}

    def handler(req: httpx.Request) -> httpx.Response:
        body = pages.get(str(req.url))
        return httpx.Response(200, text=body) if body else httpx.Response(404)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await fetch_menu("https://www.example.cz/", today=THURSDAY, client=c)

    r = asyncio.run(run())
    assert r.error is None
    assert r.source_url == "https://www.example.cz/denni-menu"
    assert r.item_count == 3


def test_fetch_error_is_reported():
    def handler(req):
        raise httpx.ConnectError("boom")

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await fetch_menu("https://www.example.cz/", client=c)

    r = asyncio.run(run())
    assert r.error and "ConnectError" in r.error


def run_fetch(pages: dict, url: str, **kw):
    def handler(req: httpx.Request) -> httpx.Response:
        body = pages.get(str(req.url))
        return httpx.Response(200, text=body) if body else httpx.Response(404)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await fetch_menu(url, today=THURSDAY, client=c, **kw)

    return asyncio.run(run())


FULL_MENU_ONLY = {"props": {"pageProps": {"sections": [
    {"_id": "s1", "name": "Předkrmy", "items": [{"_id": "a", "name": "Samosa", "price": 89}]},
    {"_id": "s2", "name": "Tikka specials", "items": [{"_id": "b", "name": "Chicken tikka", "price": 199}]},
]}}}


def test_choiceqr_only_daily_is_returned():
    url = "https://x.choiceqr.com/section:menu"
    payload = {"props": {"pageProps": {"sections": FULL_MENU_ONLY["props"]["pageProps"]["sections"] + [
        {"_id": "s3", "name": "Obědové menu", "items": [{"_id": "c", "name": "Dal", "price": 139}]}]}}}
    r = run_fetch({url: next_data(payload)}, url)
    assert r.error is None
    assert [s.name for s in r.sections] == ["Obědové menu"]


def test_choiceqr_without_daily_lists_found_sections():
    url = "https://x.choiceqr.com/section:menu"
    r = run_fetch({url: next_data(FULL_MENU_ONLY)}, url)
    assert r.sections == []
    assert r.error == "Denné menu som nerozoznal."
    assert r.found_sections == ["Předkrmy", "Tikka specials"]


def test_daily_section_setting_picks_the_section():
    url = "https://x.choiceqr.com/section:menu"
    r = run_fetch({url: next_data(FULL_MENU_ONLY)}, url, daily_section="tikka SPECIALS")
    assert [i.name for s in r.sections for i in s.items] == ["Chicken tikka"]


def test_daily_section_setting_for_html_heading():
    page = """<html><body><h2>Naše speciality</h2><p>Biryani 189 Kč</p><p>Korma 179 Kč</p></body></html>"""
    r = parse_html(page, "https://www.example.cz/", today=THURSDAY, pattern="nase specialit")
    assert r.item_count == 2
    assert parse_html(page, "https://www.example.cz/", today=THURSDAY).error


def test_html_whole_menu_is_not_shown():
    page = """<html><body><h2>Jídelní lístek</h2><p>Naan 45 Kč</p><p>Biryani 189 Kč</p></body></html>"""
    r = parse_html(page, "https://www.example.cz/", today=THURSDAY)
    assert r.error == "Na stránke som nenašiel denné menu."
    assert r.sections == []


def test_follow_iframe_on_other_host():
    home = """<html><body><h1>Everest</h1><iframe src="https://widget.example.net/menu?id=1"></iframe>
              <iframe src="https://www.youtube.com/embed/x"></iframe></body></html>"""
    r = run_fetch({"https://www.example.cz/": home, "https://widget.example.net/menu?id=1": WEEK_PAGE},
                  "https://www.example.cz/")
    assert r.error is None
    assert r.source_url == "https://widget.example.net/menu?id=1"
    assert [i.name for s in r.sections for i in s.items][0] == "Polévka: Tomatová"


def test_menu_images_are_collected():
    page = """<html><body><img src="/img/logo.png" alt="Everest">
      <img src="/uploads/denni-menu-42.jpg" alt="">
      <a href="/files/obedy.png">Polední menu</a></body></html>"""
    r = parse_html(page, "https://www.example.cz/", today=THURSDAY)
    assert r.images == ["https://www.example.cz/uploads/denni-menu-42.jpg", "https://www.example.cz/files/obedy.png"]


# --- Shapes seen on the real sites: Everest has /denni-menu/ and /jidelni-listek/ links,
# Padagali's ChoiceQR "section:menu" has only the regular menu sections.

EVEREST_HOME = """<html><body><header><a href="/">Everest</a><a href="/denni-menu/">Denní menu</a>
<a href="/jidelni-listek/">Jídelní lístek</a></header><main><h1>Indická a nepálská restaurace</h1>
<p>Vítejte v restauraci Everest. Vaříme tradiční indická a nepálská jídla každý den od 11 do 22 hodin.</p>
</main></body></html>"""
FULL_LISTEK = """<html><body><main><h1>Jídelní lístek</h1><p>Chicken tikka masala 249 Kč</p>
<p>Lamb korma 289 Kč</p></main></body></html>"""


def everest(daily_page_html: str):
    return run_fetch({"https://www.example.cz/": EVEREST_HOME,
                      "https://www.example.cz/denni-menu/": daily_page_html,
                      "https://www.example.cz/jidelni-listek/": FULL_LISTEK}, "https://www.example.cz/")


def test_everest_like_week_with_short_days_and_bare_prices():
    page = """<html><body><header>Everest</header><main><h1>Denní menu 12.10. – 16.10.</h1>
    <p>Po 12.10.</p><p>1. Chicken curry, rýže 149</p>
    <p>Čt 15.10.</p><p>Polévka: Dal shorba</p><p>1. Butter chicken, naan 159</p><p>2. Palak paneer, rýže 149</p>
    <p>Pá 16.10.</p><p>1. Lamb rogan josh 179</p></main>
    <footer>Tel. 773 990 837, Veveří 61</footer></body></html>"""
    r = everest(page)
    assert r.error is None, r.error
    assert r.source_url == "https://www.example.cz/denni-menu/"
    assert [(i.name, i.price) for s in r.sections for i in s.items] == [
        ("Polévka: Dal shorba", None), ("1. Butter chicken, naan", 159.0), ("2. Palak paneer, rýže", 149.0)]


def test_everest_like_single_day_page_without_headings():
    page = """<html><body><header><nav>Domů Denní menu Kontakt</nav></header><main>
    <p>Polévka dle denní nabídky</p><p>Menu 1 Chicken madras, rýže 145</p><p>Menu 2 Dal makhani, naan 139</p>
    </main><footer>Otevřeno Po–Pá 11:00 – 22:00, tel. 773 990 837</footer></body></html>"""
    r = everest(page)
    assert r.error is None, r.error
    assert [i.price for s in r.sections for i in s.items if i.price] == [145.0, 139.0]


def test_everest_like_menu_as_image():
    page = """<html><body><header><img src="/logo.png"></header><main><h1>Denní menu</h1>
    <img src="/wp-content/uploads/2026/10/IMG_4821.jpg" width="1080" height="1350"></main></body></html>"""
    r = everest(page)
    assert r.error == "Denné menu je na obrázku."
    assert r.images == ["https://www.example.cz/wp-content/uploads/2026/10/IMG_4821.jpg"]
    assert r.source_url == "https://www.example.cz/denni-menu/"


def test_everest_like_text_without_prices_is_shown_as_text():
    page = """<html><body><main><h1>Denní menu</h1><p>Polévka: Tomatová</p>
    <p>Kuřecí kari s rýží</p><p>Zeleninové korma s naan</p><p>Cena menu 149 Kč s polévkou.</p></main></body></html>"""
    r = everest(page)
    assert r.error is None
    assert [(i.name, i.price) for s in r.sections for i in s.items] == [
        ("Polévka: Tomatová", None), ("Kuřecí kari s rýží", None), ("Zeleninové korma s naan", None),
        ("Cena menu s polévkou", 149.0)]


def test_everest_like_short_text_page_is_shown():
    page = """<html><body><main><h1>Denní menu</h1><p>Polévka: Tomatová</p>
    <p>Kuřecí kari s rýží</p><p>Zeleninové korma s naan</p></main></body></html>"""
    r = everest(page)
    assert r.error is None, r.error
    assert [i.name for s in r.sections for i in s.items] == [
        "Polévka: Tomatová", "Kuřecí kari s rýží", "Zeleninové korma s naan"]


def test_last_weeks_dated_menu_is_not_today():
    page = """<html><body><main><p>Středa 7.10.</p><p>Dal 139</p><p>Čtvrtek 8.10.</p><p>Korma 149</p></main></body></html>"""
    r = everest(page)
    assert r.error == "Na dnešný deň stránka menu neuvádza."


def test_choiceqr_follows_lunch_menu_found_in_page_data():
    base = "https://x.choiceqr.com/section:menu"
    main = {"props": {"pageProps": {
        "menus": [{"_id": "m1", "name": "Menu", "slug": "menu"}, {"_id": "m2", "name": "Polední menu", "slug": "poledni-menu"}],
        "sections": FULL_MENU_ONLY["props"]["pageProps"]["sections"]}}}
    lunch = {"props": {"pageProps": {"sections": [
        {"_id": "l1", "name": "Polední menu", "items": [
            {"_id": "x", "name": "Chicken curry", "price": 15900, "available": False},
            {"_id": "y", "name": "Dal tadka", "price": 13900}]}]}}}
    r = run_fetch({base: next_data(main), "https://x.choiceqr.com/section:poledni-menu": next_data(lunch)}, base)
    assert r.error is None, r.error
    assert [(i.name, i.price) for s in r.sections for i in s.items] == [("Chicken curry", 159.0), ("Dal tadka", 139.0)]


def test_choiceqr_reports_lunch_menu_it_could_not_open():
    base = "https://x.choiceqr.com/section:menu"
    main = {"props": {"pageProps": {"menus": [{"_id": "m2", "name": "Lunch menu", "slug": "lunch"}],
                                    "sections": FULL_MENU_ONLY["props"]["pageProps"]["sections"]}}}
    r = run_fetch({base: next_data(main)}, base)
    assert r.error == "Denné menu som nerozoznal. Na stránke je aj: Lunch menu."
    assert r.found_sections == ["Předkrmy", "Tikka specials"]
