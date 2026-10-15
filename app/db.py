"""SQLite storage for restaurants and lunch preferences."""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DATA_DIR = Path(os.environ.get("DATA_DIR", "./data"))
DB_PATH = DATA_DIR / "menicka.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS restaurants (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    url TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL DEFAULT 'auto',
    selector TEXT,
    daily_section TEXT,
    also TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS votes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    day TEXT NOT NULL,
    name TEXT NOT NULL,
    name_key TEXT NOT NULL,
    restaurant_id INTEGER NOT NULL REFERENCES restaurants(id) ON DELETE CASCADE,
    note TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (day, name_key)
);
"""


@contextmanager
def connect():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init() -> None:
    with connect() as c:
        c.executescript(SCHEMA)
        cols = {r["name"] for r in c.execute("PRAGMA table_info(restaurants)")}
        for col in ("daily_section", "also"):  # databases created before these columns existed
            if col not in cols:
                c.execute(f"ALTER TABLE restaurants ADD COLUMN {col} TEXT")


def list_restaurants() -> list[dict]:
    with connect() as c:
        return [dict(r) for r in c.execute("SELECT * FROM restaurants ORDER BY id")]


def get_restaurant(rid: int) -> dict | None:
    with connect() as c:
        r = c.execute("SELECT * FROM restaurants WHERE id = ?", (rid,)).fetchone()
        return dict(r) if r else None


def upsert_restaurant(name: str, url: str, kind: str = "auto", selector: str | None = None,
                      daily_section: str | None = None, also: str | None = None) -> dict:
    with connect() as c:
        c.execute(
            """INSERT INTO restaurants (name, url, kind, selector, daily_section, also) VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(url) DO UPDATE SET name = excluded.name, kind = excluded.kind,
               selector = excluded.selector, daily_section = excluded.daily_section,
               also = excluded.also""",
            (name, url, kind, selector or None, daily_section or None, also or None),
        )
        return dict(c.execute("SELECT * FROM restaurants WHERE url = ?", (url,)).fetchone())


def delete_restaurant(rid: int) -> bool:
    with connect() as c:
        return c.execute("DELETE FROM restaurants WHERE id = ?", (rid,)).rowcount > 0


def set_vote(day: str, name: str, restaurant_id: int, note: str = "") -> None:
    with connect() as c:
        c.execute(
            """INSERT INTO votes (day, name, name_key, restaurant_id, note) VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(day, name_key) DO UPDATE SET name = excluded.name,
               restaurant_id = excluded.restaurant_id, note = excluded.note,
               updated_at = datetime('now')""",
            (day, name, name.casefold(), restaurant_id, note),
        )


def delete_vote(day: str, name: str) -> bool:
    with connect() as c:
        return c.execute("DELETE FROM votes WHERE day = ? AND name_key = ?", (day, name.casefold())).rowcount > 0


def list_votes(day: str) -> list[dict]:
    with connect() as c:
        return [dict(r) for r in c.execute(
            "SELECT name, restaurant_id, note, updated_at FROM votes WHERE day = ? ORDER BY updated_at",
            (day,),
        )]
