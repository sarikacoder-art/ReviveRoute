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
- Overall synthetic recovery: 30.62%
- No-contact spontaneous recovery: 13.12%
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

- ROC-AUC: 0.614
- PR-AUC: 0.348
- Brier score: 0.197
- Log loss: 0.575

```bash
python ml/train_action_model.py
```

Outputs:

- `models/action_model.joblib`
- `models/evaluation.json`

For each case, the S-learner scores every candidate action as `P(recovery within 72 hours | context, action)`. These are conditional predictions, **not causal uplift estimates**. Policy comparisons are labelled model-based and synthetic.

## Leakage controls

The model never receives event ID, customer ID, outcome timestamps, recovered amount or fields created after a decision. Historical aggregates contain only information available before decision time.

## Base pipeline coverage

```bash
python -m pytest -q
```

The Milestone 1–2 tests cover reproducibility, realism, context-action relationships, full-payment consistency, chronological splitting, leakage exclusion, probability validity and candidate-action ranking.

## Structure

```text
ReviveRoute/
├── app/audit.py
├── app/decision_engine.py
├── app/run_policy_demo.py
├── data/synthetic_recovery_history.csv
├── docs/model_card.md
├── docs/policy_card.md
├── ml/features.py
├── ml/generate_synthetic_data.py
├── ml/train_action_model.py
├── models/action_model.joblib
├── models/evaluation.json
├── tests/test_data_generator.py
├── tests/test_model_pipeline.py
├── tests/test_decision_engine.py
├── .gitignore
├── README.md
└── requirements.txt
```

## Milestone 3 — Bounded decision engine

`app/decision_engine.py` turns the five action probabilities into a next-best action using:

`expected net value = probability × amount − action cost − fatigue penalty`

The model proposes; deterministic rules dispose. Opt-out, already-recovered, expired, retry-exhausted and contact-fatigued cases stop. Sensitive failures and high-value cases escalate. Degradation and quiet-hour rules block unsafe timing. Every result includes human-readable reason codes and the complete candidate score table.

`app/audit.py` records decisions in an append-only SHA-256 hash chain, making later modification or reordering detectable. This is tamper-evident, not cryptographic proof of authorship or a replacement for immutable production storage.

Run the 100-case batch demonstration:

```bash
python -m app.run_policy_demo
```

This creates `models/policy_demo.json` and a locally ignored audit JSONL file. All amounts are explicitly labelled synthetic, model-based expectations—not observed revenue or causal uplift. Detailed policy assumptions are in `docs/policy_card.md`.

## Tests

```bash
python -m pytest -q
```

The Milestone 1–3 suite covers opt-out, payment-complete stopping, fatigue, retry exhaustion, expiry, escalation, degradation, India-local quiet hours, input validation, candidate scoring, batch evidence and audit tamper detection.

## Next milestone

## Milestone 4 — Persistent workflow API

`app/main.py` exposes the decision engine through FastAPI while `app/database.py` persists cases, all five candidate scores, state transitions and a global tamper-evident event chain in SQLite.

Start the service:

```bash
python -m uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000/docs` for the interactive API. Available endpoints include health, case intake, case list/detail, controlled transitions, aggregate summary and audit verification.

Event intake is idempotent. An identical replay returns the stored result without adding a second case; the same `event_id` with a changed payload returns HTTP 409. Terminal cases cannot be reopened, and invalid state transitions are rejected.

SQLite files are local runtime state and ignored by Git. API rupee totals remain explicitly labelled model-based expectations, not observed revenue.

Current result: **66 passed**. API tests cover validation, persistence across restarts, exact replay, conflicting replay, controlled transitions, terminal states, summary aggregation, audit creation and deliberate database-tampering detection. See `docs/api_contract.md` for the contract and state table.

## Next milestone

Milestone 5 will add signed Razorpay-style webhooks and a safely simulated executor before connecting Razorpay test-mode Payment Links. The dashboard follows once the full event loop is stable.
