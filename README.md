# ReviveRoute

ReviveRoute is a bounded next-best-action prototype for recovering failed Razorpay payments, built for the Razorpay AI Buildathon Revenue Recovery track.

## Evidence boundary

This repository currently uses **synthetic payment history only**. Its metrics demonstrate that the data, training, scoring and safety pipeline work under documented assumptions. They do not prove production uplift or represent real merchant revenue. A real rollout would require consented merchant data and a randomised controlled experiment.

## Milestone 1 — Validated synthetic history

`ml/generate_synthetic_data.py` creates 5,000 chronological failed-payment cases using seed 42.

- Date range: 1 March–27 August 2026
- Unique customers: 802
- Median failed amount: ₹2,450.70
- Mean failed amount: ₹4,921.16
- Overall synthetic recovery: 31.28%
- No-contact spontaneous recovery: 12.49%
- Missing values: 0
- Five candidate recovery actions

The hidden simulator includes action-context interactions, degradation effects, contact fatigue, noise and temporal drift. A successful recovery represents full payment of one failed transaction; partial recovery is out of scope.

```bash
python ml/generate_synthetic_data.py
```

## Milestone 2 — Calibrated action-outcome model

`ml/train_action_model.py` performs a chronological split:

- Oldest 70%: training, 3,500 rows
- Next 15%: calibration and model selection, 750 rows
- Latest 15%: untouched test period, 750 rows

It compares calibrated logistic regression with calibrated histogram gradient boosting. The selected model has the lowest validation-period Brier score. Explicit action-failure, action-degradation and action-contact interactions represent heterogeneous recovery patterns.

Selected calibrated logistic model on the held-out synthetic test period:

- ROC-AUC: 0.676
- PR-AUC: 0.438
- Brier score: 0.196
- Log loss: 0.573

```bash
python ml/train_action_model.py
```

Outputs:

- `models/action_model.joblib`
- `models/evaluation.json`

For each case, the S-learner scores every candidate action as `P(recovery within 72 hours | context, action)`. These are conditional predictions, **not causal uplift estimates**. Policy comparisons are labelled model-based and synthetic.

## Leakage controls

The model never receives event ID, customer ID, outcome timestamps, recovered amount or fields created after a decision. Historical aggregates contain only information available before decision time.

## Tests

```bash
python -m pytest -q
```

Current result: **43 passed**. Tests cover reproducibility, realism, context-action relationships, full-payment consistency, chronological splitting, leakage exclusion, probability validity and candidate-action ranking.

## Structure

```text
ReviveRoute/
├── data/synthetic_recovery_history.csv
├── docs/model_card.md
├── ml/features.py
├── ml/generate_synthetic_data.py
├── ml/train_action_model.py
├── models/action_model.joblib
├── models/evaluation.json
├── tests/test_data_generator.py
├── tests/test_model_pipeline.py
├── .gitignore
├── README.md
└── requirements.txt
```

## Next milestone

Milestone 3 will implement deterministic guardrails, stopping rules, expected-net-value selection and a tamper-evident audit chain. Razorpay test-mode integration and the dashboard follow after the safety core is tested.
