"""
SQLite connection and schema initialisation.
Uses Python's built-in sqlite3 — no ORM needed for this project.
"""
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from octocoupon.config import settings

DB_PATH = Path(settings.db_path).expanduser()
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS advertisers (
    id          TEXT PRIMARY KEY,
    network     TEXT NOT NULL,
    name        TEXT NOT NULL,
    url         TEXT,
    country     TEXT NOT NULL,
    logo_url    TEXT,
    raw_json    TEXT,
    synced_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS coupons (
    id            TEXT PRIMARY KEY,
    advertiser_id TEXT NOT NULL REFERENCES advertisers(id),
    network       TEXT NOT NULL,
    country       TEXT NOT NULL,
    title         TEXT NOT NULL,
    description   TEXT,
    code          TEXT,
    discount      TEXT,
    start_date    TEXT,
    end_date      TEXT,
    affiliate_url TEXT NOT NULL,
    raw_json      TEXT,
    synced_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS wp_posts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    coupon_id    TEXT NOT NULL REFERENCES coupons(id),
    country      TEXT NOT NULL,
    wp_post_id   INTEGER NOT NULL,
    wp_url       TEXT,
    published_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(coupon_id, country)
);

CREATE TABLE IF NOT EXISTS social_posts (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    wp_post_id       INTEGER NOT NULL REFERENCES wp_posts(id),
    platform         TEXT NOT NULL,
    platform_post_id TEXT,
    status           TEXT NOT NULL DEFAULT 'pending',
    posted_at        TEXT,
    error            TEXT,
    UNIQUE(wp_post_id, platform)
);
"""


def init_db() -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript(SCHEMA)


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
