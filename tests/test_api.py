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

    async def fake_fetch(url, kind="auto", selector=None, today=None, client=None):
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


def test_add_and_delete_restaurant(client):
    r = client.post("/api/restaurants", json={"name": "C", "url": "https://c.cz/menu"})
    assert r.status_code == 201
    rid = r.json()["id"]
    assert client.post("/api/restaurants", json={"name": "D", "url": "ftp://x"}).status_code == 422
    client.post("/api/votes", json={"name": "Ja", "restaurant_id": rid})
    assert client.delete(f"/api/restaurants/{rid}").status_code == 204
    assert client.get("/api/votes").json()["votes"] == []


def test_index_served(client):
    assert "Menučka" in client.get("/").text
