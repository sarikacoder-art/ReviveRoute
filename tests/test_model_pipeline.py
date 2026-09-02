"""Tests for leakage-safe features and action-model training."""

from pathlib import Path

import numpy as np
import pandas as pd

from ml.features import ACTIONS, MODEL_FEATURES, candidate_action_rows, model_matrix, temporal_split
from ml.train_action_model import predict_calibrated, score_candidates, train_and_evaluate

DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "synthetic_recovery_history.csv"


def load_frame() -> pd.DataFrame:
    return pd.read_csv(DATA_PATH)


def test_temporal_split_is_ordered_and_complete():
    split = temporal_split(load_frame())
    assert (len(split.train), len(split.validation), len(split.test)) == (3500, 750, 750)
    assert split.train["timestamp_utc"].max() < split.validation["timestamp_utc"].min()
    assert split.validation["timestamp_utc"].max() < split.test["timestamp_utc"].min()


def test_model_matrix_excludes_ids_and_outcomes():
    matrix = model_matrix(temporal_split(load_frame()).train)
    assert list(matrix.columns) == MODEL_FEATURES
    assert {"event_id", "customer_id", "timestamp_utc", "recovered_within_72_hours", "recovered_amount_inr"}.isdisjoint(matrix.columns)


def test_candidate_rows_cover_every_action():
    case = temporal_split(load_frame()).test.iloc[0]
    assert tuple(candidate_action_rows(case)["historical_action"]) == ACTIONS


def test_training_metrics_and_probabilities_are_valid():
    bundle, report = train_and_evaluate(DATA_PATH)
    probabilities = predict_calibrated(bundle, temporal_split(load_frame()).test)
    assert len(probabilities) == 750 and np.isfinite(probabilities).all()
    assert ((probabilities >= 0) & (probabilities <= 1)).all()
    for metrics in report["models"].values():
        assert 0 <= metrics["pr_auc"] <= 1 and 0 <= metrics["roc_auc"] <= 1
        assert metrics["brier_score"] >= 0 and metrics["log_loss"] >= 0
    assert report["causal_claim"] is False


def test_action_scoring_returns_ranked_finite_values():
    bundle, _ = train_and_evaluate(DATA_PATH)
    scores = score_candidates(bundle, temporal_split(load_frame()).test.iloc[0])
    assert set(scores["action"]) == set(ACTIONS)
    assert scores["recovery_probability"].between(0, 1).all()
    assert scores["expected_recovered_amount"].is_monotonic_decreasing
