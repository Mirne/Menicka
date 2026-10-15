import importlib

import pytest
from fastapi.testclient import TestClient

from app.scrapers.base import MenuItem, MenuResult, MenuSection


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DISABLE_REFRESH", "1")
    cfg = tmp_path / "r.yaml"
    cfg.write_text("restaurants:\n  - name: A\n    url: https://a.choiceqr.com\n  - name: B\n    url: https://b.cz\n")
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
    assert [(r["name"], r["detected_kind"]) for r in rs] == [("A", "choiceqr"), ("B", "html")]


def test_menus(client):
    menus = client.get("/api/menus").json()
    assert len(menus) == 2
    assert menus[0]["result"]["sections"][0]["items"][0] == {"name": "Jídlo", "price": 150, "description": ""}


def test_votes_one_per_person_per_day(client):
    rs = client.get("/api/restaurants").json()
    client.post("/api/votes", json={"name": "Robo", "restaurant_id": rs[0]["id"]})
    v = client.post("/api/votes", json={"name": "robo", "restaurant_id": rs[1]["id"], "note": "12:00"}).json()
    assert [(x["name"], x["restaurant_id"], x["note"]) for x in v["votes"]] == [("robo", rs[1]["id"], "12:00")]
    assert client.post("/api/votes", json={"name": "X", "restaurant_id": 999}).status_code == 404
    assert client.delete("/api/votes/ROBO").json()["votes"] == []


def test_yaml_is_the_list_of_restaurants(client, tmp_path, monkeypatch):
    import app.main as main
    rs = client.get("/api/restaurants").json()
    client.post("/api/votes", json={"name": "Ja", "restaurant_id": rs[1]["id"]})
    cfg = tmp_path / "r.yaml"
    cfg.write_text("restaurants:\n  - name: A2\n    url: https://a.choiceqr.com\n"
                   "  - name: C\n    url: https://c.cz\n    daily_section: Lunch\n    also: [pizz, dezert]\n")
    main.seed_restaurants()
    rs = client.get("/api/restaurants").json()
    assert [(r["name"], r["daily_section"], r["also"]) for r in rs] == [
        ("A2", None, None), ("C", "Lunch", "pizz, dezert")]
    assert client.get("/api/votes").json()["votes"] == []  # B and its vote are gone


def test_restaurants_cannot_be_added_over_http(client):
    assert client.post("/api/restaurants", json={"name": "X", "url": "https://x.cz"}).status_code == 405


def test_index_served(client):
    assert "Menučka" in client.get("/").text


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
