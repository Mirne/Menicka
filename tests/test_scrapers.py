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


def test_everest_like_menu_as_image(monkeypatch):
    from app.scrapers import ocr
    monkeypatch.setattr(ocr, "available", lambda: False)
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
        ("Polévka: Tomatová", None), ("Kuřecí kari s rýží", None), ("Zeleninové korma s naan", None)]


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



# --- Everest's real weekly menu picture (week 12.-16.10.2026), read by OCR.

import pathlib
import shutil

import pytest

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
needs_ocr = pytest.mark.skipif(shutil.which("tesseract") is None, reason="tesseract not installed")


def run_fetch_bytes(pages: dict, url: str, today: date):
    def handler(req: httpx.Request) -> httpx.Response:
        body = pages.get(str(req.url))
        if body is None:
            return httpx.Response(404)
        return httpx.Response(200, content=body if isinstance(body, bytes) else body.encode())

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await fetch_menu(url, today=today, client=c)

    return asyncio.run(run())


EVEREST_DAILY_PAGE = """<html><body><header><img src="/logo.png" width="80"></header><main>
<h1>Denní menu</h1><img src="/up/promo.jpg"><img src="/up/menu.webp"></main>
<footer>Veveří 61, Brno</footer></body></html>"""


def everest_real(today: date):
    return run_fetch_bytes({
        "https://www.example.cz/": EVEREST_HOME,
        "https://www.example.cz/denni-menu/": EVEREST_DAILY_PAGE,
        "https://www.example.cz/jidelni-listek/": FULL_LISTEK,
        "https://www.example.cz/up/promo.jpg": (FIXTURES / "everest-promo.jpg").read_bytes(),
        "https://www.example.cz/up/menu.webp": (FIXTURES / "everest-menu-2026-10-12.webp").read_bytes(),
    }, "https://www.example.cz/", today)


@needs_ocr
def test_everest_real_picture_thursday():
    r = everest_real(THURSDAY)
    assert r.error is None, r.error
    assert r.from_image and r.images == ["https://www.example.cz/up/menu.webp"]
    [sec] = r.sections
    assert sec.name == "Čtvrtek/ Thursday"
    dishes = [(i.name, i.price) for i in sec.items if i.price]
    assert dishes[0] == ("Dal Adrak Soup (Nepálská čočková a zázvorová polévka)", 27.0)
    assert [p for _, p in dishes] == [27, 45, 145, 145, 145, 145, 179, 199, 225, 145]
    assert dishes[3][0].startswith("2 Chicken Korma")
    assert not any("Poutník" in i.name or "Wifi" in i.name for i in sec.items)


@needs_ocr
@pytest.mark.parametrize("day,first,title", [
    (12, "Tomato Soup", "Pondělí / Monday"), (13, "Garlic Soup", "Úterý/Tuesday"),
    (14, "Chicken Soup", "Středa/Wednesday"), (16, "Tomato Soup", "Pátek / Friday")])
def test_everest_real_picture_other_days(day, first, title):
    r = everest_real(date(2026, 10, day))
    assert r.error is None, r.error
    assert r.sections[0].name == title
    assert r.sections[0].items[0].name.startswith(first)
    # the drinks list and notes after Friday are not part of the day
    assert not any("Poutník" in i.name or "Wifi" in i.name or "Heslo" in i.name for i in r.sections[0].items)


@needs_ocr
def test_everest_real_picture_next_week_is_stale():
    r = everest_real(date(2026, 10, 20))
    assert r.error == "Menu na stránke je pre týždeň 12.10.–16.10., nie pre dnešok."
    assert r.sections == []


# --- PDFs, "#anchor" URLs and extra sections (pizza)

def test_pdf_weekly_menu_today_only():
    url = "https://cdn.example.net/media/Obedova-nabidka.pdf"
    r = run_fetch_bytes({url: (FIXTURES / "obedova-nabidka-text.pdf").read_bytes()}, url, THURSDAY)
    assert r.error is None, r.error
    assert r.sections[0].name == "Čtvrtek 15. 10."
    assert [(i.name, i.price) for i in r.sections[0].items] == [
        ("Polévka: Kulajda", None), ("Hovězí guláš, houskový knedlík", 169.0), ("Zapečené těstoviny se sýrem", 149.0)]
    assert not r.from_image


def test_pdf_weekly_menu_next_week_is_stale():
    url = "https://cdn.example.net/media/Obedova-nabidka.pdf"
    r = run_fetch_bytes({url: (FIXTURES / "obedova-nabidka-text.pdf").read_bytes()}, url, date(2026, 10, 21))
    assert r.error == "Menu na stránke je pre týždeň 12.10.–16.10., nie pre dnešok."


def test_pdf_linked_from_page_is_followed():
    page = """<html><body><main><h1>Restaurace</h1><p>Vítejte u nás, vaříme poctivě každý den.</p>
    <a href="https://cdn.example.net/media/Obedova-nabidka.pdf">Obědová nabídka (PDF)</a></main></body></html>"""
    r = run_fetch_bytes({"https://www.example.cz/": page,
                         "https://cdn.example.net/media/Obedova-nabidka.pdf": (FIXTURES / "obedova-nabidka-text.pdf").read_bytes()},
                        "https://www.example.cz/", THURSDAY)
    assert r.error is None, r.error
    assert r.source_url.endswith("Obedova-nabidka.pdf")
    assert r.item_count == 3


@needs_ocr
def test_scanned_pdf_is_read_by_ocr():
    url = "https://cdn.example.net/media/menu-scan.pdf"
    r = run_fetch_bytes({url: (FIXTURES / "scanned-menu.pdf").read_bytes()}, url, THURSDAY)
    assert r.error is None, r.error
    assert r.from_image
    assert r.sections[0].name == "Čtvrtek/ Thursday"
    assert r.sections[0].items[0].name.startswith("Dal Adrak Soup")


ONE_PAGE_SITE = """<html><body><nav><a href="#about">O nás</a><a href="#lunch-menu">Lunch</a></nav>
<section id="about"><h2>O nás</h2><p>Steak 450 Kč, víno 120 Kč, vše čerstvé.</p></section>
<section id="lunch-menu"><h2>Lunch menu</h2>
  <p>Polévka: Dýňový krém 45 Kč</p><p>Kuřecí stehno, rýže 165 Kč</p></section>
<section id="contact"><p>Tel. 777 111 222</p></section></body></html>"""


def test_url_anchor_selects_that_part_of_the_page():
    r = run_fetch({"https://korzar.example/": ONE_PAGE_SITE}, "https://korzar.example/#lunch-menu")
    assert r.error is None, r.error
    assert [(i.name, i.price) for s in r.sections for i in s.items] == [
        ("Polévka: Dýňový krém", 45.0), ("Kuřecí stehno, rýže", 165.0)]


def test_url_anchor_on_an_empty_marker_takes_what_follows():
    page = """<html><body><div><a id="lunch-menu"></a><h2>Polední menu</h2><p>Svíčková 159 Kč</p>
    <p>Rizoto 149 Kč</p></div><footer>Tel. 777 111 222</footer></body></html>"""
    r = run_fetch({"https://korzar.example/": page}, "https://korzar.example/#lunch-menu")
    assert [i.name for s in r.sections for i in s.items] == ["Svíčková", "Rizoto"]


LA_STRADA = """<html><body><main><h1>Polední menu</h1>
<h3>Pondělí</h3><p>Polévka: Gulášová</p><p>1. Kuřecí řízek, kaše 159 Kč</p>
<h3>Čtvrtek</h3><p>Polévka: Kulajda</p><p>1. Lasagne 169 Kč</p><p>2. Rizoto s kuřecím masem 159 Kč</p>
<h3>Pátek</h3><p>1. Smažený sýr 159 Kč</p>
<h2>Výběr pizz k polednímu menu</h2>
<p>Pondělí: Margherita 149 Kč</p><p>Čtvrtek: Diavola 169 Kč</p><p>Pátek: Quattro formaggi 179 Kč</p>
</main><footer>Rezervace tel. 777 333 444</footer></body></html>"""


def test_also_adds_todays_pizza():
    url = "https://lastrada.example/poledni-menu/"
    r = run_fetch({url: LA_STRADA}, url, also=["pizz"])
    assert r.error is None, r.error
    assert [s.name for s in r.sections] == ["Čtvrtek", "Výběr pizz k polednímu menu"]
    assert [(i.name, i.price) for i in r.sections[1].items] == [("Diavola", 169.0)]
    # without the setting the pizza is not shown
    r2 = run_fetch({url: LA_STRADA}, url)
    assert [s.name for s in r2.sections] == ["Čtvrtek"]


def test_also_with_day_headings_inside_the_pizza_block():
    page = LA_STRADA.replace("""<p>Pondělí: Margherita 149 Kč</p><p>Čtvrtek: Diavola 169 Kč</p><p>Pátek: Quattro formaggi 179 Kč</p>""",
                             """<h4>Po</h4><p>Margherita 149 Kč</p><h4>Čt</h4><p>Diavola 169 Kč</p><p>Prosciutto 179 Kč</p>""")
    url = "https://lastrada.example/poledni-menu/"
    r = run_fetch({url: page}, url, also=["pizz"])
    pizza = [s for s in r.sections if "pizz" in s.name.lower()]
    assert [(i.name, i.price) for i in pizza[0].items] == [("Diavola", 169.0), ("Prosciutto", 179.0)]


# --- Shapes from real cards (screenshots of 15.10.2026)

U_DREVAKA = """<html><body><main><h1>Polední menu</h1>
<p><strong>Středa 14.10.</strong> Polévka: Gulášová (1,9)</p><p>1) Svíčková na smetaně, knedlík (1,3,7,9,10), 150g 174 Kč</p>
<p><strong>Čtvrtek 15.10.</strong> Polévka: Hovězí vývar s nudlemi (1,3,9)</p>
<p>1) Thajské červené kari s kuřecím masem, kokosovým mlékem, jasmínová rýže (1,3,6,7,9,10), 120g 174 Kč</p>
<p>2) Smažené řízečky z vepřové kotletky, bramborová máslová kaše, salátek (1,3,6,7,9), 150g 174 Kč</p>
<p>3) Little Chef Burger (Hovězí maso, Chedar, grilovaná cibulka, salát, dresink) hranolky a dresink (1,3,6,7,9), 80g 214 Kč</p>
<p>4) Grilovaná kuřecí prsíčka s cheddarovou omáčkou, americké brambory (1,3,6,7,9), 140g 184 Kč</p>
<p><strong>Pátek 16.10.</strong> Polévka: Bramborová s kořenovou zeleninou (1,6,9)</p>
<p>1) Smažený sýr s máslovými bramborami, naše tatarská omáčka (1,3,6,7,9), 100g 174 Kč</p>
<p>2) Gangster Bowl - menu version (8 hodin pečené vepřové maso) (1,3,6,7,9,10,12), 100g 174 Kč</p>
</main></body></html>"""


def test_u_drevaka_day_heading_glued_to_soup():
    url = "https://drevak.example/menu/pages/poledni-menu"
    r = run_fetch({url: U_DREVAKA}, url)
    assert r.error is None, r.error
    [sec] = r.sections
    assert sec.name == "Čtvrtek 15.10."
    names = [i.name for i in sec.items]
    assert names[0] == "Polévka: Hovězí vývar s nudlemi (1,3,9)"
    assert len(names) == 5 and names[-1].startswith("4) Grilovaná")
    assert not any("Smažený sýr" in n or "Bramborová s kořenovou" in n for n in names)


def test_name_day_is_not_part_of_the_menu():
    lines = ["Obědová nabídka", "Středa: svátek má Tereza", "Polévka: Česnečka", "150 g Kuře na paprice 189 Kč",
             "Čtvrtek: svátek má Tereza", "0,2 l Drůbeží vývar s masem a nudlemi", "Svátek má Tereza",
             "150 g Plněný paprikový lusk, rajská omáčka, těstovina 189 Kč",
             "150 g Hovězí guláš, kynutý knedlík 189 Kč", "Pátek: Svátek slaví Lukáš", "150 g Řízek 189 Kč"]
    from app.scrapers.html_generic import sections_from_lines
    [sec] = sections_from_lines(lines, THURSDAY, relaxed=True)
    assert sec.name == "Čtvrtek"
    assert [i.name for i in sec.items][0] == "0,2 l Drůbeží vývar s masem a nudlemi"
    assert not any("svátek" in i.name.lower() for i in sec.items)


LA_STRADA_REAL = """<html><body><main><h1>Polední menu 12.10. - 16.10.</h1>
<h3>Pizza týdne</h3>
<p>Pizza Primavera (rajčatový základ, mozzarella, cherry, kukuřice, špenát) 179 Kč</p>
<p>Po dobu poledního menu zvýhodněná cena čepovaného piva Pilsner Urquell 0,3 l 39 Kč</p>
<p>zvýhodněná cena čepovaného nealkoholického piva 0,3 l 29 Kč</p>
<p>Kohoutková voda zdarma po celou dobu menu!!</p>
<p>V době poledního menu zvýhodněná cena pizzy na odnos:</p><p>Pizza z La Strady za 145 Kč</p>
<p>Cena je včetně menu boxu a platí při objednávce min. 2 ks!!</p>
<p>Bezlepková pizza v době poledního menu + 35 Kč</p>
<p>Doporučujeme objednávky dopředu telefonicky na tel 773 222 211</p>
<p>Doprodej poledního menu v době od 15:00 do 18:00</p><p>neprodané obědové menu 1 a 4 za 89 Kč</p>
<p>```</p>
<p>MENU 1, 2 165 Kč</p><p>MENU 3, 4 175 Kč</p><p>Cena menu je včetně polévky.</p>
<p>Po 12.10.</p><p>Čočková polévka s párkem</p>
<p>1) Spaghetti Aglio e Olio &amp; Pollo s kuřecím masem, sušenými rajčaty, parmezánem a rukolou</p>
<p>2) Hovězí guláš, houskový knedlík</p>
<p>Čt 15.10.</p><p>Kulajda s vejcem</p>
<p>1) Penne all'arrabbiata s kuřecím masem</p><p>2) Smažený vepřový řízek, bramborový salát</p>
<p>3) Risotto ai funghi s parmezánem</p><p>4) Grilovaný losos, zeleninové rizoto</p>
<p>Pá 16.10.</p><p>Rybí polévka</p><p>1) Lasagne alla bolognese</p>
</main></body></html>"""


def test_la_strada_today_with_prices_from_menu_table_and_only_the_pizza():
    url = "https://lastrada.example/poledni-menu/"
    r = run_fetch({url: LA_STRADA_REAL}, url, also=["pizz"])
    assert r.error is None, r.error
    day, pizza = r.sections
    assert day.name == "Čt 15.10."
    assert [(i.name, i.price) for i in day.items] == [
        ("Kulajda s vejcem", None),
        ("1) Penne all'arrabbiata s kuřecím masem", 165.0),
        ("2) Smažený vepřový řízek, bramborový salát", 165.0),
        ("3) Risotto ai funghi s parmezánem", 175.0),
        ("4) Grilovaný losos, zeleninové rizoto", 175.0)]
    assert [(i.name, i.price) for i in pizza.items] == [
        ("Pizza Primavera (rajčatový základ, mozzarella, cherry, kukuřice, špenát)", 179.0)]
