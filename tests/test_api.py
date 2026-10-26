import importlib

import pytest
from fastapi.testclient import TestClient

from app.scrapers.base import MenuItem, MenuResult, MenuSection


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DISABLE_REFRESH", "1")
    cfg = tmp_path / "r.yaml"
    cfg.write_text("restaurants:\n  - name: A\n    url: https://a.choiceqr.com\n  - name: B\n    url: https://b.cz\n"
                   "  - name: Pho Eden\n")
    monkeypatch.setenv("RESTAURANTS_FILE", str(cfg))
    import app.db, app.main
    importlib.reload(app.db)
    main = importlib.reload(app.main)

    async def fake_fetch(url, kind="auto", selector=None, today=None, client=None, daily_section=None, also=None):
        return MenuResult(sections=[MenuSection("Denní menu", [MenuItem("Jídlo", 150)], True)], source_url=url)

    monkeypatch.setattr(main, "fetch_menu", fake_fetch)
    with TestClient(main.app) as c:
        yield c


def test_restaurants_seeded_and_kind_detected(client):
    rs = client.get("/api/restaurants").json()
    assert [(r["name"], r["has_menu"]) for r in rs] == [
        ("A", True), ("B", True), ("Pho Eden", False), ("Iné", False), ("Nejdem na obed", False)]
    assert [r["detected_kind"] for r in rs[:2]] == ["choiceqr", "html"]


def test_menus(client):
    menus = client.get("/api/menus").json()
    assert [m["restaurant"]["name"] for m in menus] == ["A", "B"]  # Pho Eden has no menu card
    assert menus[0]["result"]["sections"][0]["items"][0] == {"name": "Jídlo", "price": 150, "description": ""}


def test_votes_several_restaurants_per_person(client):
    a, b = [r["id"] for r in client.get("/api/restaurants").json()[:2]]
    v = client.post("/api/votes", json={"name": "Robo", "restaurant_ids": [a, b]}).json()
    assert sorted((x["name"], x["restaurant_id"]) for x in v["votes"]) == [("Robo", a), ("Robo", b)]
    # the list replaces the person's choices; the name is case-insensitive
    v = client.post("/api/votes", json={"name": "robo", "restaurant_ids": [b]}).json()
    assert [(x["name"], x["restaurant_id"]) for x in v["votes"]] == [("robo", b)]
    assert client.post("/api/votes", json={"name": "X", "restaurant_ids": [999]}).status_code == 404
    assert client.post("/api/votes", json={"name": "Robo", "restaurant_ids": []}).json()["votes"] == []
    client.post("/api/votes", json={"name": "Robo", "restaurant_ids": [a, b]})
    assert client.delete("/api/votes/ROBO").json()["votes"] == []


def test_not_going_excludes_restaurants(client):
    rs = client.get("/api/restaurants").json()
    skip = [r["id"] for r in rs if r["skip"]][0]
    v = client.post("/api/votes", json={"name": "Jana", "restaurant_ids": [rs[0]["id"], skip]}).json()
    assert [x["restaurant_id"] for x in v["votes"]] == [skip]


def test_old_votes_table_is_migrated(tmp_path, monkeypatch):
    import sqlite3
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    con = sqlite3.connect(tmp_path / "menicka.db")
    con.executescript("""
        CREATE TABLE restaurants (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, url TEXT NOT NULL UNIQUE,
            kind TEXT NOT NULL DEFAULT 'auto', selector TEXT, created_at TEXT NOT NULL DEFAULT (datetime('now')));
        CREATE TABLE votes (id INTEGER PRIMARY KEY AUTOINCREMENT, day TEXT NOT NULL, name TEXT NOT NULL,
            name_key TEXT NOT NULL, restaurant_id INTEGER NOT NULL REFERENCES restaurants(id) ON DELETE CASCADE,
            note TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL DEFAULT (datetime('now')), UNIQUE (day, name_key));
        INSERT INTO restaurants (name, url) VALUES ('A', 'https://a.cz'), ('B', 'https://b.cz');
        INSERT INTO votes (day, name, name_key, restaurant_id) VALUES ('2026-10-16', 'Robo', 'robo', 1);""")
    con.commit(); con.close()
    import app.db
    db = importlib.reload(app.db)
    db.init()
    db.set_vote("2026-10-16", "Robo", 2)  # a second choice is now allowed
    assert [(v["name"], v["restaurant_id"]) for v in db.list_votes("2026-10-16")] == [("Robo", 1), ("Robo", 2)]

def test_yaml_is_the_list_of_restaurants(client, tmp_path, monkeypatch):
    import app.main as main
    rs = client.get("/api/restaurants").json()
    client.post("/api/votes", json={"name": "Ja", "restaurant_ids": [rs[1]["id"]]})
    cfg = tmp_path / "r.yaml"
    cfg.write_text("restaurants:\n  - name: A2\n    url: https://a.choiceqr.com\n"
                   "  - name: C\n    url: https://c.cz\n    daily_section: Lunch\n    also: [pizz, dezert]\n")
    main.seed_restaurants()
    rs = client.get("/api/restaurants").json()
    assert [(r["name"], r["daily_section"], r["also"]) for r in rs] == [
        ("A2", None, None), ("C", "Lunch", "pizz, dezert"), ("Iné", None, None), ("Nejdem na obed", None, None)]
    assert client.get("/api/votes").json()["votes"] == []  # B and its vote are gone


def test_restaurants_cannot_be_added_over_http(client):
    assert client.post("/api/restaurants", json={"name": "X", "url": "https://x.cz"}).status_code == 405


def test_index_served(client):
    html = client.get("/").text
    assert "<title>Menu</title>" in html and "<h1>Menu <span" in html


def test_source_download(client, monkeypatch):
    import app.main as main

    async def fake_html(url, client=None):
        return "<html>raw</html>"

    monkeypatch.setattr(main, "fetch_html", fake_html)
    rid = client.get("/api/restaurants").json()[0]["id"]
    r = client.get(f"/api/restaurants/{rid}/source")
    assert r.text == "<html>raw</html>"
    assert 'filename="a.html"' in r.headers["content-disposition"]


def test_old_database_gets_new_column(tmp_path, monkeypatch):
    import sqlite3
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    con = sqlite3.connect(tmp_path / "menicka.db")
    con.execute("CREATE TABLE restaurants (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, "
                "url TEXT NOT NULL UNIQUE, kind TEXT NOT NULL DEFAULT 'auto', selector TEXT, "
                "created_at TEXT NOT NULL DEFAULT (datetime('now')))")
    con.commit(); con.close()
    import app.db
    db = importlib.reload(app.db)
    db.init()
    assert db.upsert_restaurant("X", "https://x.cz", daily_section="Menu dne")["daily_section"] == "Menu dne"


def test_vote_only_restaurant(client):
    pho = [r for r in client.get("/api/restaurants").json() if r["name"] == "Pho Eden"][0]
    v = client.post("/api/votes", json={"name": "Jana", "restaurant_ids": [pho["id"]]}).json()
    assert v["votes"][0]["restaurant_id"] == pho["id"]
    assert client.get(f"/api/restaurants/{pho['id']}/source").status_code == 404
    import app.main as main
    main.seed_restaurants()  # restarting does not duplicate it
    assert [r["name"] for r in client.get("/api/restaurants").json()].count("Pho Eden") == 1


def test_day_titles_are_dropped():
    from datetime import date
    from app.scrapers import drop_day_titles
    from app.scrapers.base import MenuResult, MenuSection
    names = ["Čtvrtek", "Čtvrtek/ Thursday", "Čt 15.10.", "Čtvrtek 15.10.", "Denní menu", "Výběr pizz k polednímu menu", "Polévky"]
    r = drop_day_titles(MenuResult(sections=[MenuSection(n) for n in names]), date(2026, 10, 15))
    assert [s.name for s in r.sections] == ["", "", "", "", "Denní menu", "Výběr pizz k polednímu menu", "Polévky"]


def test_not_going_option(client):
    rs = client.get("/api/restaurants").json()
    skip = rs[-1]
    assert (skip["name"], skip["skip"], skip["has_menu"]) == ("Nejdem na obed", True, False)
    v = client.post("/api/votes", json={"name": "Peter", "restaurant_ids": [skip["id"]]}).json()
    assert v["votes"][0]["restaurant_id"] == skip["id"]
    assert "Nejdem na obed" not in [m["restaurant"]["name"] for m in client.get("/api/menus").json()]
    import app.main as main
    main.seed_restaurants()  # stays one option, keeps the vote
    rs2 = client.get("/api/restaurants").json()
    assert [r["name"] for r in rs2].count("Nejdem na obed") == 1 and rs2[-1]["id"] == skip["id"]
    assert len(client.get("/api/votes").json()["votes"]) == 1


def test_votes_from_previous_days_are_cleared(client):
    import app.db as db
    import app.main as main
    rid = client.get("/api/restaurants").json()[0]["id"]
    db.set_vote("2020-01-01", "Stary", rid)
    client.post("/api/votes", json={"name": "Dnes", "restaurant_ids": [rid]})
    v = client.get("/api/votes").json()
    assert v["day"] == main.today() and [x["name"] for x in v["votes"]] == ["Dnes"]
    with db.connect() as c:
        assert [r[0] for r in c.execute("SELECT name FROM votes")] == ["Dnes"]


def test_new_day_starts_empty(client, monkeypatch):
    import app.main as main
    rid = client.get("/api/restaurants").json()[0]["id"]
    client.post("/api/votes", json={"name": "Robo", "restaurant_ids": [rid]})
    monkeypatch.setattr(main, "today", lambda: "2099-01-02")
    assert client.get("/api/votes").json() == {"day": "2099-01-02", "votes": []}


def test_other_option_combines_with_restaurants(client):
    rs = client.get("/api/restaurants").json()
    other = [r for r in rs if r["other"]][0]
    assert (other["name"], other["has_menu"], rs[-2]["id"]) == ("Iné", False, other["id"])  # before "Nejdem"
    v = client.post("/api/votes", json={"name": "Eva", "restaurant_ids": [rs[0]["id"], other["id"]]}).json()
    assert sorted(x["restaurant_id"] for x in v["votes"]) == sorted([rs[0]["id"], other["id"]])
    assert "Iné" not in [m["restaurant"]["name"] for m in client.get("/api/menus").json()]


def test_other_note_is_saved_edited_and_preserved(client):
    rs = client.get("/api/restaurants").json()
    other = next(r["id"] for r in rs if r["other"])
    regular = rs[0]["id"]
    payload = {"name": "Eva", "restaurant_ids": [other, regular], "other_note": "  Bistro pri práci  "}
    response = client.post("/api/votes", json=payload)
    assert response.status_code == 200
    by_id = {v["restaurant_id"]: v for v in client.get("/api/votes").json()["votes"]}
    assert by_id[other]["note"] == "Bistro pri práci"
    assert by_id[regular]["note"] == ""
    # Older clients that omit the new field must preserve an existing note.
    client.post("/api/votes", json={"name": "eva", "restaurant_ids": [other]})
    assert client.get("/api/votes").json()["votes"][0]["note"] == "Bistro pri práci"
    payload.update(other_note="Iné bistro", restaurant_ids=[other])
    assert client.post("/api/votes", json=payload).json()["votes"][0]["note"] == "Iné bistro"
    payload["other_note"] = ""
    assert client.post("/api/votes", json=payload).json()["votes"][0]["note"] == ""


def test_other_note_is_personal_and_removed_with_the_choice(client):
    rs = client.get("/api/restaurants").json()
    other = next(r["id"] for r in rs if r["other"])
    skip = next(r["id"] for r in rs if r["skip"])
    for name, note in [("Eva", "Bistro"), ("Robo", "Doma")]:
        client.post("/api/votes", json={"name": name, "restaurant_ids": [other], "other_note": note})
    client.post("/api/votes", json={"name": "Eva", "restaurant_ids": [skip, other], "other_note": "Bistro"})
    votes = client.get("/api/votes").json()["votes"]
    assert sorted((v["name"], v["note"]) for v in votes) == [("Eva", ""), ("Robo", "Doma")]
    client.post("/api/votes", json={"name": "Eva", "restaurant_ids": [other]})
    assert next(v for v in client.get("/api/votes").json()["votes"] if v["name"] == "Eva")["note"] == ""
    assert client.post("/api/votes", json={"name": "Eva", "restaurant_ids": [other], "other_note": "x" * 201}).status_code == 422



def test_index_versions_all_assets_and_revalidates_html(client, tmp_path, monkeypatch):
    import hashlib
    import app.main as main
    from bs4 import BeautifulSoup
    first = client.get("/")
    assert first.headers["cache-control"] == "no-cache"
    assets = ("style.css", "i18n.js", "app.js")
    version = hashlib.sha256(b"".join((main.STATIC / f).read_bytes() for f in assets)).hexdigest()[:16]
    for filename in assets:
        assert f"/static/{filename}?v={version}" in first.text
        assert client.get(f"/static/{filename}?v={version}").status_code == 200
    # A deployment changing one asset changes the URLs of the whole bundle.
    for filename in (*assets, "index.html"):
        (tmp_path / filename).write_bytes((main.STATIC / filename).read_bytes())
    with (tmp_path / "i18n.js").open("a") as f:
        f.write("\n// updated translations")
    monkeypatch.setattr(main, "STATIC", tmp_path)
    second = client.get("/")
    assert f"?v={version}" not in second.text
    details = BeautifulSoup(second.text, "lxml").select_one("#other-details")
    assert details.has_attr("hidden")
    assert "row" not in details.get("class", [])  # cached .row CSS must not override hidden
