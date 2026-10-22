"""Health, model information and configuration endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..core.container import Container
from ..database.repository import utcnow
from ..schemas.api import HealthResponse
from .deps import get_container

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health", response_model=HealthResponse)
def health(c: Container = Depends(get_container)):
    """Reports only what was actually checked on this request."""
    db_ok, db_error = True, None
    try:
        with c.db.connect() as conn:
            conn.execute("SELECT 1").fetchone()
    except Exception as exc:  # noqa: BLE001
        db_ok, db_error = False, f"{type(exc).__name__}: {exc}"
    ready = bool(c.store.loaded and db_ok)
    return HealthResponse(
        status="ok" if ready else "degraded",
        model_loaded=c.store.loaded,
        model_version=c.store.version if c.store.loaded else None,
        model_error=c.store.error,
        database_ok=db_ok,
        database_error=db_error,
        ready=ready,
        model_is_synthetic=c.store.is_synthetic,
        checked_at=utcnow(),
    )


@router.get("/model")
def model_info(c: Container = Depends(get_container)):
    """Model metadata: version, training date, dataset, features, candidate comparison."""
    if not c.store.loaded:
        raise HTTPException(503, f"The model is not loaded: {c.store.error}")
    meta = dict(c.store.metadata)
    meta["features_count"] = len(c.store.features)
    return meta


@router.get("/model/evaluation")
def model_evaluation(c: Container = Depends(get_container)):
    """Measured performance of the selected model on the held-out test split, plus validation comparison."""
    if not c.store.loaded:
        raise HTTPException(503, f"The model is not loaded: {c.store.error}")
    if not c.store.evaluation:
        raise HTTPException(404, "No evaluation results were saved with this model.")
    return c.store.evaluation


@router.get("/datasets/schema")
def dataset_schema(c: Container = Depends(get_container)):
    """The feature schema uploaded CSV files must satisfy."""
    if not c.store.loaded:
        raise HTTPException(503, f"The model is not loaded: {c.store.error}")
    return {
        "format": "CSV with a header row, one network flow per row",
        "required_features": c.store.features,
        "optional_columns": {
            "Label": "Ground-truth label. Used only for comparison, never as a prediction.",
            "Timestamp": "Enables time-based trends and filters.",
            "Source IP / Destination IP / Destination Port": "Stored as context for alert review.",
        },
        "notes": [
            "Column names are matched after trimming whitespace.",
            "Packet-capture (pcap) files and raw logs are not supported. Flows must be extracted first (for example with CICFlowMeter).",
            "The features must follow the same definitions as the training dataset.",
        ],
        "training_dataset": c.store.metadata.get("dataset", {}).get("name"),
        "max_upload_mb": c.settings.max_upload_mb,
    }


@router.get("/risk/rules")
def risk_rules(c: Container = Depends(get_container)):
    """The active, configurable risk rules (loaded from risk/rules.json)."""
    return c.risk.rules
