"""SQLite storage: the scraped books, what changed, and an audit log of every request.

Tables
  runs        one row per crawl: when, what, why it stopped
  fetch_log   one row per URL we tried: outcome, status, attempts, latency, bytes
  books       one row per book URL (the primary key), newest version wins
  changes     field-level history: 'price_pence went 5177 -> 4999 in run 3'
  rejects     pages we fetched but couldn't turn into a valid book, with reasons
  http_cache  last body + ETag/Last-Modified per URL, for conditional GETs
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime

from .fetcher import CachedPage, FetchResult

ITEM_FIELDS = ("upc", "title", "category", "price_pence", "rating", "in_stock",
               "stock_count", "description")

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at    TEXT NOT NULL,
    finished_at   TEXT,
    start_url     TEXT NOT NULL,
    profile       TEXT NOT NULL,
    settings_json TEXT NOT NULL,
    stop_reason   TEXT
);
CREATE TABLE IF NOT EXISTS fetch_log (
    run_id      INTEGER NOT NULL REFERENCES runs(run_id),
    seq         INTEGER NOT NULL,
    kind        TEXT NOT NULL,      -- 'listing' or 'item'
    url         TEXT NOT NULL,
    final_url   TEXT NOT NULL,
    outcome     TEXT NOT NULL,
    status      INTEGER,
    attempts    INTEGER NOT NULL,
    retries     INTEGER NOT NULL,
    redirects   INTEGER NOT NULL,
    elapsed_ms  REAL NOT NULL,
    bytes       INTEGER NOT NULL,
    error       TEXT,
    PRIMARY KEY (run_id, seq)
);
CREATE TABLE IF NOT EXISTS books (
    url              TEXT PRIMARY KEY,
    upc              TEXT,
    title            TEXT NOT NULL,
    category         TEXT,
    price_pence      INTEGER NOT NULL,
    rating           INTEGER,
    in_stock         INTEGER,
    stock_count      INTEGER,
    description      TEXT,
    content_hash     TEXT NOT NULL,
    parser_version   TEXT NOT NULL,     -- which profile code produced these values
    first_seen_run   INTEGER NOT NULL,
    last_seen_run    INTEGER NOT NULL,
    last_changed_run INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS changes (
    run_id    INTEGER NOT NULL,
    url       TEXT NOT NULL,
    field     TEXT NOT NULL,
    old_value TEXT,
    new_value TEXT
);
CREATE TABLE IF NOT EXISTS rejects (
    run_id  INTEGER NOT NULL,
    url     TEXT NOT NULL,
    reasons TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS http_cache (
    url           TEXT PRIMARY KEY,
    etag          TEXT,
    last_modified TEXT,
    encoding      TEXT,
    body          BLOB NOT NULL
);
"""


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def content_hash(item: dict) -> str:
    """Fingerprint of the fields we care about: same hash = nothing changed."""
    payload = json.dumps([item.get(f) for f in ITEM_FIELDS], ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()


class Store:
    def __init__(self, path: str = "scraper.db"):
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self._seq = 0

    # -- runs ---------------------------------------------------------------------------
    def start_run(self, start_url: str, profile: str, settings: dict) -> int:
        cur = self.conn.execute(
            "INSERT INTO runs (started_at, start_url, profile, settings_json) VALUES (?, ?, ?, ?)",
            (utc_now(), start_url, profile, json.dumps(settings, default=str)),
        )
        self.conn.commit()
        self._seq = 0
        return cur.lastrowid

    def finish_run(self, run_id: int, stop_reason: str) -> None:
        self.conn.execute("UPDATE runs SET finished_at = ?, stop_reason = ? WHERE run_id = ?",
                          (utc_now(), stop_reason, run_id))
        self.conn.commit()

    # -- audit log ------------------------------------------------------------------------
    def log_fetch(self, run_id: int, kind: str, r: FetchResult) -> None:
        self._seq += 1
        self.conn.execute(
            "INSERT INTO fetch_log VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (run_id, self._seq, kind, r.url, r.final_url, r.outcome, r.status or None,
             r.attempts, r.retries, r.redirects, round(r.elapsed_ms, 3), r.bytes_received, r.error),
        )

    def log_reject(self, run_id: int, url: str, reasons: list[str]) -> None:
        self.conn.execute("INSERT INTO rejects VALUES (?, ?, ?)", (run_id, url, "; ".join(reasons)))

    # -- books ----------------------------------------------------------------------------
    def upsert_book(self, run_id: int, item: dict, parser_version: str = "") -> str:
        """Insert, update, or just mark as seen. Returns 'new', 'changed' or 'unchanged'."""
        new_hash = content_hash(item)
        row = self.conn.execute("SELECT * FROM books WHERE url = ?", (item["url"],)).fetchone()
        if row is None:
            self.conn.execute(
                f"INSERT INTO books (url, {', '.join(ITEM_FIELDS)}, content_hash, parser_version, "
                "first_seen_run, last_seen_run, last_changed_run) "
                f"VALUES (?, {', '.join('?' for _ in ITEM_FIELDS)}, ?, ?, ?, ?, ?)",
                (item["url"], *[item[f] for f in ITEM_FIELDS], new_hash, parser_version,
                 run_id, run_id, run_id),
            )
            return "new"
        if row["content_hash"] == new_hash:
            self.conn.execute("UPDATE books SET last_seen_run = ?, parser_version = ? WHERE url = ?",
                              (run_id, parser_version, item["url"]))
            return "unchanged"
        for f in ITEM_FIELDS:  # record exactly which fields moved
            if row[f] != item[f]:
                self.conn.execute("INSERT INTO changes VALUES (?, ?, ?, ?, ?)",
                                  (run_id, item["url"], f, _s(row[f]), _s(item[f])))
        assignments = ", ".join(f"{f} = ?" for f in ITEM_FIELDS)
        self.conn.execute(
            f"UPDATE books SET {assignments}, content_hash = ?, parser_version = ?, last_seen_run = ?, "
            "last_changed_run = ? WHERE url = ?",
            (*[item[f] for f in ITEM_FIELDS], new_hash, parser_version, run_id, run_id, item["url"]),
        )
        return "changed"

    def mark_seen(self, run_id: int, url: str, parser_version: str) -> bool:
        """Page came back 304 Not Modified: if we already hold this book, parsed by this same
        parser, it can't have changed. Mark it seen and skip parsing. False = parse it."""
        cur = self.conn.execute(
            "UPDATE books SET last_seen_run = ? WHERE url = ? AND parser_version = ?",
            (run_id, url, parser_version))
        return cur.rowcount == 1

    def commit(self) -> None:
        self.conn.commit()

    # -- http cache (the Fetcher's Cache protocol) ----------------------------------------
    def cache_get(self, url: str) -> CachedPage | None:
        row = self.conn.execute(
            "SELECT body, encoding, etag, last_modified FROM http_cache WHERE url = ?", (url,)
        ).fetchone()
        return CachedPage(row["body"], row["encoding"], row["etag"], row["last_modified"]) if row else None

    def cache_put(self, url: str, page: CachedPage) -> None:
        self.conn.execute(
            "INSERT INTO http_cache (url, etag, last_modified, encoding, body) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(url) DO UPDATE SET etag = excluded.etag, "
            "last_modified = excluded.last_modified, encoding = excluded.encoding, body = excluded.body",
            (url, page.etag, page.last_modified, page.encoding, page.body),
        )

    def close(self) -> None:
        self.conn.commit()
        self.conn.close()


def _s(value) -> str | None:
    return None if value is None else str(value)
