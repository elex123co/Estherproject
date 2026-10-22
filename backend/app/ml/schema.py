"""Column and label conventions shared by training, validation and inference.

Nothing in this module hardcodes a feature list. The features the model uses are
discovered from the training data and stored in the model metadata; at inference time
the input is validated against that saved list.
"""
from __future__ import annotations

import re

import pandas as pd

BENIGN_LABEL = "BENIGN"

# Columns that identify a flow or describe its context. They are never model features.
# (Source Port is an ephemeral, identifier-like value; Destination Port is kept as a feature
# if present in the data because it describes the targeted service.)
METADATA_COLUMNS = {
    "flow id",
    "source ip",
    "src ip",
    "source port",
    "src port",
    "destination ip",
    "dst ip",
    "timestamp",
    "label",
    "unnamed: 0",
    "index",
    "id",
}

LABEL_COLUMN = "label"

# Optional context columns that are stored next to a prediction for analyst review.
CONTEXT_COLUMNS = {
    "timestamp": ["timestamp"],
    "src_ip": ["source ip", "src ip"],
    "src_port": ["source port", "src port"],
    "dst_ip": ["destination ip", "dst ip"],
    "dst_port": ["destination port", "dst port"],
}


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Strip stray whitespace from column names (CICIDS2017 headers contain leading spaces).

    Names that collide after stripping receive a numeric suffix so no column is lost.
    """
    seen: dict[str, int] = {}
    names: list[str] = []
    for raw in df.columns:
        name = re.sub(r"\s+", " ", str(raw)).strip()
        if name in seen:
            seen[name] += 1
            name = f"{name}.{seen[name]}"
        else:
            seen[name] = 0
        names.append(name)
    df = df.copy()
    df.columns = names
    return df


def find_column(df: pd.DataFrame, candidates: list[str]) -> str | None:
    """Return the real column name matching any lowercase candidate, case-insensitively."""
    lookup = {c.lower(): c for c in df.columns}
    for candidate in candidates:
        if candidate in lookup:
            return lookup[candidate]
    return None


def normalize_label(value: object) -> str | None:
    """Clean a ground-truth or predicted label.

    CICIDS2017 files contain a mis-encoded dash in the web-attack labels
    ("Web Attack � Brute Force"). Any run of non-ASCII characters is replaced by a plain
    dash so that the same class always has the same name.
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return None
    text = re.sub(r"\s*[^\x00-\x7f]+\s*", " - ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if text.upper() == BENIGN_LABEL:
        return BENIGN_LABEL
    return text


def is_metadata_column(name: str) -> bool:
    return name.strip().lower() in METADATA_COLUMNS
