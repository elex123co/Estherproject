"""Metric computation. All figures are derived from real predictions passed in."""
from __future__ import annotations

from typing import Sequence

import numpy as np
from sklearn.metrics import confusion_matrix

from .schema import BENIGN_LABEL


def _safe_div(numerator: float, denominator: float) -> float | None:
    return float(numerator / denominator) if denominator else None


def evaluate_from_confusion(cm, labels: list[str], basis: str, benign: str = BENIGN_LABEL) -> dict:
    """Full multiclass evaluation from a confusion matrix (rows = true class, columns = predicted).

    Working from the matrix lets streaming sessions evaluate millions of flows without keeping them.
    `basis` states which data the figures came from so the UI can say so.
    """
    cm = np.asarray(cm, dtype=np.int64)
    total = int(cm.sum())
    tp = np.diag(cm).astype(float)
    support = cm.sum(axis=1).astype(float)
    predicted = cm.sum(axis=0).astype(float)
    precision = np.divide(tp, predicted, out=np.zeros_like(tp), where=predicted > 0)
    recall = np.divide(tp, support, out=np.zeros_like(tp), where=support > 0)
    denom = precision + recall
    f1 = np.divide(2 * precision * recall, denom, out=np.zeros_like(tp), where=denom > 0)

    per_class = [
        {"label": label, "precision": float(precision[i]), "recall": float(recall[i]), "f1": float(f1[i]), "support": int(support[i])}
        for i, label in enumerate(labels)
    ]
    present = support > 0
    macro = {
        "precision": float(precision[present].mean()) if present.any() else 0.0,
        "recall": float(recall[present].mean()) if present.any() else 0.0,
        "f1": float(f1[present].mean()) if present.any() else 0.0,
    }
    weighted = {
        "precision": float((precision * support).sum() / total) if total else 0.0,
        "recall": float((recall * support).sum() / total) if total else 0.0,
        "f1": float((f1 * support).sum() / total) if total else 0.0,
    }

    binary = None
    if benign in labels:
        b = labels.index(benign)
        tn = int(cm[b, b])
        fp = int(cm[b, :].sum() - tn)  # normal flows predicted as some attack
        fn = int(cm[:, b].sum() - tn)  # attack flows predicted as normal
        btp = total - tn - fp - fn
        p = _safe_div(btp, btp + fp)
        r = _safe_div(btp, btp + fn)
        binary = {
            "true_positives": btp, "false_positives": fp, "true_negatives": tn, "false_negatives": fn,
            "precision": p, "recall": r,
            "f1": _safe_div(2 * p * r, p + r) if p is not None and r is not None else None,
            "false_positive_rate": _safe_div(fp, fp + tn),
            "false_negative_rate": _safe_div(fn, fn + btp),
        }
    return {
        "basis": basis,
        "n_samples": total,
        "accuracy": float(tp.sum() / total) if total else 0.0,
        "macro_avg": macro,
        "weighted_avg": weighted,
        "averaging_note": (
            "Macro average: unweighted mean over classes that occur in the evaluated data, so minority "
            "attack classes count as much as BENIGN. Weighted average: mean weighted by class support."
        ),
        "binary_detection": binary,
        "labels": list(labels),
        "confusion_matrix": cm.tolist(),
        "per_class": per_class,
    }


def evaluate_predictions(y_true: Sequence[str], y_pred: Sequence[str], labels: list[str], basis: str) -> dict:
    cm = confusion_matrix(np.asarray(y_true), np.asarray(y_pred), labels=labels)
    return evaluate_from_confusion(cm, labels, basis)
