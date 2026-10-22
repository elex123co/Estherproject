"""Train the intrusion-detection model and save the artifacts the API loads.

Real use (CICIDS2017 CSVs in a folder):
    python scripts/train.py --data ../data/CICIDS2017 --dataset-name CICIDS2017 --dataset-version MachineLearningCVE

Quick smoke test on synthetic data (clearly flagged as synthetic in the saved metadata):
    python scripts/generate_synthetic_data.py
    python scripts/train.py --data ../data/synthetic --synthetic --dataset-name synthetic-smoke-test

The full CICIDS2017 set is ~2.8M rows. If memory or time is limited, use --max-rows to take a
stratified sample (recorded in the model metadata).
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import REPO_ROOT  # noqa: E402
from app.ml.training import run_training  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", type=Path, required=True, help="CSV file or folder of CSV files")
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "models", help="output folder for model artifacts")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--max-rows", type=int, default=None, help="stratified sample size (default: use everything)")
    parser.add_argument("--test-size", type=float, default=0.2)
    parser.add_argument("--val-size", type=float, default=0.2)
    parser.add_argument("--min-class-count", type=int, default=10, help="drop classes with fewer samples than this")
    parser.add_argument("--rf-trees", type=int, default=100)
    parser.add_argument("--dataset-name", default="CICIDS2017")
    parser.add_argument("--dataset-version", default=None)
    parser.add_argument("--synthetic", action="store_true", help="mark the data as synthetic in the metadata")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    meta = run_training(
        args.data,
        args.out,
        seed=args.seed,
        max_rows=args.max_rows,
        test_size=args.test_size,
        val_size=args.val_size,
        min_class_count=args.min_class_count,
        rf_trees=args.rf_trees,
        dataset_name=args.dataset_name,
        dataset_version=args.dataset_version,
        is_synthetic=args.synthetic,
    )
    print(f"\nSelected model: {meta['model_type']}  (version {meta['model_version']})")
    for name, info in meta["candidates"].items():
        v = info["validation"]
        print(f"  {name:20s} validation macro-F1={v['macro_f1']:.4f}  accuracy={v['accuracy']:.4f}  fit={info['fit_seconds']}s")
    print(f"Artifacts written to {args.out}")


if __name__ == "__main__":
    main()
