"""CSV loading helpers that tolerate the quirks of CICIDS2017 files."""
from __future__ import annotations

import codecs
from pathlib import Path
from typing import Iterator

import pandas as pd

from .schema import normalize_columns


def detect_encoding(path: Path) -> str:
    """CICIDS2017 CSVs are not always valid UTF-8; fall back to latin-1 when needed."""
    decoder = codecs.getincrementaldecoder("utf-8")(errors="strict")
    try:
        with open(path, "rb") as handle:
            while True:
                block = handle.read(4 * 1024 * 1024)
                if not block:
                    decoder.decode(b"", final=True)
                    break
                decoder.decode(block)
        return "utf-8"
    except UnicodeDecodeError:
        return "latin-1"


def read_csv(path: Path, **kwargs) -> pd.DataFrame:
    frame = pd.read_csv(path, encoding=detect_encoding(path), low_memory=False, **kwargs)
    return normalize_columns(frame)


def iter_csv_chunks(path: Path, chunk_rows: int) -> Iterator[pd.DataFrame]:
    encoding = detect_encoding(path)
    for chunk in pd.read_csv(path, encoding=encoding, chunksize=chunk_rows, low_memory=False):
        yield normalize_columns(chunk)


def list_csv_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    files = sorted(p for p in path.rglob("*.csv") if p.is_file())
    if not files:
        raise FileNotFoundError(f"No CSV files found under {path}")
    return files
