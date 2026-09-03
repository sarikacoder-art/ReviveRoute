# Judge Demo Script

## 90-second primary walkthrough

### Opening â€” 10 seconds

â€œA failed payment is not automatically a retry problem. The correct response depends on why it failed, the customerâ€™s context, contact fatigue, timing and value. ReviveRoute closes that entire recovery loop while keeping deterministic safety rules in control.â€

### Show the dashboard â€” 10 seconds

Open `http://127.0.0.1:8000/`.

â€œThis dashboard deliberately separates revenue at risk, model-based expected recovery and signed simulated outcomes. We never present synthetic predictions as production uplift.â€

### Run the one-click demonstration â€” 35 seconds

Click **Run end-to-end demo**.

Narrate the five stages as they complete:

1. â€œA signed Razorpay-style `payment.failed` event puts â‚¹1,800 at risk.â€
2. â€œThe agent diagnoses a temporary network issue from the payment error fields.â€
3. â€œThe calibrated model scores all five interventions, then deterministic guardrails choose the safe action.â€
4. â€œThe executor creates a non-routable simulated artifactâ€”no customer contact and no payment API call.â€
5. â€œA second signed event is matched to the exact recovery reference, closing the case as recovered.â€

### Inspect the evidence â€” 20 seconds

Close the demo modal and open the new case.

â€œThe drawer exposes the chosen action, probability, expected net value, every rejected candidate, reason codes and the full state-transition history. This is explainable at the individual-case level.â€

Click **Verify audit chain**.

â€œEvery workflow event participates in a persistent SHA-256 hash chain, so modification or reordering is detectable.â€

### Close â€” 15 seconds

â€œReviveRoute is narrow by design: one-time failed-payment recovery, implemented deeply from signed detection to measured outcome. It combines ML selection with hard safety boundaries, and it is ready to replace the simulator with Razorpay test-mode execution behind an explicit switch.â€

## If the live demo fails

1. Keep the server terminal visible and read the error.
2. Open `http://127.0.0.1:8000/health`; confirm version `0.6.0`.
3. Refresh the dashboard once.
4. If necessary, show the API at `/docs`, the existing case records and `models/policy_demo.json`.
5. Do not claim that a failed local demonstration represents a recovered production payment.

## Pre-demo checklist

- Run `python -m pytest -q` and confirm **81 passed**.
- Start with `python -m uvicorn app.main:app --reload`.
- Confirm `/health` reports version `0.6.0`.
- Confirm the dashboard loads without internet access.
- Set browser zoom to 90â€“100% and close unrelated tabs.
- Keep `/docs` open in a second tab.
