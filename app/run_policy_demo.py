"""Run the bounded policy over a synthetic batch and create audit evidence."""

from __future__ import annotations

import json
from collections import Counter
from datetime import timedelta
from pathlib import Path

import pandas as pd

from app.decision_engine import DecisionEngine, RecoveryCase

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = PROJECT_ROOT / "data" / "synthetic_recovery_history.csv"
AUDIT_PATH = PROJECT_ROOT / "data" / "policy_audit.jsonl"
SUMMARY_PATH = PROJECT_ROOT / "models" / "policy_demo.json"


def run_demo(limit: int = 100) -> dict:
    data = pd.read_csv(DATA_PATH).tail(limit)
    engine = DecisionEngine()
    decisions = []
    for _, row in data.iterrows():
        case = RecoveryCase.from_series(row)
        decisions.append(engine.decide(case, now=case.timestamp_utc + timedelta(minutes=1)))

    total_at_risk = float(data["amount_inr"].sum())
    expected_recovered = float(sum(max(decision.expected_net_value, 0.0) for decision in decisions))
    summary = {
        "evidence_label": "synthetic model-based policy demonstration; not causal uplift",
        "batch_cases": len(decisions),
        "revenue_at_risk_inr": round(total_at_risk, 2),
        "expected_net_recovery_inr": round(expected_recovered, 2),
        "expected_net_recovery_rate": round(expected_recovered / total_at_risk, 4),
        "action_distribution": dict(Counter(decision.selected_action for decision in decisions)),
        "workflow_status_distribution": dict(Counter(decision.workflow_status for decision in decisions)),
        "audit_entries": len(engine.audit.entries),
        "audit_chain_valid": engine.audit.verify(),
        "limitations": [
            "Values are predictions on synthetic data, not money observed after deployment.",
            "Real uplift must be measured with randomized assignment and Razorpay webhook outcomes.",
        ],
    }
    engine.audit.write_jsonl(AUDIT_PATH)
    SUMMARY_PATH.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


if __name__ == "__main__":
    print(json.dumps(run_demo(), indent=2))

