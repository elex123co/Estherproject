"""Records, alerts, review actions and dashboard statistics."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from ..core.container import Container
from ..database.repository import SORT_COLUMNS, RecordFilters
from ..schemas.api import ReviewUpdate
from .deps import get_container, record_filters

router = APIRouter(prefix="/api", tags=["records"])


def _page_params(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    sort: str = Query("event_time", pattern="^(" + "|".join(SORT_COLUMNS) + ")$"),
    order: str = Query("desc", pattern="^(asc|desc)$"),
):
    return page, page_size, sort, order == "desc"


@router.get("/records")
def list_records(filters: RecordFilters = Depends(record_filters), paging=Depends(_page_params),
                 c: Container = Depends(get_container)):
    """All analyzed records, filterable by scan, class, category, risk level and time range."""
    page, page_size, sort, desc = paging
    return c.repo.list_records(filters, page=page, page_size=page_size, sort=sort, descending=desc)


@router.get("/alerts")
def list_alerts(filters: RecordFilters = Depends(record_filters), paging=Depends(_page_params),
                c: Container = Depends(get_container)):
    """Records flagged as suspicious, or whose result needs review. These are potential intrusions, not confirmed incidents."""
    filters.alerts_only = True
    page, page_size, sort, desc = paging
    if sort == "event_time" and desc is True:
        sort = "risk"  # most urgent first by default for the alert queue
    return c.repo.list_records(filters, page=page, page_size=page_size, sort=sort, descending=desc)


@router.get("/alerts/{record_id}")
def alert_detail(record_id: str, c: Container = Depends(get_container)):
    record = c.repo.get_record(record_id)
    if record is None:
        raise HTTPException(404, "Alert not found.")
    importances = c.store.metadata.get("feature_importances") if c.store.loaded else None
    features = record.get("features") or {}
    influential = None
    if importances and features:
        influential = [
            {"feature": i["feature"], "importance": i["importance"], "value": features.get(i["feature"])}
            for i in importances[:10]
        ]
    record["influential_features"] = influential
    record["influential_features_note"] = (
        "Model-wide feature importance shown next to this record's values. It indicates what the model relies on "
        "overall, not a per-record explanation." if influential else None
    )
    record["features_note"] = None if features else (
        "Feature values were not stored for this record (only flagged records are stored, up to a per-scan cap).")
    record["confidence_note"] = (
        "Model confidence is the model's own estimate for its predicted class. It is not a calibrated probability "
        "of an attack, and it is separate from the risk level." if record.get("confidence") is not None else
        "This model does not provide a confidence estimate.")
    return record


@router.patch("/alerts/{record_id}")
def update_alert(record_id: str, body: ReviewUpdate, c: Container = Depends(get_container)):
    """Set the review status (new / investigating / reviewed) and/or a review note."""
    if body.review_status is None and body.review_note is None:
        raise HTTPException(422, "Provide review_status and/or review_note.")
    updated = c.repo.update_review(record_id, body.review_status, body.review_note)
    if updated is None:
        raise HTTPException(404, "Alert not found.")
    return updated


@router.get("/stats/overview")
def stats_overview(scan_id: str | None = Query(None), c: Container = Depends(get_container)):
    return c.repo.overview(scan_id)


@router.get("/stats/traffic")
def stats_traffic(filters: RecordFilters = Depends(record_filters), c: Container = Depends(get_container)):
    return c.repo.traffic(filters)


@router.get("/stats/filter-options")
def filter_options(scan_id: str | None = Query(None), c: Container = Depends(get_container)):
    return c.repo.filter_options(scan_id)
