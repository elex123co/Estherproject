"""Prediction service: validated frame in, structured per-record results out.

Every field comes from the loaded model or from the risk engine. Nothing is simulated.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

from ..ml.model_store import ModelStore
from ..ml.preprocessing import NumericCleaner
from ..ml.schema import CONTEXT_COLUMNS, LABEL_COLUMN, find_column, normalize_label
from ..risk.engine import RiskEngine

# Features copied next to a record so the risk engine and analysts can see the evidence used.
EVIDENCE_FEATURES = ["Flow Packets/s", "Flow Bytes/s", "Flow Duration", "Total Fwd Packets", "Total Backward Packets"]


class MissingFeaturesError(ValueError):
    def __init__(self, missing: list[str]):
        self.missing = missing
        super().__init__(f"Missing required features: {missing[:10]}")


class Predictor:
    def __init__(self, store: ModelStore, risk: RiskEngine):
        self.store = store
        self.risk = risk

    def predict_frame(
        self,
        frame: pd.DataFrame,
        *,
        row_offset: int = 0,
        feature_rows_remaining: int = 0,
    ) -> list[dict[str, Any]]:
        """Score one chunk. `feature_rows_remaining` caps how many flagged records keep their feature vector."""
        store = self.store
        if not store.loaded:
            raise RuntimeError("Model is not loaded.")
        features = store.features
        missing = [c for c in features if c not in frame.columns]
        if missing:
            raise MissingFeaturesError(missing)
        if frame.empty:
            return []

        cleaned = NumericCleaner(features).transform(frame)
        invalid_counts = np.isnan(cleaned).sum(axis=1)
        imputed_fraction = invalid_counts / max(len(features), 1)

        predictions = store.pipeline.predict(frame)
        confidences: np.ndarray | None = None
        if store.supports_proba:
            probabilities = store.pipeline.predict_proba(frame)
            class_index = {c: i for i, c in enumerate(store.pipeline.classes_)}
            confidences = probabilities[np.arange(len(predictions)), [class_index[p] for p in predictions]]

        label_col = find_column(frame, [LABEL_COLUMN])
        context_cols = {k: find_column(frame, c) for k, c in CONTEXT_COLUMNS.items()}
        timestamps = (
            pd.to_datetime(frame[context_cols["timestamp"]], errors="coerce") if context_cols.get("timestamp") else None
        )
        evidence_cols = [c for c in EVIDENCE_FEATURES if c in features]
        evidence_index = {c: features.index(c) for c in evidence_cols}

        now = datetime.now(timezone.utc).replace(microsecond=0)
        processed_at = now.isoformat()
        results: list[dict[str, Any]] = []
        feature_budget = feature_rows_remaining
        benign = store.benign_label

        for i, predicted in enumerate(predictions):
            predicted = str(predicted)
            confidence = float(confidences[i]) if confidences is not None else None
            evidence_row = {c: float(cleaned[i, j]) for c, j in evidence_index.items()}
            assessment = self.risk.assess(predicted, confidence, evidence_row, float(imputed_fraction[i]))
            suspicious = predicted != benign

            warnings: list[str] = []
            if invalid_counts[i]:
                warnings.append(
                    f"{int(invalid_counts[i])} of {len(features)} features were missing or invalid and were imputed."
                )

            flow_time = None
            if timestamps is not None and pd.notna(timestamps.iloc[i]):
                flow_time = timestamps.iloc[i].strftime("%Y-%m-%dT%H:%M:%S")

            record: dict[str, Any] = {
                "record_id": uuid.uuid4().hex,
                "row_index": row_offset + i,
                "processed_at": processed_at,
                "flow_timestamp": flow_time,
                "predicted_class": predicted,
                "is_suspicious": suspicious,
                "attack_category": predicted if suspicious else None,
                "confidence": confidence,
                "risk_level": assessment.level,
                "requires_review": assessment.requires_review,
                "risk_rule_id": assessment.rule_id,
                "risk_reason": assessment.reason,
                "risk_evidence": assessment.evidence,
                "warnings": warnings,
                "ground_truth_label": normalize_label(frame[label_col].iloc[i]) if label_col else None,
                "src_ip": _text(frame, context_cols.get("src_ip"), i),
                "dst_ip": _text(frame, context_cols.get("dst_ip"), i),
                "dst_port": _port(frame, context_cols.get("dst_port"), i),
                "features": None,
            }
            if (suspicious or assessment.requires_review) and feature_budget > 0:
                record["features"] = {
                    name: (None if np.isnan(cleaned[i, j]) else float(cleaned[i, j])) for j, name in enumerate(features)
                }
                feature_budget -= 1
            results.append(record)
        return results


def _text(frame: pd.DataFrame, column: str | None, i: int) -> str | None:
    if not column:
        return None
    value = frame[column].iloc[i]
    return None if pd.isna(value) else str(value)


def _port(frame: pd.DataFrame, column: str | None, i: int) -> int | None:
    if not column:
        return None
    value = pd.to_numeric(frame[column].iloc[i], errors="coerce")
    return None if pd.isna(value) else int(value)
