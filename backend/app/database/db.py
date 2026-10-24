"""Database access: local SQLite by default, Postgres (for example Supabase) when DATABASE_URL is set."""
from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from urllib.parse import urlparse

log = logging.getLogger("nid.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS scans (
    id              TEXT PRIMARY KEY,
    source          TEXT NOT NULL,              -- 'upload' | 'single'
    filename        TEXT,
    file_path       TEXT,
    size_bytes      INTEGER,
    status          TEXT NOT NULL,              -- uploaded | queued | running | completed | failed
    created_at      TEXT NOT NULL,
    started_at      TEXT,
    finished_at     TEXT,
    rows_total      INTEGER,
    rows_processed  INTEGER NOT NULL DEFAULT 0,
    error           TEXT,
    model_version   TEXT,
    validation_json TEXT,
    summary_json    TEXT
);

CREATE TABLE IF NOT EXISTS records (
    id                  TEXT PRIMARY KEY,
    scan_id             TEXT NOT NULL REFERENCES scans(id) ON DELETE CASCADE,
    row_index           INTEGER NOT NULL,
    processed_at        TEXT NOT NULL,
    event_time          TEXT NOT NULL,          -- flow timestamp when present, else processing time
    event_time_source   TEXT NOT NULL,          -- 'flow' | 'processed'
    predicted_class     TEXT NOT NULL,
    is_suspicious       INTEGER NOT NULL,
    attack_category     TEXT,
    confidence          DOUBLE PRECISION,
    risk_level          TEXT NOT NULL,
    requires_review     INTEGER NOT NULL,
    risk_rule_id        TEXT,
    risk_reason         TEXT,
    risk_evidence_json  TEXT,
    warnings_json       TEXT,
    ground_truth_label  TEXT,
    src_ip              TEXT,
    dst_ip              TEXT,
    dst_port            INTEGER,
    features_json       TEXT,
    review_status       TEXT NOT NULL DEFAULT 'new',   -- new | investigating | reviewed
    review_note         TEXT,
    reviewed_at         TEXT
);

CREATE INDEX IF NOT EXISTS idx_records_scan        ON records(scan_id);
CREATE INDEX IF NOT EXISTS idx_records_suspicious  ON records(is_suspicious);
CREATE INDEX IF NOT EXISTS idx_records_risk        ON records(risk_level);
CREATE INDEX IF NOT EXISTS idx_records_class       ON records(predicted_class);
CREATE INDEX IF NOT EXISTS idx_records_event_time  ON records(event_time);
CREATE INDEX IF NOT EXISTS idx_records_review      ON records(review_status);
"""


PG_SECURITY = """
-- Supabase exposes the public schema over its REST API. Row level security with no policies keeps these tables
-- private to the backend's own database role, which bypasses it.
ALTER TABLE scans ENABLE ROW LEVEL SECURITY;
ALTER TABLE records ENABLE ROW LEVEL SECURITY;
"""


def _normalize_url(url: str) -> str:
    url = url.strip()
    if "://" not in url:  # keyword-style conninfo built from DB_HOST / DB_USER / DB_PASSWORD
        return url
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    host = urlparse(url).hostname or ""
    if "sslmode=" not in url and host not in ("localhost", "127.0.0.1", "") and not host.startswith("/"):
        url += ("&" if "?" in url else "?") + "sslmode=require"  # hosted databases require TLS
    return url


class _PgConn:
    """Gives a psycopg connection the small sqlite3-style surface the repository uses ('?' placeholders)."""

    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql: str, params=()):
        cur = self._conn.cursor()
        cur.execute(sql.replace("?", "%s"), params or None)
        return cur

    def executemany(self, sql: str, rows):
        cur = self._conn.cursor()
        cur.executemany(sql.replace("?", "%s"), rows)
        return cur


class Database:
    def __init__(self, path: Path | None = None, url: str | None = None):
        self.path = path
        self.url = _normalize_url(url) if url else None
        self._pool = None

    @property
    def backend(self) -> str:
        return "postgres" if self.url else "sqlite"

    def describe(self) -> str:
        if self.url:
            if "://" not in self.url:
                from psycopg.conninfo import conninfo_to_dict
                return f"postgres at {conninfo_to_dict(self.url).get('host') or 'local socket'}"
            p = urlparse(self.url)
            return f"postgres at {p.hostname or 'local socket'}"
        return f"sqlite file {self.path}"

    @contextmanager
    def connect(self) -> Iterator:
        if self.url:
            with self._pool.connection() as conn:  # commits on success, rolls back on error
                yield _PgConn(conn)
            return
        conn = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init(self) -> None:
        if not self.url:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.connect() as conn:
                conn.executescript(SCHEMA)
            return
        from psycopg.rows import dict_row
        from psycopg_pool import ConnectionPool

        # prepare_threshold=None: Supabase's pooled connection (transaction mode) does not support prepared statements.
        self._pool = ConnectionPool(
            self.url, min_size=1, max_size=5, open=False, timeout=20,
            kwargs={"row_factory": dict_row, "prepare_threshold": None, "connect_timeout": 15, "autocommit": False})
        self._pool.open(wait=True, timeout=30)
        text = "\n".join(l for l in (SCHEMA + PG_SECURITY).splitlines() if not l.strip().startswith("--"))
        with self.connect() as conn:
            for stmt in (x.strip() for x in text.split(";")):
                if stmt:
                    conn.execute(stmt)
        log.info("Connected to %s", self.describe())

    def close(self) -> None:
        if self._pool is not None:
            self._pool.close()
