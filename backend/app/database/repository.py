"""All SQL lives here. Statistics are computed from stored results only."""
from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

from .db import Database

RISK_ORDER_SQL = (
    "CASE risk_level WHEN 'Critical' THEN 5 WHEN 'High' THEN 4 WHEN 'Medium' THEN 3 "
    "WHEN 'Low' THEN 2 WHEN 'Needs review' THEN 1 ELSE 0 END"
)
RISK_LEVELS = ["Critical", "High", "Medium", "Low", "Needs review", "None"]
REVIEW_STATUSES = ("new", "investigating", "reviewed")
SORT_COLUMNS = {
    "event_time": "event_time",
    "processed_at": "processed_at",
    "risk": RISK_ORDER_SQL,
    "confidence": "confidence",
    "row_index": "row_index",
}


def utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class RecordFilters:
    scan_id: str | None = None
    classification: str | None = None  # 'normal' | 'suspicious'
    category: str | None = None
    risk_level: str | None = None
    review_status: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    alerts_only: bool = False

    def to_sql(self) -> tuple[str, list[Any]]:
        clauses, params = [], []
        if self.scan_id:
            clauses.append("scan_id = ?")
            params.append(self.scan_id)
        if self.classification == "normal":
            clauses.append("is_suspicious = 0")
        elif self.classification == "suspicious":
            clauses.append("is_suspicious = 1")
        if self.category:
            clauses.append("predicted_class = ?")
            params.append(self.category)
        if self.risk_level:
            clauses.append("risk_level = ?")
            params.append(self.risk_level)
        if self.review_status:
            clauses.append("review_status = ?")
            params.append(self.review_status)
        if self.date_from:
            clauses.append("event_time >= ?")
            params.append(self.date_from)
        if self.date_to:
            clauses.append("event_time <= ?")
            params.append(self.date_to)
        if self.alerts_only:
            clauses.append("(is_suspicious = 1 OR requires_review = 1)")
        return (" WHERE " + " AND ".join(clauses)) if clauses else "", params


def _loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


class Repository:
    def __init__(self, db: Database):
        self.db = db

    # ------------------------------------------------------------------ scans
    def create_scan(self, *, source: str, filename: str | None, file_path: str | None, size_bytes: int | None,
                    status: str, rows_total: int | None, validation: dict | None, model_version: str | None,
                    scan_id: str | None = None) -> str:
        scan_id = scan_id or uuid.uuid4().hex
        with self.db.connect() as conn:
            conn.execute(
                "INSERT INTO scans (id, source, filename, file_path, size_bytes, status, created_at, rows_total, "
                "validation_json, model_version) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (scan_id, source, filename, file_path, size_bytes, status, utcnow(), rows_total,
                 json.dumps(validation) if validation is not None else None, model_version),
            )
        return scan_id

    def update_scan(self, scan_id: str, **fields: Any) -> None:
        if not fields:
            return
        for key in ("summary", "validation"):
            if key in fields:
                fields[f"{key}_json"] = json.dumps(fields.pop(key))
        assignments = ", ".join(f"{k} = ?" for k in fields)
        with self.db.connect() as conn:
            conn.execute(f"UPDATE scans SET {assignments} WHERE id = ?", [*fields.values(), scan_id])

    def get_scan(self, scan_id: str) -> dict | None:
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM scans WHERE id = ?", (scan_id,)).fetchone()
            if row is None:
                return None
            return self._scan_dict(conn, row)

    def list_scans(self, limit: int = 100) -> list[dict]:
        with self.db.connect() as conn:
            rows = conn.execute("SELECT * FROM scans ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
            return [self._scan_dict(conn, r, light=True) for r in rows]

    def delete_scan(self, scan_id: str) -> str | None:
        """Delete a scan and its records; returns the stored file path (for cleanup) if any."""
        with self.db.connect() as conn:
            row = conn.execute("SELECT file_path FROM scans WHERE id = ?", (scan_id,)).fetchone()
            if row is None:
                return None
            conn.execute("DELETE FROM scans WHERE id = ?", (scan_id,))
            return row["file_path"] or ""

    def fail_interrupted_scans(self) -> int:
        with self.db.connect() as conn:
            cur = conn.execute(
                "UPDATE scans SET status='failed', error='Interrupted by a server restart.', finished_at=? "
                "WHERE status IN ('queued','running')", (utcnow(),))
            return cur.rowcount

    def _scan_dict(self, conn: sqlite3.Connection, row: sqlite3.Row, light: bool = False) -> dict:
        d = dict(row)
        d.pop("file_path", None)
        counts = conn.execute(
            "SELECT COUNT(*) AS total, COALESCE(SUM(is_suspicious),0) AS suspicious, "
            "COALESCE(SUM(CASE WHEN requires_review=1 THEN 1 ELSE 0 END),0) AS needs_review "
            "FROM records WHERE scan_id = ?", (row["id"],)).fetchone()
        d["records_stored"] = counts["total"]
        d["suspicious_records"] = counts["suspicious"]
        d["records_requiring_review"] = counts["needs_review"]
        d["validation"] = _loads(d.pop("validation_json", None), None)
        d["summary"] = _loads(d.pop("summary_json", None), None)
        if light:
            d.pop("validation", None)
        return d

    def delete_records(self, scan_id: str) -> None:
        with self.db.connect() as conn:
            conn.execute("DELETE FROM records WHERE scan_id = ?", (scan_id,))

    def get_scan_file(self, scan_id: str) -> str | None:
        with self.db.connect() as conn:
            row = conn.execute("SELECT file_path FROM scans WHERE id = ?", (scan_id,)).fetchone()
            return row["file_path"] if row else None

    # ---------------------------------------------------------------- records
    def insert_records(self, scan_id: str, results: Iterable[dict]) -> int:
        rows = []
        for r in results:
            flow = r.get("flow_timestamp")
            rows.append((
                r["record_id"], scan_id, r["row_index"], r["processed_at"],
                flow or r["processed_at"][:19], "flow" if flow else "processed",
                r["predicted_class"], int(r["is_suspicious"]), r.get("attack_category"), r.get("confidence"),
                r["risk_level"], int(r["requires_review"]), r.get("risk_rule_id"), r.get("risk_reason"),
                json.dumps(r.get("risk_evidence") or {}), json.dumps(r.get("warnings") or []),
                r.get("ground_truth_label"), r.get("src_ip"), r.get("dst_ip"), r.get("dst_port"),
                json.dumps(r["features"]) if r.get("features") is not None else None,
            ))
        if not rows:
            return 0
        with self.db.connect() as conn:
            conn.executemany(
                "INSERT INTO records (id, scan_id, row_index, processed_at, event_time, event_time_source, "
                "predicted_class, is_suspicious, attack_category, confidence, risk_level, requires_review, "
                "risk_rule_id, risk_reason, risk_evidence_json, warnings_json, ground_truth_label, src_ip, dst_ip, "
                "dst_port, features_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        return len(rows)

    @staticmethod
    def _record_dict(row: sqlite3.Row, detail: bool = False) -> dict:
        d = dict(row)
        d["is_suspicious"] = bool(d["is_suspicious"])
        d["requires_review"] = bool(d["requires_review"])
        d["warnings"] = _loads(d.pop("warnings_json", None), [])
        d["risk_evidence"] = _loads(d.pop("risk_evidence_json", None), {})
        features = d.pop("features_json", None)
        if detail:
            d["features"] = _loads(features, None)
        return d

    def list_records(self, filters: RecordFilters, *, page: int, page_size: int, sort: str, descending: bool) -> dict:
        where, params = filters.to_sql()
        order = SORT_COLUMNS.get(sort, "event_time")
        direction = "DESC" if descending else "ASC"
        with self.db.connect() as conn:
            total = conn.execute(f"SELECT COUNT(*) FROM records{where}", params).fetchone()[0]
            rows = conn.execute(
                "SELECT id, scan_id, row_index, processed_at, event_time, event_time_source, predicted_class, "
                "is_suspicious, attack_category, confidence, risk_level, requires_review, risk_rule_id, risk_reason, "
                "risk_evidence_json, warnings_json, ground_truth_label, src_ip, dst_ip, dst_port, review_status, "
                "review_note, reviewed_at, (features_json IS NOT NULL) AS has_features "
                f"FROM records{where} ORDER BY {order} {direction}, row_index ASC LIMIT ? OFFSET ?",
                [*params, page_size, (page - 1) * page_size]).fetchall()
        items = []
        for r in rows:
            d = self._record_dict(r)
            d["has_features"] = bool(d["has_features"])
            items.append(d)
        return {"items": items, "total": total, "page": page, "page_size": page_size}

    def get_record(self, record_id: str) -> dict | None:
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM records WHERE id = ?", (record_id,)).fetchone()
        return self._record_dict(row, detail=True) if row else None

    def update_review(self, record_id: str, status: str | None, note: str | None) -> dict | None:
        sets, params = [], []
        if status is not None:
            sets.append("review_status = ?")
            params.append(status)
        if note is not None:
            sets.append("review_note = ?")
            params.append(note)
        if not sets:
            return self.get_record(record_id)
        sets.append("reviewed_at = ?")
        params.append(utcnow())
        with self.db.connect() as conn:
            cur = conn.execute(f"UPDATE records SET {', '.join(sets)} WHERE id = ?", [*params, record_id])
            if cur.rowcount == 0:
                return None
        return self.get_record(record_id)

    def iter_records_for_export(self, filters: RecordFilters, batch: int = 5000) -> Iterable[sqlite3.Row]:
        where, params = filters.to_sql()
        offset = 0
        while True:
            with self.db.connect() as conn:
                rows = conn.execute(
                    "SELECT id, scan_id, row_index, processed_at, event_time, predicted_class, is_suspicious, "
                    "confidence, risk_level, requires_review, risk_rule_id, risk_reason, ground_truth_label, "
                    "src_ip, dst_ip, dst_port, review_status, review_note "
                    f"FROM records{where} ORDER BY row_index ASC LIMIT ? OFFSET ?", [*params, batch, offset]).fetchall()
            if not rows:
                return
            yield from rows
            offset += batch

    # ------------------------------------------------------------- statistics
    def overview(self, scan_id: str | None) -> dict:
        f = RecordFilters(scan_id=scan_id)
        where, params = f.to_sql()
        with self.db.connect() as conn:
            t = conn.execute(
                "SELECT COUNT(*) AS total, COALESCE(SUM(is_suspicious),0) AS suspicious, "
                "COALESCE(SUM(CASE WHEN requires_review=1 THEN 1 ELSE 0 END),0) AS review, "
                "MAX(processed_at) AS last_processed FROM records" + where, params).fetchone()
            risk_rows = conn.execute(
                "SELECT risk_level, COUNT(*) AS n FROM records" + where + " GROUP BY risk_level", params).fetchall()
            alert_where = (where + " AND " if where else " WHERE ") + "(is_suspicious = 1 OR requires_review = 1)"
            alert_risk = conn.execute(
                "SELECT risk_level, COUNT(*) AS n FROM records" + alert_where + " GROUP BY risk_level", params).fetchall()
            cat_where = (where + " AND " if where else " WHERE ") + "is_suspicious = 1"
            cats = conn.execute(
                "SELECT predicted_class AS category, COUNT(*) AS n FROM records" + cat_where +
                " GROUP BY predicted_class ORDER BY n DESC LIMIT 10", params).fetchall()
            scan_where = " WHERE id = ?" if scan_id else ""
            scans = conn.execute(
                "SELECT COUNT(*) AS n, SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) AS completed, "
                "MAX(finished_at) AS last_finished FROM scans" + scan_where, [scan_id] if scan_id else []).fetchone()
            review = conn.execute(
                "SELECT review_status, COUNT(*) AS n FROM records" + alert_where + " GROUP BY review_status", params).fetchall()
        total = t["total"]
        return {
            "total_records": total,
            "normal_records": total - t["suspicious"],
            "suspicious_records": t["suspicious"],
            "records_requiring_review": t["review"],
            "alerts_by_risk": {lvl: next((r["n"] for r in alert_risk if r["risk_level"] == lvl), 0) for lvl in RISK_LEVELS if lvl != "None"},
            "records_by_risk": {lvl: next((r["n"] for r in risk_rows if r["risk_level"] == lvl), 0) for lvl in RISK_LEVELS},
            "top_attack_categories": [{"category": r["category"], "count": r["n"]} for r in cats],
            "alerts_by_review_status": {s: next((r["n"] for r in review if r["review_status"] == s), 0) for s in REVIEW_STATUSES},
            "scans_total": scans["n"] or 0,
            "scans_completed": scans["completed"] or 0,
            "last_analysis_at": scans["last_finished"] or t["last_processed"],
            "scope": "scan" if scan_id else "all_scans",
            "note": "Counts are analyzed records (network flows). They are not unique attacks or incidents; many records can belong to one event.",
        }

    def traffic(self, filters: RecordFilters) -> dict:
        where, params = filters.to_sql()
        with self.db.connect() as conn:
            cls = conn.execute("SELECT is_suspicious AS s, COUNT(*) AS n FROM records" + where + " GROUP BY is_suspicious", params).fetchall()
            cats = conn.execute("SELECT predicted_class AS c, COUNT(*) AS n FROM records" + where + " GROUP BY predicted_class ORDER BY n DESC", params).fetchall()
            risks = conn.execute("SELECT risk_level AS r, COUNT(*) AS n FROM records" + where + " GROUP BY risk_level", params).fetchall()
            span = conn.execute("SELECT MIN(event_time) AS lo, MAX(event_time) AS hi FROM records" + where, params).fetchone()
            sources = conn.execute("SELECT event_time_source AS s, COUNT(*) AS n FROM records" + where + " GROUP BY event_time_source", params).fetchall()
            bucket, length = "hour", 13
            trend: list[dict] = []
            if span["lo"] and span["hi"]:
                lo = datetime.fromisoformat(span["lo"])
                hi = datetime.fromisoformat(span["hi"])
                hours = (hi - lo).total_seconds() / 3600
                if hours <= 2:
                    bucket, length = "minute", 16
                elif hours <= 72:
                    bucket, length = "hour", 13
                else:
                    bucket, length = "day", 10
                trend_rows = conn.execute(
                    f"SELECT substr(event_time,1,{length}) AS b, SUM(CASE WHEN is_suspicious=0 THEN 1 ELSE 0 END) AS normal, "
                    "SUM(is_suspicious) AS suspicious FROM records" + where + " GROUP BY b ORDER BY b", params).fetchall()
                trend = [{"bucket": r["b"], "normal": r["normal"], "suspicious": r["suspicious"]} for r in trend_rows]
        source_counts = {r["s"]: r["n"] for r in sources}
        basis = "flow_timestamp" if source_counts.get("flow") and not source_counts.get("processed") else (
            "processing_time" if source_counts.get("processed") and not source_counts.get("flow") else "mixed")
        return {
            "classification": {"normal": next((r["n"] for r in cls if r["s"] == 0), 0), "suspicious": next((r["n"] for r in cls if r["s"] == 1), 0)},
            "categories": [{"category": r["c"], "count": r["n"], "suspicious": r["c"] != "BENIGN"} for r in cats],
            "risk_levels": {lvl: next((r["n"] for r in risks if r["r"] == lvl), 0) for lvl in RISK_LEVELS},
            "trend": trend,
            "trend_bucket": bucket,
            "time_basis": basis,
            "time_basis_note": {
                "flow_timestamp": "Times come from the Timestamp column in the analyzed data.",
                "processing_time": "The data has no usable timestamp, so times are when the application processed the records. They do not reflect when traffic occurred.",
                "mixed": "Some scans have flow timestamps and others only processing times.",
            }[basis],
            "time_range": {"from": span["lo"], "to": span["hi"]},
        }

    def filter_options(self, scan_id: str | None) -> dict:
        where, params = RecordFilters(scan_id=scan_id).to_sql()
        with self.db.connect() as conn:
            cats = [r[0] for r in conn.execute("SELECT DISTINCT predicted_class FROM records" + where + " ORDER BY 1", params)]
        return {"categories": cats, "risk_levels": RISK_LEVELS, "review_statuses": list(REVIEW_STATUSES)}

    def report_tables(self, scan_id: str) -> dict:
        f = RecordFilters(scan_id=scan_id)
        traffic = self.traffic(f)
        where, params = f.to_sql()
        with self.db.connect() as conn:
            alerts = conn.execute(
                "SELECT id, row_index, event_time, predicted_class, confidence, risk_level, requires_review, risk_rule_id, review_status "
                "FROM records" + where + " AND (is_suspicious = 1 OR requires_review = 1) "
                f"ORDER BY {RISK_ORDER_SQL} DESC, confidence DESC LIMIT 50", params).fetchall()
        return {"traffic": traffic, "top_alerts": [dict(a) | {"requires_review": bool(a["requires_review"])} for a in alerts]}
