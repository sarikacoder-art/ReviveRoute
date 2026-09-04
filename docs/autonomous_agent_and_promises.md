# Autonomous agent and promise-to-pay boundary

## Autonomous worker

`RecoveryAgentWorker` starts and stops with the FastAPI lifecycle. While the process is awake, it polls every 10 seconds for due `SCHEDULED` cases and passes them to the same bounded executor used by the tested API path. Execution remains `SIMULATED`: no customer is contacted and no payment API is called.

`GET /api/v1/agent/status` exposes the heartbeat, poll cycles, executions, last error and external-call safety flags. Set `REVIVEROUTE_AGENT_ENABLED=false` when a deployment needs the worker disabled. A production deployment should run the worker as a separately supervised service with durable PostgreSQL locking; Render's free service sleeps when inactive, so it is not an always-on production worker.

## Promise-to-pay watchlist

Payment promises are a separate rules-based operations feature. They are not passed to the failed-payment recovery model. Status is derived from promised date and observed payment date:

- `PROMISE_ACTIVE`
- `DUE_TODAY`
- `PROMISE_BROKEN`
- `PROMISE_KEPT`
- `PAID_LATE`

The dashboard reports outstanding amount, broken promises, broken amount and kept rate. Its sample button creates fictional organization labels only. Names and customer identifiers are display and lookup fields, never ML features.

## Real-data readiness

The current action model remains trained on explicitly synthetic action-outcome history. Training it responsibly on real data requires consented, anonymized merchant history containing pre-decision context, intervention assignment and a verified recovery outcome. Public loan-default or credit-risk data cannot validate which failed-payment recovery action works and is therefore not presented as training evidence.
