"""Leakage-safe features and temporal splitting for ReviveRoute."""

from dataclasses import dataclass

import pandas as pd

TARGET = "recovered_within_72_hours"
ACTIONS = ("NO_CONTACT", "LINK_NOW", "LINK_AFTER_2H", "LINK_NEXT_MORNING", "HUMAN_REVIEW")
ACTION_DELAYS = {"NO_CONTACT": 0, "LINK_NOW": 10, "LINK_AFTER_2H": 120, "LINK_NEXT_MORNING": 600, "HUMAN_REVIEW": 60}
CATEGORICAL_FEATURES = [
    "payment_method",
    "failure_reason",
    "historical_action",
    "reason_action",
    "action_degradation",
    "action_contact_band",
]
NUMERIC_FEATURES = [
    "amount_inr", "hour", "weekday", "customer_tenure_days", "prior_successes",
    "prior_failures", "prior_recoveries", "contacts_last_7_days",
    "recent_method_failure_rate", "degradation_flag", "action_delay_minutes",
    "event_day_index",
]
MODEL_FEATURES = CATEGORICAL_FEATURES + NUMERIC_FEATURES


@dataclass(frozen=True)
class TemporalSplit:
    train: pd.DataFrame
    validation: pd.DataFrame
    test: pd.DataFrame


def prepare_dataframe(dataframe: pd.DataFrame) -> pd.DataFrame:
    """Parse time, sort records, and create only decision-time features."""
    frame = dataframe.copy()
    frame["timestamp_utc"] = pd.to_datetime(frame["timestamp_utc"], utc=True)
    frame = frame.sort_values("timestamp_utc").reset_index(drop=True)
    start = frame["timestamp_utc"].min()
    frame["event_day_index"] = (frame["timestamp_utc"] - start).dt.total_seconds() / 86_400
    return frame


def temporal_split(dataframe: pd.DataFrame, train_fraction: float = 0.70, validation_fraction: float = 0.15) -> TemporalSplit:
    """Create chronological train/validation/test partitions."""
    if train_fraction <= 0 or validation_fraction <= 0 or train_fraction + validation_fraction >= 1:
        raise ValueError("Invalid temporal split fractions")
    frame = prepare_dataframe(dataframe)
    train_end = int(len(frame) * train_fraction)
    validation_end = train_end + int(len(frame) * validation_fraction)
    return TemporalSplit(frame.iloc[:train_end].copy(), frame.iloc[train_end:validation_end].copy(), frame.iloc[validation_end:].copy())


def model_matrix(dataframe: pd.DataFrame) -> pd.DataFrame:
    """Return approved inputs, excluding IDs and outcome leakage."""
    frame = dataframe.copy()
    frame["reason_action"] = frame["failure_reason"].astype(str) + "__" + frame["historical_action"].astype(str)
    frame["action_degradation"] = frame["historical_action"].astype(str) + "__" + frame["degradation_flag"].astype(str)
    contact_band = pd.cut(
        frame["contacts_last_7_days"],
        bins=[-1, 1, 3, float("inf")],
        labels=["low", "medium", "high"],
    ).astype(str)
    frame["action_contact_band"] = frame["historical_action"].astype(str) + "__" + contact_band
    missing = sorted(set(MODEL_FEATURES) - set(frame.columns))
    if missing:
        raise ValueError(f"Missing model features: {missing}")
    return frame[MODEL_FEATURES].copy()


def candidate_action_rows(case: pd.Series) -> pd.DataFrame:
    """Duplicate one case under every candidate action for scoring."""
    rows = []
    for action in ACTIONS:
        candidate = case.copy()
        candidate["historical_action"] = action
        candidate["action_delay_minutes"] = ACTION_DELAYS[action]
        rows.append(candidate)
    return pd.DataFrame(rows).reset_index(drop=True)
