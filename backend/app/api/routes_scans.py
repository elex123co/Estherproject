"""Dataset upload, analysis jobs, single-record prediction, exports and reports."""
from __future__ import annotations

import csv
import io
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse

from ..core.container import Container
from ..database.repository import RecordFilters, utcnow
from ..schemas.api import DatasetUploadResponse, PredictRequest
from ..services.analysis import QueueFullError
from ..services.prediction import MissingFeaturesError
from ..services.validation import ValidationError, validate_csv, validate_record
from .deps import get_container, require_model

router = APIRouter(prefix="/api", tags=["scans"])

DISCLAIMER = (
    "This report comes from a machine-learning decision-support prototype. Flagged records are potential "
    "intrusions that require investigation, not confirmed incidents. The system can miss attacks and can raise "
    "false alarms, and it does not replace professional security analysts."
)


@router.post("/datasets/upload", response_model=DatasetUploadResponse)
async def upload_dataset(file: UploadFile = File(...), c: Container = Depends(get_container)):
    """Upload a CSV and validate it against the model's feature schema. Does not start analysis."""
    require_model(c)
    filename = Path(file.filename or "upload.csv").name
    if not filename.lower().endswith(".csv"):
        raise HTTPException(415, "Only .csv files are supported. Packet captures and raw logs cannot be analyzed directly.")

    upload_id = uuid.uuid4().hex
    path = c.settings.upload_dir / f"{upload_id}.csv"  # the client's file name is never used as a path
    limit = c.settings.max_upload_mb * 1024 * 1024
    size = 0
    try:
        with open(path, "wb") as out:
            while block := await file.read(1024 * 1024):
                size += len(block)
                if size > limit:
                    raise HTTPException(413, f"File is larger than the {c.settings.max_upload_mb} MB upload limit.")
                out.write(block)
        if size == 0:
            raise HTTPException(400, "The uploaded file is empty.")
        try:
            validation = await run_in_threadpool(validate_csv, path, c.store.features)
        except ValidationError as exc:
            raise HTTPException(422, str(exc)) from exc
    except Exception:
        path.unlink(missing_ok=True)
        raise

    if not validation["compatible"]:
        path.unlink(missing_ok=True)  # nothing to analyze; keep no copy of an unusable file
        return DatasetUploadResponse(scan_id=None, filename=filename, size_bytes=size, validation=validation)

    scan_id = c.repo.create_scan(
        source="upload", filename=filename, file_path=str(path), size_bytes=size, status="uploaded",
        rows_total=validation["rows"], validation=validation, model_version=c.store.version, scan_id=upload_id)
    return DatasetUploadResponse(scan_id=scan_id, filename=filename, size_bytes=size, validation=validation)


@router.post("/scans/{scan_id}/analyze", status_code=202)
def start_analysis(scan_id: str, c: Container = Depends(get_container)):
    """Queue the analysis of an uploaded dataset. Poll GET /api/scans/{id} for progress."""
    require_model(c)
    scan = c.repo.get_scan(scan_id)
    if scan is None:
        raise HTTPException(404, "Scan not found.")
    if scan["status"] != "uploaded":
        raise HTTPException(409, f"This scan is '{scan['status']}' and cannot be started. Upload the file again to re-run it.")
    try:
        c.analysis.submit(scan_id)
    except QueueFullError as exc:
        raise HTTPException(429, str(exc)) from exc
    return c.repo.get_scan(scan_id)


@router.get("/scans")
def list_scans(limit: int = Query(50, ge=1, le=200), c: Container = Depends(get_container)):
    return {"items": c.repo.list_scans(limit)}


@router.get("/scans/{scan_id}")
def get_scan(scan_id: str, c: Container = Depends(get_container)):
    scan = c.repo.get_scan(scan_id)
    if scan is None:
        raise HTTPException(404, "Scan not found.")
    return scan


@router.delete("/scans/{scan_id}", status_code=204)
def delete_scan(scan_id: str, c: Container = Depends(get_container)):
    scan = c.repo.get_scan(scan_id)
    if scan is None:
        raise HTTPException(404, "Scan not found.")
    if scan["status"] in ("queued", "running"):
        raise HTTPException(409, "A running analysis cannot be deleted.")
    path = c.repo.delete_scan(scan_id)
    if path:
        Path(path).unlink(missing_ok=True)


@router.post("/predict")
async def predict_single(body: PredictRequest, c: Container = Depends(get_container)):
    """Analyze one flow supplied as JSON (all required features must be present as keys)."""
    require_model(c)
    problems = validate_record(body.record, c.store.features)
    if problems:
        raise HTTPException(422, {"message": "The record does not match the model's feature schema.", "problems": problems})
    try:
        result = await run_in_threadpool(c.analysis.analyze_record, body.record)
    except MissingFeaturesError as exc:
        raise HTTPException(422, str(exc)) from exc
    result.pop("features", None)
    return result


def _safe_cell(value):
    """Neutralise spreadsheet formula injection in exported text fields."""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


EXPORT_COLUMNS = [
    "record_id", "scan_id", "row_index", "event_time", "predicted_class", "is_suspicious", "confidence",
    "risk_level", "requires_review", "risk_rule_id", "risk_reason", "ground_truth_label", "review_status", "review_note",
]
CONTEXT_EXPORT_COLUMNS = ["src_ip", "dst_ip", "dst_port"]


@router.get("/scans/{scan_id}/export.csv")
def export_csv(
    scan_id: str,
    scope: str = Query("alerts", pattern="^(alerts|all)$"),
    include_network_context: bool = Query(False, description="Include IP addresses and destination port."),
    c: Container = Depends(get_container),
):
    """CSV of per-record results. Raw flow features are never exported. IP addresses only on request."""
    scan = c.repo.get_scan(scan_id)
    if scan is None:
        raise HTTPException(404, "Scan not found.")
    if scan["status"] != "completed":
        raise HTTPException(409, "Only completed scans can be exported.")
    filters = RecordFilters(scan_id=scan_id, alerts_only=(scope == "alerts"))
    columns = EXPORT_COLUMNS + (CONTEXT_EXPORT_COLUMNS if include_network_context else [])

    def generate():
        yield f"# Report generated {utcnow()} | model {scan.get('model_version')} | scope {scope} | "\
              "flagged records are potential intrusions requiring investigation, not confirmed incidents\n"
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(columns)
        yield buffer.getvalue()
        for row in c.repo.iter_records_for_export(filters):
            d = dict(row)
            d["record_id"] = d.pop("id")
            d["is_suspicious"] = bool(d["is_suspicious"])
            d["requires_review"] = bool(d["requires_review"])
            buffer.seek(0)
            buffer.truncate()
            writer.writerow([_safe_cell(d.get(col)) for col in columns])
            yield buffer.getvalue()

    return StreamingResponse(
        generate(), media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="nid-report-{scan_id[:8]}-{scope}.csv"'})


@router.get("/scans/{scan_id}/report")
def scan_report(scan_id: str, c: Container = Depends(get_container)):
    """Structured report for a completed analysis (rendered and printed by the frontend)."""
    scan = c.repo.get_scan(scan_id)
    if scan is None:
        raise HTTPException(404, "Scan not found.")
    if scan["status"] != "completed":
        raise HTTPException(409, "A report is available only for completed scans.")
    meta = c.store.metadata if c.store.loaded else {}
    validation = scan.get("validation") or {}
    tables = c.repo.report_tables(scan_id)
    return {
        "generated_at": utcnow(),
        "scan": {k: scan[k] for k in ("id", "filename", "source", "created_at", "started_at", "finished_at", "rows_total", "model_version", "records_stored", "suspicious_records", "records_requiring_review")},
        "dataset_summary": {
            "records": validation.get("rows", scan.get("rows_total")),
            "features_detected": validation.get("features_detected"),
            "features_expected": validation.get("features_expected"),
            "missing_values": validation.get("missing_values"),
            "invalid_values": validation.get("invalid_values"),
            "duplicate_rows": validation.get("duplicate_rows"),
            "label_distribution": validation.get("label_distribution"),
            "warnings": validation.get("warnings", []),
        },
        "model": {
            "version": meta.get("model_version"), "type": meta.get("model_type"), "trained_at": meta.get("trained_at"),
            "training_dataset": meta.get("dataset", {}).get("name"), "is_synthetic": bool(meta.get("dataset", {}).get("is_synthetic")),
            "held_out_test_macro_f1": (c.store.evaluation.get("selected", {}).get("macro_avg", {}) or {}).get("f1") if c.store.loaded else None,
            "evaluation_basis": (c.store.evaluation.get("selected", {}) or {}).get("basis") if c.store.loaded else None,
        },
        "risk_rules_version": c.risk.version,
        "summary": scan.get("summary"),
        "classification": tables["traffic"]["classification"],
        "categories": tables["traffic"]["categories"],
        "risk_levels": tables["traffic"]["risk_levels"],
        "top_alerts": tables["top_alerts"],
        "disclaimer": DISCLAIMER,
        "counting_note": "Counts are analyzed records (network flows), not unique attacks or incidents.",
    }
