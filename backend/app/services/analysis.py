"""Background analysis of uploaded datasets and single-record analysis."""
from __future__ import annotations

import logging
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

from ..core.config import Settings
from ..database.repository import Repository, utcnow
from ..ml.data_loader import iter_csv_chunks
from ..ml.evaluation import evaluate_predictions
from ..ml.schema import normalize_columns
from .prediction import Predictor

log = logging.getLogger("nid.analysis")


class QueueFullError(RuntimeError):
    pass


class AnalysisService:
    def __init__(self, settings: Settings, repo: Repository, predictor: Predictor):
        self.settings = settings
        self.repo = repo
        self.predictor = predictor
        self.executor = ThreadPoolExecutor(max_workers=settings.max_concurrent_jobs, thread_name_prefix="analysis")

    def submit(self, scan_id: str) -> None:
        active = [s for s in self.repo.list_scans(500) if s["source"] == "upload" and s["status"] in ("queued", "running")]
        if len(active) >= self.settings.max_queued_jobs:
            raise QueueFullError("Too many analyses are queued. Wait for one to finish and try again.")
        self.repo.update_scan(scan_id, status="queued", rows_processed=0, error=None,
                              model_version=self.predictor.store.version)
        self.executor.submit(self._run, scan_id)

    # ------------------------------------------------------------------ job
    def _run(self, scan_id: str) -> None:
        started = time.time()
        path = self.repo.get_scan_file(scan_id)
        try:
            if not path or not Path(path).exists():
                raise FileNotFoundError("The uploaded file is no longer available.")
            self.repo.update_scan(scan_id, status="running", started_at=utcnow())
            class_counts: Counter = Counter()
            risk_counts: Counter = Counter()
            truth_parts: list[np.ndarray] = []
            pred_parts: list[np.ndarray] = []
            offset = 0
            budget = self.settings.max_feature_rows_per_scan
            stored_vectors = 0
            for chunk in iter_csv_chunks(Path(path), self.settings.chunk_rows):
                results = self.predictor.predict_frame(chunk, row_offset=offset, feature_rows_remaining=budget)
                used = sum(1 for r in results if r["features"] is not None)
                budget -= used
                stored_vectors += used
                self.repo.insert_records(scan_id, results)
                offset += len(chunk)
                class_counts.update(r["predicted_class"] for r in results)
                risk_counts.update(r["risk_level"] for r in results)
                labelled = [(r["ground_truth_label"], r["predicted_class"]) for r in results if r["ground_truth_label"]]
                if labelled:
                    truth_parts.append(np.array([t for t, _ in labelled], dtype=object))
                    pred_parts.append(np.array([p for _, p in labelled], dtype=object))
                self.repo.update_scan(scan_id, rows_processed=offset)

            summary = {
                "records_analyzed": offset,
                "predicted_class_counts": dict(class_counts),
                "risk_level_counts": dict(risk_counts),
                "duration_seconds": round(time.time() - started, 2),
                "feature_vectors_stored": stored_vectors,
                "feature_vector_cap": self.settings.max_feature_rows_per_scan,
                "label_comparison": self._label_comparison(truth_parts, pred_parts),
            }
            self.repo.update_scan(scan_id, status="completed", finished_at=utcnow(), summary=summary,
                                  rows_processed=offset)
            log.info("Scan %s completed: %d records in %.1fs", scan_id, offset, time.time() - started)
        except Exception as exc:  # noqa: BLE001 - recorded on the scan so the UI can show it
            log.exception("Scan %s failed", scan_id)
            self.repo.delete_records(scan_id)  # do not leave a partial, misleading result behind
            self.repo.update_scan(scan_id, status="failed", finished_at=utcnow(),
                                  error=f"{type(exc).__name__}: {exc}"[:500])

    @staticmethod
    def _label_comparison(truth_parts: list[np.ndarray], pred_parts: list[np.ndarray]) -> dict | None:
        if not truth_parts:
            return None
        truth = np.concatenate(truth_parts)
        pred = np.concatenate(pred_parts)
        labels = sorted(set(truth.tolist()) | set(pred.tolist()))
        evaluation = evaluate_predictions(truth, pred, labels, "labels supplied in the uploaded file")
        evaluation["caveat"] = (
            "Computed against the Label column of this upload. This is not the held-out test evaluation. "
            "If the upload overlaps the model's training data, these figures are optimistic."
        )
        return evaluation

    # -------------------------------------------------------- single record
    def analyze_record(self, record: dict) -> dict:
        frame = normalize_columns(pd.DataFrame([record]))
        results = self.predictor.predict_frame(frame, row_offset=0, feature_rows_remaining=1)
        result = results[0]
        scan_id = self.repo.create_scan(
            source="single", filename="Single record", file_path=None, size_bytes=None, status="completed",
            rows_total=1, validation=None, model_version=self.predictor.store.version)
        self.repo.insert_records(scan_id, results)
        self.repo.update_scan(scan_id, started_at=utcnow(), finished_at=utcnow(), rows_processed=1,
                              summary={"records_analyzed": 1, "predicted_class_counts": {result["predicted_class"]: 1},
                                       "risk_level_counts": {result["risk_level"]: 1}, "label_comparison": None})
        result["scan_id"] = scan_id
        return result
