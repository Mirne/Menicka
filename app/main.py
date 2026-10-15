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
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import db
import httpx

from .scrapers import detect_kind, drop_day_titles, fetch_html, fetch_menu, parse_also

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
    rs = data.get("restaurants") or []
    for r in rs:
        # A restaurant without url is only a voting option (no menu to fetch).
        r["url"] = r.get("url") or f"vote-only:{r['name']}"
        db.upsert_restaurant(r["name"], r["url"], r.get("kind", "auto"), r.get("selector"),
                             r.get("daily_section"), ", ".join(parse_also(r.get("also"))))
    # restaurants.yaml is the list: whatever was removed from it goes away
    removed = db.keep_only_restaurants([r["url"] for r in rs])
    if removed:
        log.info("removed %d restaurants no longer in %s", removed, RESTAURANTS_FILE)


def has_menu(r: dict) -> bool:
    return r["url"].startswith(("http://", "https://"))


async def refresh_one(r: dict) -> dict:
    result = await fetch_menu(r["url"], r.get("kind") or "auto", r.get("selector"), today=now().date(),
                              daily_section=r.get("daily_section"), also=r.get("also"))
    drop_day_titles(result, now().date())
    entry = {"fetched_at": now().isoformat(timespec="seconds"), "day": today(), "result": result.to_dict()}
    _cache[r["id"]] = entry
    return entry


async def refresh_all() -> None:
    async with _lock:
        rs = [r for r in db.list_restaurants() if has_menu(r)]
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


class VoteIn(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    restaurant_id: int
    note: str = Field(default="", max_length=120)


def restaurant_view(r: dict) -> dict:
    return {**r, "has_menu": has_menu(r),
            "detected_kind": detect_kind(r["url"]) if r["kind"] == "auto" else r["kind"]}


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


@app.get("/api/restaurants")
def get_restaurants() -> list[dict]:
    return [restaurant_view(r) for r in db.list_restaurants()]


@app.get("/api/restaurants/{rid}/source")
async def restaurant_source(rid: int) -> Response:
    """The page HTML exactly as the server downloads it, to debug a parser."""
    r = db.get_restaurant(rid)
    if not r or not has_menu(r):
        raise HTTPException(404, "Reštaurácia neexistuje")
    try:
        html = await fetch_html(r["url"])
    except httpx.HTTPError as e:
        raise HTTPException(502, f"Stránku sa nepodarilo načítať: {e}")
    safe = "".join(ch if ch.isalnum() else "-" for ch in r["name"].lower()).strip("-") or "restauracia"
    return Response(html, media_type="text/html; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{safe}.html"'})


@app.get("/api/menus")
async def get_menus() -> list[dict]:
    rs = [r for r in db.list_restaurants() if has_menu(r)]
    if any(r["id"] not in _cache or _cache[r["id"]]["day"] != today() for r in rs):
        # Wait for a refresh already running instead of fetching (and OCR-ing) twice.
        async with _lock:
            stale = [r for r in rs if r["id"] not in _cache or _cache[r["id"]]["day"] != today()]
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
