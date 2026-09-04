# ReviveRoute

**Track:** AI Revenue Recovery  
**Build:** Solo  
**Scope:** One-time failed Razorpay payment recovery

## One-line pitch

ReviveRoute detects a failed payment, diagnoses why it failed, scores the next-best recovery action, enforces deterministic safety rules, executes a bounded workflow and attributes the signed recovery outcome—with measured money and a tamper-evident audit trail.

## Problem

Revenue does not disappear in one clean step. A failed payment may be caused by insufficient funds, a network issue, a blocked card, a bank limit or a risk decline. Treating every failure as “retry now” can waste attempts, increase contact fatigue or automate a sensitive case.

## Solution

ReviveRoute combines:

- HMAC-verified, idempotent Razorpay-style webhook intake;
- deterministic failure diagnosis and customer-context enrichment;
- calibrated action-specific recovery probabilities;
- expected-net-value ranking across five interventions;
- stopping, fatigue, timing and escalation guardrails;
- a persistent SQLite workflow state machine;
- safe simulated execution with no external calls;
- signed outcome attribution and separately labelled metrics;
- a persistent SHA-256 audit chain and verifier;
- a judge-facing dashboard with a one-click end-to-end demo.
- manual and bounded CSV merchant intake, a downloadable template and a synthetic sample-batch explorer.
- a lifecycle-managed autonomous worker with a visible heartbeat and safe due-action execution;
- a separate promise-to-pay watchlist using fictional demo labels and deterministic status rules.

## Why it is differentiated

The model is not allowed to act directly. It proposes probabilities for every intervention, while deterministic policy defines what may execute. This makes each decision inspectable, prevents unsafe automation and keeps the evidence boundary explicit.

## Demonstration

Start the service and open the dashboard:

```powershell
python -m uvicorn app.main:app --reload
```

Visit `http://127.0.0.1:8000/` and click **Run end-to-end demo**. A unique signed ₹1,800 failed-payment case moves through:

`DETECTED → DIAGNOSED → DECIDED → EXECUTED → RECOVERED`

The demonstration contacts no customer and calls no payment API.

## Validation

- 94 automated tests cover data, model, policy, persistence, webhooks, attribution, autonomous execution, promise tracking, merchant intake, dashboard and audit integrity.
- Invalid signatures fail closed.
- Exact webhook retries are idempotent; conflicting replays are rejected.
- Paid outcomes require an existing recovery reference and matching full amount.
- Audit-tampering tests verify that modification is detected.

## Evidence boundary

The dataset is synthetic. Predictions are model-based and non-causal. The ₹1,800 demo outcome is signed local simulation—not production revenue. Real uplift requires randomized assignment and real Razorpay outcomes.

## Technology

Python 3.12, FastAPI, SQLite, pandas, NumPy, scikit-learn, joblib, pytest, HTML, CSS and vanilla JavaScript.
