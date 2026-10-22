"""Request and response schemas for the HTTP API."""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

ReviewStatus = Literal["new", "investigating", "reviewed"]


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    backend_reachable: bool = True
    model_loaded: bool
    model_version: Optional[str] = None
    model_error: Optional[str] = None
    database_ok: bool
    database_error: Optional[str] = None
    ready: bool = Field(description="True only when the model is loaded and the database responded to a check.")
    model_is_synthetic: bool = False
    checked_at: str


class ReviewUpdate(BaseModel):
    review_status: Optional[ReviewStatus] = None
    review_note: Optional[str] = Field(default=None, max_length=2000)


class PredictRequest(BaseModel):
    record: dict[str, Any] = Field(description="One flow: feature name -> numeric value (null for unknown).")


class ErrorResponse(BaseModel):
    detail: Any


class DatasetUploadResponse(BaseModel):
    scan_id: Optional[str] = Field(description="Set only when the file is compatible and ready to analyze.")
    filename: str
    size_bytes: int
    validation: dict[str, Any]


# ---------------------------------------------------------------- real-time
class PhaseIn(BaseModel):
    label: str = Field(max_length=100, description="Attack class to simulate (must exist in the simulation pool).")
    start: float = Field(ge=0, description="Seconds from session start.")
    duration: float = Field(gt=0)
    rate: float = Field(gt=0, description="Attack flows per second during the phase.")


class ScenarioIn(BaseModel):
    name: str = Field(default="Custom scenario", max_length=80)
    seed: Optional[int] = Field(default=None, description="Same seed gives the same scenario. Random when omitted.")
    duration_seconds: float
    baseline_rate: float = Field(ge=0, description="Normal flows per second throughout.")
    phases: list[PhaseIn] = Field(default_factory=list, max_length=20)


class ReplayIn(BaseModel):
    scan_id: str
    rate: float = Field(gt=0, description="Flows per second.")
    loop: bool = False


class SessionStart(BaseModel):
    mode: Literal["simulation", "replay", "live"]
    scenario: Optional[ScenarioIn] = None
    replay: Optional[ReplayIn] = None
    max_duration_seconds: Optional[float] = Field(default=None, gt=0, description="Cap for replay and live sessions.")


class IngestIn(BaseModel):
    flows: list[dict[str, Any]] = Field(min_length=1, max_length=500)
