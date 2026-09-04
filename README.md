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
├── app/database.py
├── app/decision_engine.py
├── app/executor.py
├── app/main.py
├── app/run_policy_demo.py
├── app/schemas.py
├── app/webhooks.py
├── data/synthetic_recovery_history.csv
├── docs/api_contract.md
├── docs/model_card.md
├── docs/policy_card.md
├── docs/webhook_security.md
├── ml/features.py
├── ml/generate_synthetic_data.py
├── ml/train_action_model.py
├── models/action_model.joblib
├── models/evaluation.json
├── tests/test_data_generator.py
├── tests/test_model_pipeline.py
├── tests/test_decision_engine.py
├── tests/test_api.py
├── tests/test_webhooks.py
├── .env.example
├── .gitignore
├── pytest.ini
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

## Milestone 4 — Persistent workflow API

`app/main.py` exposes the decision engine through FastAPI while `app/database.py` persists cases, all five candidate scores, state transitions and a global tamper-evident event chain in SQLite.

Start the service:

```bash
python -m uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000/docs` for the interactive API. Available endpoints include health, case intake, case list/detail, controlled transitions, aggregate summary and audit verification.

Event intake is idempotent. An identical replay returns the stored result without adding a second case; the same `event_id` with a changed payload returns HTTP 409. Terminal cases cannot be reopened, and invalid state transitions are rejected.

SQLite files are local runtime state and ignored by Git. Hosted deployments can set `DATABASE_URL` to a managed PostgreSQL URL so cases, scheduled actions, outcomes and the audit chain survive service restarts. API rupee totals remain explicitly labelled model-based expectations, not observed revenue.

API tests cover validation, persistence across restarts, exact replay, conflicting replay, controlled transitions, terminal states, summary aggregation, audit creation and deliberate database-tampering detection. See `docs/api_contract.md` for the contract and state table.

## Milestone 5 — Signed webhooks and safe execution

`POST /webhooks/razorpay` verifies `X-Razorpay-Signature` against the exact raw body using HMAC-SHA256, then deduplicates with `X-Razorpay-Event-Id`. It supports `payment.failed` intake and `payment_link.paid` recovery attribution. Invalid signatures fail closed; exact retries are idempotent; conflicting reuse returns HTTP 409.

`POST /api/v1/executor/run-due` runs only due link actions in `SIMULATED` mode. It never contacts a customer or payment API, and creates only non-routable `example.invalid` artifacts. A paid event must match its unique recovery reference and the full failed amount.

Set a local webhook secret before starting the API:

```powershell
$env:RAZORPAY_WEBHOOK_SECRET="choose-a-long-random-local-secret"
python -m uvicorn app.main:app --reload
```

Predicted expected recovery and signed demo/test observed recovery are reported separately. See `docs/webhook_security.md` for the security and evidence boundary.

Security tests cover exact raw-body verification, missing configuration, invalid signatures, event-ID replay and conflict, deterministic taxonomy, paise conversion, safe execution, human-review isolation, full recovery attribution, amount matching and audit continuity.

## Milestone 6 — Judge dashboard and one-click proof

Open `http://127.0.0.1:8000/` after starting the service. The operator dashboard displays revenue at risk, model-based expected recovery, signed simulated/test outcomes, action and workflow distributions, searchable case details, all candidate scores, guardrail reasons and audit verification.

The **Run end-to-end demo** button creates a unique signed `payment.failed` fixture, verifies it, maps and diagnoses the failure, scores all actions, applies deterministic policy, executes only a non-routable simulated artifact, verifies a signed `payment_link.paid` fixture, attributes ₹1,800 to the exact recovery reference and closes the case as `RECOVERED`. It makes no customer contact and no Razorpay API call. Expected and observed-demo metrics remain visibly separated.

## Milestone 8 — Merchant intake and batch exploration

The dashboard now lets an external evaluator enter one fictional failed payment, import a CSV batch, download the canonical template or load 25 clearly labelled synthetic sample cases. Every accepted case follows the same model, guardrail, persistence and audit path as webhook-created cases.

CSV imports are bounded to 512 KB and 100 rows. Required fields, enum values, amounts and timezone-aware timestamps are validated; failures include row numbers; exact event replays remain idempotent. The public hosted build is explicitly labelled a disposable sandbox and instructs users not to submit sensitive data. Production use requires authentication, tenant isolation, rate limiting and durable storage; signed Razorpay webhooks remain the production-shaped entry path.

Current result: **88 passed**. Intake tests cover the downloadable template, valid and invalid rows, defaults, idempotent replay, byte and row limits, sample-batch bounds, evidence labels and dashboard controls. See `docs/merchant_intake.md`.

## Milestone 9 — Visible autonomous agent and promise watchlist

`app/agent_worker.py` now runs the bounded executor continuously while the API process is awake. The dashboard exposes its heartbeat, poll cycles and safe executions, making the autonomous observe-decide-execute loop visible. Execution is still deliberately simulated.

A separate rules-based promise-to-pay watchlist shows active, due, kept, late-paid and broken commitments plus outstanding and overdue money. Sample names are fictional display labels and identity is never used as an ML feature. The recovery model remains honestly labelled synthetic until consented merchant action-outcome history is available. See `docs/autonomous_agent_and_promises.md`.

## Milestone 10 — Always-ready public demonstration

An empty deployed database is now populated automatically with 40 synthetic failed payments, a varied portfolio of signed simulated recoveries, and six fictional payment promises before the autonomous worker starts. Recovered examples span multiple failure reasons and the `LINK_NOW`, `LINK_AFTER_2H`, and `LINK_NEXT_MORNING` options. Seeding is idempotent, independently checks both datasets and can be disabled with `REVIVEROUTE_AUTO_SEED=false`. This prevents an empty judge dashboard after Render resets its temporary filesystem. See `docs/public_demo_seed.md`.

## Milestone 12 — evidence-first judge readiness

- The seed uses Indian business-hour timestamps so the real decision engine can demonstrate `LINK_NOW`, `LINK_AFTER_2H` and `LINK_NEXT_MORNING` instead of collapsing to one quiet-hour-safe option.
- **Prove autonomous execution** creates a fictional due case and waits for the background worker—not the button handler—to execute it.
- Agent status now distinguishes process-local activity from persisted execution evidence that survives a restart.
- Observed recovery includes an executed-case denominator, recovery rate and a failure-reason/action/amount breakdown.
- A credential-gated `RazorpayTestClient` accepts only `rzp_test_` keys, disables customer notifications and remains inactive unless explicitly configured.
- Public copy now states that merchant authentication, rate limiting and tenant isolation are required before production use. The demo does not claim those controls already exist.
- Executor errors are contained and surfaced in agent status instead of terminating the polling loop.

Current verification: **103 passing tests**. See `docs/judge_readiness.md`.

## Deployment boundary

## Milestone 13 — Razorpay Test Mode execution

Set `RAZORPAY_TEST_MODE_ENABLED=true` together with private `rzp_test_` credentials to activate the hybrid executor. Only cases originating from a verified Razorpay webhook can call the Payment Links API; manual, CSV and synthetic cases remain simulated. Notifications and reminders are disabled, live key IDs are rejected, provider failures are audited, and `payment_link.paid` closes the exact attributed case. See `docs/razorpay_test_mode.md`.

Without this explicit switch and valid test credentials, ReviveRoute remains fully simulated.

## Milestone 14 — Durable hosted state

ReviveRoute now selects managed PostgreSQL whenever `DATABASE_URL` is configured, while preserving SQLite for local development and tests. The health response exposes only the backend type (`POSTGRESQL` or `SQLITE`), never the connection string. See `docs/durable_postgres.md` for the Render setup and restart-survival check.
