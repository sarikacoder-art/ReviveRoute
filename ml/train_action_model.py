"""Train and evaluate ReviveRoute's next-best-action outcome model."""

import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, log_loss, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

try:
    from ml.features import ACTION_DELAYS, ACTIONS, CATEGORICAL_FEATURES, MODEL_FEATURES, NUMERIC_FEATURES, TARGET, candidate_action_rows, model_matrix, temporal_split
except ModuleNotFoundError:
    from features import ACTION_DELAYS, ACTIONS, CATEGORICAL_FEATURES, MODEL_FEATURES, NUMERIC_FEATURES, TARGET, candidate_action_rows, model_matrix, temporal_split

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = PROJECT_ROOT / "data" / "synthetic_recovery_history.csv"
MODEL_PATH = PROJECT_ROOT / "models" / "action_model.joblib"
REPORT_PATH = PROJECT_ROOT / "models" / "evaluation.json"


def make_preprocessor() -> ColumnTransformer:
    categorical = Pipeline([("imputer", SimpleImputer(strategy="most_frequent")), ("onehot", OneHotEncoder(handle_unknown="ignore", sparse_output=False))])
    numeric = Pipeline([("imputer", SimpleImputer(strategy="median")), ("scale", StandardScaler())])
    return ColumnTransformer([("categorical", categorical, CATEGORICAL_FEATURES), ("numeric", numeric, NUMERIC_FEATURES)])


def make_logistic_pipeline() -> Pipeline:
    return Pipeline([("preprocess", make_preprocessor()), ("model", LogisticRegression(max_iter=1500, class_weight="balanced", random_state=42))])


def make_tree_pipeline() -> Pipeline:
    model = HistGradientBoostingClassifier(learning_rate=0.06, max_iter=180, max_leaf_nodes=15, min_samples_leaf=30, l2_regularization=1.0, random_state=42)
    return Pipeline([("preprocess", make_preprocessor()), ("model", model)])


def metric_bundle(y_true: pd.Series, probabilities: np.ndarray) -> dict[str, float]:
    clipped = np.clip(probabilities, 1e-6, 1 - 1e-6)
    return {"pr_auc": float(average_precision_score(y_true, clipped)), "roc_auc": float(roc_auc_score(y_true, clipped)), "brier_score": float(brier_score_loss(y_true, clipped)), "log_loss": float(log_loss(y_true, clipped))}


def predict_calibrated(bundle: dict, frame: pd.DataFrame) -> np.ndarray:
    raw = bundle["model"].predict_proba(model_matrix(frame))[:, 1]
    return np.asarray(bundle["calibrator"].predict(raw), dtype=float)


def calibrated_bundle(model: Pipeline, validation: pd.DataFrame, y_validation: pd.Series, version: str) -> dict:
    """Fit an isotonic calibration map using only the validation period."""
    raw = model.predict_proba(model_matrix(validation))[:, 1]
    calibrator = IsotonicRegression(out_of_bounds="clip", y_min=0.01, y_max=0.99)
    calibrator.fit(raw, y_validation)
    return {
        "model": model,
        "calibrator": calibrator,
        "model_features": MODEL_FEATURES,
        "actions": ACTIONS,
        "target": TARGET,
        "version": version,
    }


def score_candidates(bundle: dict, case: pd.Series) -> pd.DataFrame:
    candidates = candidate_action_rows(case)
    probabilities = predict_calibrated(bundle, candidates)
    result = pd.DataFrame({"action": ACTIONS, "recovery_probability": probabilities, "expected_recovered_amount": probabilities * float(case["amount_inr"])})
    return result.sort_values("expected_recovered_amount", ascending=False).reset_index(drop=True)


def policy_estimates(bundle: dict, test: pd.DataFrame) -> dict[str, dict[str, float]]:
    """Model-based offline estimates; these are not causal uplift claims."""
    estimates = {}
    columns = []
    for action in ACTIONS:
        candidate = test.copy()
        candidate["historical_action"] = action
        candidate["action_delay_minutes"] = ACTION_DELAYS[action]
        probabilities = predict_calibrated(bundle, candidate)
        columns.append(probabilities)
        estimates[action] = {"predicted_recovery_rate": float(probabilities.mean()), "predicted_recovered_amount": float(np.sum(probabilities * candidate["amount_inr"].to_numpy()))}
    best = np.column_stack(columns).max(axis=1)
    estimates["MODEL_RANKED"] = {"predicted_recovery_rate": float(best.mean()), "predicted_recovered_amount": float(np.sum(best * test["amount_inr"].to_numpy()))}
    return estimates


def train_and_evaluate(data_path: Path = DATA_PATH) -> tuple[dict, dict]:
    split = temporal_split(pd.read_csv(data_path))
    x_train, y_train = model_matrix(split.train), split.train[TARGET]
    x_validation, y_validation = model_matrix(split.validation), split.validation[TARGET]
    x_test, y_test = model_matrix(split.test), split.test[TARGET]

    logistic = make_logistic_pipeline()
    logistic.fit(x_train, y_train)
    logistic_bundle = calibrated_bundle(logistic, split.validation, y_validation, "logistic-milestone-2.0")
    logistic_probabilities = predict_calibrated(logistic_bundle, split.test)
    tree = make_tree_pipeline()
    tree.fit(x_train, y_train)
    tree_bundle = calibrated_bundle(tree, split.validation, y_validation, "tree-milestone-2.0")
    tree_probabilities = predict_calibrated(tree_bundle, split.test)
    logistic_validation = predict_calibrated(logistic_bundle, split.validation)
    tree_validation = predict_calibrated(tree_bundle, split.validation)
    validation_brier = {
        "calibrated_logistic_regression": float(brier_score_loss(y_validation, logistic_validation)),
        "calibrated_hist_gradient_boosting": float(brier_score_loss(y_validation, tree_validation)),
    }
    selected_name = min(validation_brier, key=validation_brier.get)
    bundle = logistic_bundle if selected_name == "calibrated_logistic_regression" else tree_bundle
    report = {
        "evidence_label": "offline evaluation on a held-out synthetic temporal test set",
        "causal_claim": False,
        "split": {"train_rows": len(split.train), "validation_rows": len(split.validation), "test_rows": len(split.test), "train_end": split.train["timestamp_utc"].max().isoformat(), "validation_end": split.validation["timestamp_utc"].max().isoformat(), "test_end": split.test["timestamp_utc"].max().isoformat()},
        "test_recovery_rate": float(y_test.mean()),
        "selection_metric": "lowest validation-period Brier score",
        "validation_brier": validation_brier,
        "selected_model": selected_name,
        "models": {"calibrated_logistic_regression": metric_bundle(y_test, logistic_probabilities), "calibrated_hist_gradient_boosting": metric_bundle(y_test, tree_probabilities)},
        "policy_estimates": policy_estimates(bundle, split.test),
        "limitations": ["Training and evaluation data are synthetic.", "Policy values are model-based estimates, not observed counterfactual outcomes.", "Real merchant uplift requires a randomized controlled experiment."],
    }
    return bundle, report


def main() -> None:
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    bundle, report = train_and_evaluate()
    joblib.dump(bundle, MODEL_PATH)
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Saved model: {MODEL_PATH}")
    print(f"Saved evaluation: {REPORT_PATH}")
    print(json.dumps(report["models"], indent=2))
    print("\nPolicy estimates are synthetic, model-based, and non-causal.")


if __name__ == "__main__":
    main()
