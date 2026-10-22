"""Reproducible training workflow.

load -> clean -> split (stratified) -> feature selection (train only) -> fit three candidates ->
select on the validation split -> evaluate the selected model once on the held-out test split ->
save model, metadata and evaluation results.
"""
from __future__ import annotations

import hashlib
import json
import logging
import platform
import time
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.model_selection import train_test_split

from .data_loader import list_csv_files, read_csv
from .evaluation import evaluate_predictions
from .preprocessing import MODEL_NAMES, build_pipeline
from .schema import BENIGN_LABEL, LABEL_COLUMN, find_column, is_metadata_column, normalize_label

log = logging.getLogger("nid.training")

NUMERIC_COLUMN_MIN_FRACTION = 0.95  # a column is numeric if >= 95% of its values convert


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_dataset(data_path: Path) -> tuple[pd.DataFrame, list[dict]]:
    frames, files = [], []
    for path in list_csv_files(data_path):
        frame = read_csv(path)
        label_col = find_column(frame, [LABEL_COLUMN])
        if label_col is None:
            raise ValueError(f"{path.name} has no 'Label' column; supervised training needs labels.")
        if label_col != "Label":
            frame = frame.rename(columns={label_col: "Label"})
        frames.append(frame)
        files.append({"name": path.name, "size_bytes": path.stat().st_size, "sha256": _sha256(path), "rows": len(frame)})
        log.info("Loaded %s: %d rows, %d columns", path.name, len(frame), frame.shape[1])
    combined = pd.concat(frames, ignore_index=True, sort=False)
    return combined, files


def select_numeric_columns(df: pd.DataFrame) -> tuple[list[str], list[str]]:
    candidates = [c for c in df.columns if not is_metadata_column(c)]
    numeric, skipped = [], []
    for column in candidates:
        raw_present = df[column].notna()
        if not raw_present.any():
            skipped.append(column)
            continue
        converted = pd.to_numeric(df[column], errors="coerce")
        # Of the values that are present, how many parse as numbers (inf/NaN strings parse too)?
        valid_fraction = converted[raw_present].notna().mean()
        if valid_fraction >= NUMERIC_COLUMN_MIN_FRACTION:
            numeric.append(column)
        else:
            skipped.append(column)
    return numeric, skipped


def stratified_sample(df: pd.DataFrame, max_rows: int, seed: int, label_col: str = "Label") -> pd.DataFrame:
    if len(df) <= max_rows:
        return df
    frac = max_rows / len(df)
    parts = []
    for _, group in df.groupby(label_col):
        keep = min(len(group), max(int(round(len(group) * frac)), 500))
        parts.append(group.sample(n=keep, random_state=seed))
    return pd.concat(parts).sample(frac=1.0, random_state=seed).reset_index(drop=True)


def select_features(train_x: pd.DataFrame) -> tuple[list[str], list[dict]]:
    """Decide the final feature list from the TRAINING split only."""
    removed: list[dict] = []
    keep: list[str] = []
    hashes: dict[int, str] = {}
    for column in train_x.columns:
        series = train_x[column]
        if series.notna().sum() == 0:
            removed.append({"feature": column, "reason": "all values missing in training data"})
            continue
        if series.nunique(dropna=True) <= 1:
            removed.append({"feature": column, "reason": "constant in training data"})
            continue
        key = int(pd.util.hash_pandas_object(series, index=False).sum())
        original = hashes.get(key)
        if original is not None and train_x[original].equals(series):
            removed.append({"feature": column, "reason": f"exact duplicate of '{original}'"})
            continue
        hashes[key] = column
        keep.append(column)
    return keep, removed


def build_simulation_pool(x_test, y_test, x_val, y_val, features: list[str], seed: int,
                          per_class_cap: int = 500, min_per_class: int = 50) -> pd.DataFrame:
    """Labelled flows for the simulator, drawn ONLY from splits the model was not fitted on.

    Test-split flows are used first; validation-split flows top up classes that are too small.
    """
    parts = []
    test = x_test[features].assign(Label=y_test.to_numpy())
    val = x_val[features].assign(Label=y_val.to_numpy())
    for label in sorted(set(test["Label"]) | set(val["Label"])):
        rows = test[test["Label"] == label]
        if len(rows) < min_per_class:
            extra = val[val["Label"] == label]
            rows = pd.concat([rows, extra.head(min_per_class - len(rows))])
        if len(rows) > per_class_cap:
            rows = rows.sample(n=per_class_cap, random_state=seed)
        parts.append(rows)
    return pd.concat(parts, ignore_index=True)


def _top_importances(pipeline, features: list[str], top_n: int = 20) -> list[dict] | None:
    clf = pipeline.named_steps["clf"]
    importances = getattr(clf, "feature_importances_", None)
    if importances is None:
        return None
    order = np.argsort(importances)[::-1][:top_n]
    return [{"feature": features[i], "importance": float(importances[i])} for i in order]


def run_training(
    data_path: Path,
    out_dir: Path,
    *,
    seed: int = 42,
    max_rows: int | None = None,
    test_size: float = 0.2,
    val_size: float = 0.2,
    min_class_count: int = 10,
    rf_trees: int = 100,
    dataset_name: str = "CICIDS2017",
    dataset_version: str | None = None,
    is_synthetic: bool = False,
) -> dict:
    started = time.time()
    out_dir.mkdir(parents=True, exist_ok=True)

    raw, files = load_dataset(data_path)
    rows_loaded = len(raw)

    raw["Label"] = raw["Label"].map(normalize_label)
    missing_labels = int(raw["Label"].isna().sum())
    raw = raw[raw["Label"].notna()].reset_index(drop=True)

    numeric_cols, skipped_cols = select_numeric_columns(raw.drop(columns=["Label"]))
    x = raw[numeric_cols].apply(pd.to_numeric, errors="coerce").astype(np.float32)
    x = x.replace([np.inf, -np.inf], np.nan)
    y = raw["Label"].astype(str)
    del raw

    # Exact duplicate flows are removed BEFORE splitting so the same flow cannot sit in both train and test.
    combined = x.copy()
    combined["Label"] = y.to_numpy()
    before = len(combined)
    combined = combined.drop_duplicates().reset_index(drop=True)
    duplicates_removed = before - len(combined)

    counts = combined["Label"].value_counts()
    dropped_classes = {str(k): int(v) for k, v in counts[counts < min_class_count].items()}
    if dropped_classes:
        log.warning("Dropping classes with fewer than %d samples: %s", min_class_count, dropped_classes)
        combined = combined[~combined["Label"].isin(dropped_classes)].reset_index(drop=True)
    if BENIGN_LABEL not in set(combined["Label"]):
        raise ValueError(f"The data contains no '{BENIGN_LABEL}' class; cannot train a normal-vs-attack detector.")
    if combined["Label"].nunique() < 2:
        raise ValueError("At least two classes are required for training.")

    if max_rows:
        combined = stratified_sample(combined, max_rows, seed)

    y_all = combined["Label"]
    x_all = combined.drop(columns=["Label"])

    # 60/20/20 by default: stratified so minority classes appear in every split.
    x_trainval, x_test, y_trainval, y_test = train_test_split(
        x_all, y_all, test_size=test_size, stratify=y_all, random_state=seed
    )
    relative_val = val_size / (1.0 - test_size)
    x_train, x_val, y_train, y_val = train_test_split(
        x_trainval, y_trainval, test_size=relative_val, stratify=y_trainval, random_state=seed
    )
    log.info("Split sizes: train=%d val=%d test=%d", len(x_train), len(x_val), len(x_test))

    features, removed_features = select_features(x_train)
    log.info("Using %d features (%d removed)", len(features), len(removed_features))

    candidates: dict[str, dict] = {}
    fitted = {}
    classes = sorted(y_all.unique().tolist())
    for name in MODEL_NAMES:
        t0 = time.time()
        pipeline = build_pipeline(name, features, seed, rf_trees)
        pipeline.fit(x_train, y_train)
        fit_seconds = time.time() - t0
        val_eval = evaluate_predictions(y_val, pipeline.predict(x_val), classes, "validation split")
        candidates[name] = {
            "fit_seconds": round(fit_seconds, 2),
            "validation": {
                "accuracy": val_eval["accuracy"],
                "macro_precision": val_eval["macro_avg"]["precision"],
                "macro_recall": val_eval["macro_avg"]["recall"],
                "macro_f1": val_eval["macro_avg"]["f1"],
                "weighted_f1": val_eval["weighted_avg"]["f1"],
                "attack_recall": val_eval["binary_detection"]["recall"],
                "false_positive_rate": val_eval["binary_detection"]["false_positive_rate"],
            },
        }
        fitted[name] = pipeline
        log.info("%s: val macro-F1=%.4f (%.1fs)", name, val_eval["macro_avg"]["f1"], fit_seconds)

    # Selection uses the validation split only (macro-F1, then attack recall, then lower FPR).
    def _rank(name: str):
        v = candidates[name]["validation"]
        return (v["macro_f1"], v["attack_recall"] or 0.0, -(v["false_positive_rate"] or 0.0))

    selected = max(MODEL_NAMES, key=_rank)
    pipeline = fitted[selected]

    # The test split is touched exactly once, for the selected model.
    test_eval = evaluate_predictions(y_test, pipeline.predict(x_test), classes, "held-out test split")
    train_eval_accuracy = float(np.mean(pipeline.predict(x_train.head(20000)) == y_train.head(20000).to_numpy()))

    pool = build_simulation_pool(x_test, y_test, x_val, y_val, features, seed)

    trained_at = datetime.now(timezone.utc)
    version = f"{trained_at.strftime('%Y%m%dT%H%M%SZ')}-{selected}"
    supports_proba = hasattr(pipeline, "predict_proba")

    metadata = {
        "model_version": version,
        "model_type": selected,
        "trained_at": trained_at.isoformat(),
        "training_seconds": round(time.time() - started, 1),
        "random_seed": seed,
        "dataset": {
            "name": dataset_name,
            "version": dataset_version,
            "is_synthetic": is_synthetic,
            "files": files,
            "rows_loaded": rows_loaded,
            "rows_missing_label": missing_labels,
            "duplicates_removed": duplicates_removed,
            "classes_dropped_too_few_samples": dropped_classes,
            "rows_used": int(len(combined)),
            "max_rows_sampling": max_rows,
            "class_distribution": {str(k): int(v) for k, v in y_all.value_counts().items()},
            "non_numeric_columns_excluded": skipped_cols,
        },
        "split": {
            "strategy": "random stratified split by label",
            "train_rows": int(len(x_train)),
            "validation_rows": int(len(x_val)),
            "test_rows": int(len(x_test)),
            "caveat": (
                "Flows from the same capture session can be correlated, so a random split may "
                "overestimate performance on unseen networks or capture days."
            ),
        },
        "features": features,
        "removed_features": removed_features,
        "classes": classes,
        "benign_label": BENIGN_LABEL,
        "preprocessing": [
            "column names stripped of whitespace",
            "non-numeric, infinite and absurdly large values set to missing",
            "median imputation fitted on the training split",
            "standard scaling (logistic regression only)",
            "class_weight balanced to counter class imbalance",
        ],
        "candidates": candidates,
        "selection_criterion": "validation macro-F1, then attack recall, then lower false-positive rate",
        "supports_probability_estimates": bool(supports_proba),
        "confidence_note": (
            "Confidence is the model's predicted-class probability. For tree ensembles it is a vote "
            "share and is not a calibrated probability that an attack is occurring."
        ),
        "feature_importances": _top_importances(pipeline, features),
        "simulation_pool": {
            "source": "held-out test split (validation split tops up small classes); never used to fit the model",
            "per_class": {str(k): int(v) for k, v in pool["Label"].value_counts().items()},
        },
        "train_accuracy_sample": train_eval_accuracy,
        "library_versions": {"python": platform.python_version(), "scikit-learn": sklearn.__version__, "pandas": pd.__version__, "numpy": np.__version__},
    }

    evaluation = {
        "model_version": version,
        "selected_model": selected,
        "selected": test_eval,
        "candidates_validation": candidates,
    }

    joblib.dump({"pipeline": pipeline, "features": features, "classes": classes, "model_version": version}, out_dir / "intrusion_model.joblib", compress=3)
    joblib.dump({"model_version": version, "frame": pool}, out_dir / "simulation_pool.joblib", compress=3)
    (out_dir / "model_metadata.json").write_text(json.dumps(metadata, indent=2))
    (out_dir / "evaluation.json").write_text(json.dumps(evaluation, indent=2))
    log.info("Saved model %s to %s", version, out_dir)
    return metadata
