"""Loads the saved model bundle once at startup. Never retrains."""
from __future__ import annotations

import json
import logging
from pathlib import Path

import joblib

log = logging.getLogger("nid.model")


class ModelStore:
    def __init__(self, model_path: Path, metadata_path: Path, evaluation_path: Path):
        self.model_path = model_path
        self.metadata_path = metadata_path
        self.evaluation_path = evaluation_path
        self.pipeline = None
        self.features: list[str] = []
        self.classes: list[str] = []
        self.metadata: dict = {}
        self.evaluation: dict = {}
        self.error: str | None = None
        self.loaded = False

    def load(self) -> None:
        self.loaded = False
        self.error = None
        try:
            if not self.model_path.exists():
                raise FileNotFoundError(
                    f"No trained model found at {self.model_path}. Run backend/scripts/train.py first."
                )
            bundle = joblib.load(self.model_path)
            self.pipeline = bundle["pipeline"]
            clf = getattr(self.pipeline, "named_steps", {}).get("clf")
            if clf is not None and hasattr(clf, "n_jobs"):
                clf.n_jobs = 1  # real-time micro-batches are tiny; thread start-up would dominate latency
            self.features = list(bundle["features"])
            self.classes = list(bundle["classes"])
            self.metadata = json.loads(self.metadata_path.read_text()) if self.metadata_path.exists() else {}
            self.evaluation = json.loads(self.evaluation_path.read_text()) if self.evaluation_path.exists() else {}
            if self.metadata and self.metadata.get("model_version") != bundle.get("model_version"):
                raise ValueError("Model file and metadata file belong to different training runs.")
            # Smoke check that the pipeline exposes what the API relies on.
            if not hasattr(self.pipeline, "predict"):
                raise TypeError("Loaded object is not a fitted pipeline.")
            self.loaded = True
            log.info("Loaded model %s with %d features", bundle.get("model_version"), len(self.features))
        except Exception as exc:  # noqa: BLE001 - surface any load failure through /health
            self.error = f"{type(exc).__name__}: {exc}"
            log.error("Model failed to load: %s", self.error)

    @property
    def version(self) -> str | None:
        return self.metadata.get("model_version")

    @property
    def supports_proba(self) -> bool:
        return bool(self.loaded and hasattr(self.pipeline, "predict_proba"))

    @property
    def benign_label(self) -> str:
        return self.metadata.get("benign_label", "BENIGN")

    @property
    def is_synthetic(self) -> bool:
        return bool(self.metadata.get("dataset", {}).get("is_synthetic"))
