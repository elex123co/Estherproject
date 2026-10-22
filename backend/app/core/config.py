"""Application settings, read from environment variables (no secrets in code)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def _env_path(name: str, default: Path) -> Path:
    value = os.environ.get(name)
    return Path(value).expanduser().resolve() if value else default


def _env_list(name: str, default: list[str]) -> list[str]:
    value = os.environ.get(name)
    if not value:
        return default
    return [item.strip() for item in value.split(",") if item.strip()]


@dataclass
class Settings:
    app_name: str = "Network Intrusion Detection and Risk Assessment API"
    app_version: str = "1.0.0"

    # Locations
    model_dir: Path = field(default_factory=lambda: _env_path("NID_MODEL_DIR", REPO_ROOT / "models"))
    data_dir: Path = field(default_factory=lambda: _env_path("NID_DATA_DIR", REPO_ROOT / "data"))
    database_path: Path = field(
        default_factory=lambda: _env_path("NID_DATABASE_PATH", REPO_ROOT / "data" / "nid.sqlite3")
    )
    risk_rules_path: Path = field(
        default_factory=lambda: _env_path(
            "NID_RISK_RULES_PATH", Path(__file__).resolve().parents[1] / "risk" / "rules.json"
        )
    )

    # CORS: origins that may call the API from a browser
    allowed_origins: list[str] = field(
        default_factory=lambda: _env_list(
            "NID_ALLOWED_ORIGINS", ["http://localhost:5173", "http://127.0.0.1:5173"]
        )
    )

    # Resource protection
    max_upload_mb: int = field(default_factory=lambda: int(os.environ.get("NID_MAX_UPLOAD_MB", "200")))
    chunk_rows: int = field(default_factory=lambda: int(os.environ.get("NID_CHUNK_ROWS", "20000")))
    max_concurrent_jobs: int = field(default_factory=lambda: int(os.environ.get("NID_MAX_JOBS", "1")))
    max_queued_jobs: int = field(default_factory=lambda: int(os.environ.get("NID_MAX_QUEUED_JOBS", "5")))
    # Per-record feature vectors are stored only for flagged records, up to this cap per scan.
    max_feature_rows_per_scan: int = field(
        default_factory=lambda: int(os.environ.get("NID_MAX_FEATURE_ROWS", "50000"))
    )
    max_page_size: int = 200
    # Real-time sessions
    max_realtime_rate: int = field(default_factory=lambda: int(os.environ.get("NID_MAX_REALTIME_RATE", "2000")))
    max_realtime_records: int = field(default_factory=lambda: int(os.environ.get("NID_MAX_REALTIME_RECORDS", "500000")))
    max_session_seconds: int = field(default_factory=lambda: int(os.environ.get("NID_MAX_SESSION_SECONDS", "3600")))

    @property
    def upload_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def model_path(self) -> Path:
        return self.model_dir / "intrusion_model.joblib"

    @property
    def model_metadata_path(self) -> Path:
        return self.model_dir / "model_metadata.json"

    @property
    def pool_path(self) -> Path:
        return self.model_dir / "simulation_pool.joblib"

    @property
    def evaluation_path(self) -> Path:
        return self.model_dir / "evaluation.json"

    def ensure_dirs(self) -> None:
        for path in (self.model_dir, self.data_dir, self.upload_dir, self.database_path.parent):
            path.mkdir(parents=True, exist_ok=True)


def get_settings() -> Settings:
    return Settings()
