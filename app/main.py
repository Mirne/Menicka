"""Menicka: daily lunch menus from your restaurants + who wants to go where."""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from . import db
from .scrapers import KINDS, detect_kind, fetch_menu

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
log = logging.getLogger("menicka")

TZ = ZoneInfo(os.environ.get("TZ", "Europe/Prague"))
REFRESH_MINUTES = int(os.environ.get("REFRESH_MINUTES", "30"))
RESTAURANTS_FILE = Path(os.environ.get("RESTAURANTS_FILE", "restaurants.yaml"))
STATIC = Path(__file__).parent / "static"

# restaurant id -> {"fetched_at": iso, "day": "YYYY-MM-DD", "result": dict}
_cache: dict[int, dict] = {}
_lock = asyncio.Lock()


def now() -> datetime:
    return datetime.now(TZ)


def today() -> str:
    return now().date().isoformat()


def seed_restaurants() -> None:
    if not RESTAURANTS_FILE.exists():
        log.info("no %s, skipping seed", RESTAURANTS_FILE)
        return
    data = yaml.safe_load(RESTAURANTS_FILE.read_text(encoding="utf-8")) or {}
    for r in data.get("restaurants", []):
        db.upsert_restaurant(r["name"], r["url"], r.get("kind", "auto"), r.get("selector"))


async def refresh_one(r: dict) -> dict:
    result = await fetch_menu(r["url"], r.get("kind") or "auto", r.get("selector"), today=now().date())
    entry = {"fetched_at": now().isoformat(timespec="seconds"), "day": today(), "result": result.to_dict()}
    _cache[r["id"]] = entry
    return entry


async def refresh_all() -> None:
    async with _lock:
        rs = db.list_restaurants()
        await asyncio.gather(*(refresh_one(r) for r in rs))
        log.info("refreshed %d restaurants", len(rs))


async def refresh_loop() -> None:
    while True:
        try:
            await refresh_all()
        except Exception:
            log.exception("refresh failed")
        await asyncio.sleep(REFRESH_MINUTES * 60)


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init()
    seed_restaurants()
    task = asyncio.create_task(refresh_loop()) if os.environ.get("DISABLE_REFRESH") != "1" else None
    yield
    if task:
        task.cancel()


app = FastAPI(title="Menicka", lifespan=lifespan)


class RestaurantIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    url: str = Field(min_length=8, max_length=500)
    kind: str = "auto"
    selector: str | None = Field(default=None, max_length=200)

    @field_validator("url")
    @classmethod
    def http_url(cls, v: str) -> str:
        v = v.strip()
        if not v.startswith(("http://", "https://")):
            raise ValueError("URL musí začínať http:// alebo https://")
        return v

    @field_validator("kind")
    @classmethod
    def known_kind(cls, v: str) -> str:
        if v not in KINDS:
            raise ValueError(f"kind musí byť jedno z {KINDS}")
        return v


class VoteIn(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    restaurant_id: int
    note: str = Field(default="", max_length=120)


def restaurant_view(r: dict) -> dict:
    return {**r, "detected_kind": detect_kind(r["url"]) if r["kind"] == "auto" else r["kind"]}


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


@app.get("/api/restaurants")
def get_restaurants() -> list[dict]:
    return [restaurant_view(r) for r in db.list_restaurants()]


@app.post("/api/restaurants", status_code=201)
async def add_restaurant(body: RestaurantIn) -> dict:
    r = db.upsert_restaurant(body.name.strip(), body.url, body.kind, (body.selector or "").strip() or None)
    await refresh_one(r)
    return restaurant_view(r)


@app.delete("/api/restaurants/{rid}", status_code=204)
def remove_restaurant(rid: int) -> None:
    if not db.delete_restaurant(rid):
        raise HTTPException(404, "Reštaurácia neexistuje")
    _cache.pop(rid, None)


@app.get("/api/menus")
async def get_menus() -> list[dict]:
    rs = db.list_restaurants()
    stale = [r for r in rs if r["id"] not in _cache or _cache[r["id"]]["day"] != today()]
    if stale:
        await asyncio.gather(*(refresh_one(r) for r in stale))
    return [{"restaurant": restaurant_view(r), **_cache[r["id"]]} for r in rs if r["id"] in _cache]


@app.post("/api/menus/refresh")
async def post_refresh() -> dict:
    await refresh_all()
    return {"ok": True, "fetched_at": now().isoformat(timespec="seconds")}


@app.get("/api/votes")
def get_votes() -> dict:
    return {"day": today(), "votes": db.list_votes(today())}


@app.post("/api/votes")
def post_vote(body: VoteIn) -> dict:
    if not db.get_restaurant(body.restaurant_id):
        raise HTTPException(404, "Reštaurácia neexistuje")
    db.set_vote(today(), body.name.strip(), body.restaurant_id, body.note.strip())
    return get_votes()


@app.delete("/api/votes/{name}")
def remove_vote(name: str) -> dict:
    db.delete_vote(today(), name.strip())
    return get_votes()


app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")
