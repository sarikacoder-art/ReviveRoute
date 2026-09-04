# Judge-readiness and evidence boundaries

## What the live demo proves

1. Failed payments enter through manual, CSV or signed-webhook intake.
2. The calibrated model scores five actions and deterministic rules may block or override them.
3. The background worker polls the due queue and performs only bounded link actions.
4. Signed paid events are attributed to an exact recovery reference before money is counted.
5. Observed simulated/test recovery is reported by failure reason, action, case count and amount.
6. Escalations, stops, executions and outcomes remain in a verifiable SHA-256 audit chain.

The **Prove autonomous execution** button does not itself execute an action. It creates an explicitly fictional due case, then waits for the independently running worker to discover and execute it. The response states `button_executed_action: false` and returns the resulting audit evidence.

## Razorpay test mode

`app/razorpay_test.py` is an optional, test-only payment-link client. It:

- rejects keys that do not begin with `rzp_test_`;
- never exposes the configured secret in status responses;
- sends amounts in paise;
- disables SMS, email and automatic reminders by default;
- is inactive when credentials are absent.

Configure `RAZORPAY_TEST_KEY_ID` and `RAZORPAY_TEST_KEY_SECRET` only in deployment secrets. The current public workflow remains a signed simulation until a merchant explicitly supplies test credentials and completes test-mode integration. No production or live credential is accepted by this adapter.

## Honest production boundary

Implemented now: Razorpay-compatible webhook parsing, HMAC signature verification, replay/conflict detection, exact reference and amount attribution, bounded decisions, simulated execution, agent lifecycle, persistence and audit verification.

Required before production: merchant authentication, tenant-scoped storage and queries, rate limiting, durable managed storage, approved communication templates, consent/opt-out integration, secrets management, monitoring and a randomized uplift experiment using real merchant outcomes.

## Metric definitions

- **Revenue at risk:** sum of failed-payment amounts in the current case store.
- **Expected net recovery:** model-based expected value after action cost and fatigue penalty; it is neither observed nor causal.
- **Observed recovery:** amount from signed simulated/test paid events that match one stored execution reference and exact failed-payment amount.
- **Observed recovery rate:** recovered executed cases divided by all persisted executed cases. Escalated, stopped and never-executed cases are excluded from this denominator.
