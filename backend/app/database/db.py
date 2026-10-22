"""SQLite connection handling and schema."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

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
    confidence          REAL,
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


class Database:
    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
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
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(SCHEMA)
