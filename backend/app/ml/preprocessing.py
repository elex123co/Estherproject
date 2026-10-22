"""Reusable preprocessing shared by training and inference.

The same fitted pipeline object is saved with the model, so inference applies exactly the
transformations that were fitted on the training split.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.tree import DecisionTreeClassifier

MAX_ABS_VALUE = 1e30  # anything beyond this cannot be a real measurement and would overflow float32

MODEL_NAMES = ("random_forest", "decision_tree", "logistic_regression")


class NumericCleaner(BaseEstimator, TransformerMixin):
    """Select the expected feature columns and coerce them to clean numeric values.

    - non-numeric values become NaN
    - +/- infinity (present in CICIDS2017 rate columns) becomes NaN
    - absurdly large magnitudes become NaN
    Imputation of NaN values is performed by the next pipeline step, which is fitted on
    the training data only.
    """

    def __init__(self, feature_names: list[str] | None = None):
        self.feature_names = feature_names

    def fit(self, X, y=None):  # noqa: N803 - sklearn convention
        return self

    def transform(self, X):  # noqa: N803
        if not isinstance(X, pd.DataFrame):
            X = pd.DataFrame(X, columns=self.feature_names)
        missing = [c for c in (self.feature_names or []) if c not in X.columns]
        if missing:
            raise ValueError(f"Missing required feature columns: {missing[:10]}")
        selected = X[list(self.feature_names or [])]
        values = np.empty(selected.shape, dtype=np.float32)
        for j, column in enumerate(selected.columns):
            col = np.array(pd.to_numeric(selected[column], errors="coerce").to_numpy(dtype=np.float64, na_value=np.nan), dtype=np.float64, copy=True)
            col[~np.isfinite(col)] = np.nan
            col[np.abs(col) > MAX_ABS_VALUE] = np.nan
            values[:, j] = col
        return values

    def get_feature_names_out(self, input_features=None):
        return np.asarray(self.feature_names, dtype=object)


def count_invalid_per_row(frame: pd.DataFrame, feature_names: list[str]) -> np.ndarray:
    """Number of missing / non-numeric / infinite values in each row (before imputation)."""
    cleaned = NumericCleaner(feature_names).transform(frame)
    return np.isnan(cleaned).sum(axis=1)


def build_estimator(name: str, seed: int, rf_trees: int = 100):
    if name == "random_forest":
        return RandomForestClassifier(
            n_estimators=rf_trees,
            min_samples_leaf=1,
            class_weight="balanced_subsample",
            n_jobs=-1,
            random_state=seed,
        )
    if name == "decision_tree":
        return DecisionTreeClassifier(
            min_samples_leaf=2,
            class_weight="balanced",
            random_state=seed,
        )
    if name == "logistic_regression":
        return LogisticRegression(
            max_iter=500,
            class_weight="balanced",
            solver="lbfgs",
            random_state=seed,
        )
    raise ValueError(f"Unknown model name: {name}")


def build_pipeline(name: str, features: list[str], seed: int, rf_trees: int = 100) -> Pipeline:
    """Full pipeline: clean -> median impute -> (scale for logistic regression) -> classifier."""
    steps: list[tuple[str, object]] = [
        ("clean", NumericCleaner(feature_names=list(features))),
        ("impute", SimpleImputer(strategy="median", keep_empty_features=True)),
    ]
    if name == "logistic_regression":
        steps.append(("scale", StandardScaler()))
    steps.append(("clf", build_estimator(name, seed, rf_trees)))
    return Pipeline(steps)
