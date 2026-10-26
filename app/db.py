"""SQLite storage for restaurants and lunch preferences."""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DATA_DIR = Path(os.environ.get("DATA_DIR", "./data"))
DB_PATH = DATA_DIR / "menicka.db"

RESTAURANTS_TABLE = """
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
"""
# One row per person, day and chosen restaurant (a person may pick several).
VOTES_TABLE = """
CREATE TABLE IF NOT EXISTS votes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    day TEXT NOT NULL,
    name TEXT NOT NULL,
    name_key TEXT NOT NULL,
    restaurant_id INTEGER NOT NULL REFERENCES restaurants(id) ON DELETE CASCADE,
    note TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (day, name_key, restaurant_id)
);
"""
SCHEMA = RESTAURANTS_TABLE + VOTES_TABLE


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
        votes_sql = c.execute("SELECT sql FROM sqlite_master WHERE name = 'votes'").fetchone()["sql"]
        if "name_key, restaurant_id" not in votes_sql:
            # Older databases allowed one vote per person and day: rebuild with the new key.
            c.executescript(
                "ALTER TABLE votes RENAME TO votes_old;" + VOTES_TABLE +
                """INSERT INTO votes (day, name, name_key, restaurant_id, note, updated_at)
                       SELECT day, name, name_key, restaurant_id, note, updated_at FROM votes_old;
                   DROP TABLE votes_old;"""
            )


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


def keep_only_restaurants(urls: list[str]) -> int:
    """Remove restaurants (and their votes) whose URL is not in the list."""
    with connect() as c:
        marks = ",".join("?" * len(urls)) or "''"
        return c.execute(f"DELETE FROM restaurants WHERE url NOT IN ({marks})", urls).rowcount


def delete_restaurant(rid: int) -> bool:
    with connect() as c:
        return c.execute("DELETE FROM restaurants WHERE id = ?", (rid,)).rowcount > 0


def set_votes(day: str, name: str, restaurant_ids: list[int], notes: dict[int, str] | None = None) -> None:
    """Replace a person's choices for the day (one or more restaurants, or none)."""
    key = name.casefold()
    with connect() as c:
        keep = list(dict.fromkeys(restaurant_ids))
        marks = ",".join("?" * len(keep))
        drop = f" AND restaurant_id NOT IN ({marks})" if keep else ""
        c.execute(f"DELETE FROM votes WHERE day = ? AND name_key = ?{drop}", (day, key, *keep))
        for rid in keep:
            c.execute(
                """INSERT INTO votes (day, name, name_key, restaurant_id) VALUES (?, ?, ?, ?)
                   ON CONFLICT(day, name_key, restaurant_id) DO UPDATE SET name = excluded.name""",
                (day, name, key, rid),
            )
            if notes is not None and rid in notes:
                c.execute("UPDATE votes SET note = ?, updated_at = datetime('now') "
                          "WHERE day = ? AND name_key = ? AND restaurant_id = ?",
                          (notes[rid], day, key, rid))


def update_vote_note(day: str, name: str, url: str, note: str) -> None:
    """Edit an existing choice without recreating a removed vote or changing other choices."""
    with connect() as c:
        c.execute("UPDATE votes SET note = ?, updated_at = datetime('now') "
                  "WHERE day = ? AND name_key = ? AND restaurant_id = "
                  "(SELECT id FROM restaurants WHERE url = ?)",
                  (note, day, name.casefold(), url))


def set_vote(day: str, name: str, restaurant_id: int) -> None:
    """Add one choice, keeping the others."""
    key = name.casefold()
    with connect() as c:
        c.execute(
            """INSERT INTO votes (day, name, name_key, restaurant_id) VALUES (?, ?, ?, ?)
               ON CONFLICT(day, name_key, restaurant_id) DO UPDATE SET name = excluded.name""",
            (day, name, key, restaurant_id),
        )


def delete_vote(day: str, name: str) -> bool:
    with connect() as c:
        return c.execute("DELETE FROM votes WHERE day = ? AND name_key = ?", (day, name.casefold())).rowcount > 0


def delete_votes_before(day: str) -> int:
    """Votes are for one day only: drop everything older."""
    with connect() as c:
        return c.execute("DELETE FROM votes WHERE day < ?", (day,)).rowcount


def list_votes(day: str) -> list[dict]:
    with connect() as c:
        return [dict(r) for r in c.execute(
            "SELECT name, restaurant_id, note, updated_at FROM votes WHERE day = ? ORDER BY updated_at, id",
            (day,),
        )]
