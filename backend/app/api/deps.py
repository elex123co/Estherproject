from __future__ import annotations

from datetime import datetime

from fastapi import HTTPException, Query, Request

from ..core.container import Container
from ..database.repository import RecordFilters


def get_container(request: Request) -> Container:
    return request.app.state.container


def require_model(container: Container) -> None:
    if not container.store.loaded:
        raise HTTPException(
            status_code=503,
            detail=f"The model is not loaded: {container.store.error or 'unknown error'}",
        )


def _check_iso(value: str | None, name: str) -> str | None:
    if value is None:
        return None
    try:
        datetime.fromisoformat(value)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"{name} must be an ISO 8601 date or datetime, e.g. 2017-07-05T09:00:00")
    return value


def record_filters(
    scan_id: str | None = Query(None),
    classification: str | None = Query(None, pattern="^(normal|suspicious)$"),
    category: str | None = Query(None, max_length=100),
    risk_level: str | None = Query(None, pattern="^(Critical|High|Medium|Low|Needs review|None)$"),
    review_status: str | None = Query(None, pattern="^(new|investigating|reviewed)$"),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
) -> RecordFilters:
    return RecordFilters(
        scan_id=scan_id, classification=classification, category=category, risk_level=risk_level,
        review_status=review_status, date_from=_check_iso(date_from, "date_from"), date_to=_check_iso(date_to, "date_to"),
    )
