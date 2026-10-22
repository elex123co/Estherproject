"""Input validation: inspect an uploaded CSV and decide whether the model can score it."""
from __future__ import annotations

from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

from ..ml.data_loader import detect_encoding
from ..ml.preprocessing import NumericCleaner
from ..ml.schema import (
    CONTEXT_COLUMNS,
    LABEL_COLUMN,
    find_column,
    is_metadata_column,
    normalize_columns,
    normalize_label,
)


class ValidationError(Exception):
    """Raised for input that cannot be read as a CSV at all."""


def validate_csv(path: Path, required_features: list[str], chunk_rows: int = 50_000) -> dict:
    """Scan the whole file in chunks and report structure, data quality and model compatibility."""
    encoding = detect_encoding(path)
    try:
        reader = pd.read_csv(path, encoding=encoding, chunksize=chunk_rows, low_memory=False)
        first = next(reader, None)
    except (pd.errors.EmptyDataError, pd.errors.ParserError, UnicodeDecodeError) as exc:
        raise ValidationError(f"The file could not be parsed as CSV: {exc}") from exc
    if first is None or first.empty:
        raise ValidationError("The file contains no data rows.")

    first = normalize_columns(first)
    columns = list(first.columns)
    required = list(required_features)
    missing_required = [c for c in required if c not in columns]
    label_col = find_column(first, [LABEL_COLUMN])
    context = {key: find_column(first, cands) for key, cands in CONTEXT_COLUMNS.items()}
    context = {k: v for k, v in context.items() if v}
    known = set(required) | ({label_col} if label_col else set()) | set(context.values())
    unexpected = [c for c in columns if c not in known and not is_metadata_column(c)]
    metadata_cols = [c for c in columns if is_metadata_column(c) and c != label_col and c not in context.values()]

    rows = 0
    missing_total = 0
    invalid_total = 0  # non-numeric or infinite values in model feature columns
    rows_with_issue = 0
    label_counts: Counter = Counter()
    hash_parts: list[np.ndarray] = []
    usable = [c for c in required if c in columns]
    cleaner = NumericCleaner(usable) if usable else None

    def process(chunk: pd.DataFrame) -> None:
        nonlocal rows, missing_total, invalid_total, rows_with_issue
        rows += len(chunk)
        hash_parts.append(pd.util.hash_pandas_object(chunk.astype(str), index=False).to_numpy())
        if label_col:
            label_counts.update(chunk[label_col].map(normalize_label).fillna("(missing label)"))
        if cleaner is not None:
            present = chunk[usable]
            cleaned = cleaner.transform(chunk)
            bad_mask = np.isnan(cleaned)
            raw_missing = present.isna().to_numpy()
            missing_total += int(raw_missing.sum())
            invalid_total += int((bad_mask & ~raw_missing).sum())
            rows_with_issue += int(bad_mask.any(axis=1).sum())

    process(first)
    try:
        for chunk in reader:
            process(normalize_columns(chunk))
    except (pd.errors.ParserError, UnicodeDecodeError) as exc:
        raise ValidationError(f"The file is malformed partway through: {exc}") from exc

    all_hashes = np.concatenate(hash_parts)
    duplicates = int(len(all_hashes) - len(np.unique(all_hashes)))

    errors: list[str] = []
    warnings: list[str] = []
    if missing_required:
        shown = ", ".join(missing_required[:8]) + (" ..." if len(missing_required) > 8 else "")
        errors.append(
            f"{len(missing_required)} of the {len(required)} features the model needs are missing "
            f"(for example: {shown}). The file does not match the model's feature schema."
        )
    if rows_with_issue and not missing_required:
        warnings.append(
            f"{rows_with_issue} rows contain missing, non-numeric or infinite values in model features. "
            "They will be imputed using training-set medians and flagged on the record."
        )
    if duplicates:
        warnings.append(f"{duplicates} duplicate rows were found. They are analyzed as separate records.")
    if unexpected:
        warnings.append(f"{len(unexpected)} columns are not used by the model and will be ignored.")
    if not label_col:
        warnings.append("No 'Label' column found. Analysis will run, but predictions cannot be compared with ground truth.")

    return {
        "rows": rows,
        "columns_total": len(columns),
        "features_expected": len(required),
        "features_detected": len(required) - len(missing_required),
        "missing_required_features": missing_required,
        "unexpected_columns": unexpected,
        "metadata_columns": metadata_cols,
        "context_columns_found": context,
        "label_column_present": bool(label_col),
        "label_distribution": dict(label_counts.most_common()) if label_col else None,
        "missing_values": missing_total,
        "invalid_values": invalid_total,
        "rows_with_data_issues": rows_with_issue,
        "duplicate_rows": duplicates,
        "compatible": not missing_required,
        "errors": errors,
        "warnings": warnings,
        "encoding": encoding,
    }


def validate_record(record: dict, required_features: list[str]) -> list[str]:
    """Return a list of problems for a single JSON record (empty list means acceptable)."""
    problems = []
    missing = [c for c in required_features if c not in {str(k).strip() for k in record}]
    if missing:
        shown = ", ".join(missing[:8]) + (" ..." if len(missing) > 8 else "")
        problems.append(f"Record is missing {len(missing)} required features (for example: {shown}).")
    return problems
