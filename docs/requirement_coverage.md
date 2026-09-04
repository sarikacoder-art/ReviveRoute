# Official Track Requirement Coverage

## Scope decision

The official directions—including checkout abandonment, failed subscriptions, receivables, mandate retries, Hinglish voice and promise-to-pay—are examples, not a requirement to combine every recovery problem. ReviveRoute deliberately solves one loop deeply: **recovery of one-time failed Razorpay payments**.

| Mandatory requirement | Working ReviveRoute evidence | Judge demonstration |
|---|---|---|
| Detect revenue at risk | HMAC-verified `payment.failed` webhooks, manual merchant intake and bounded CSV batches create idempotent recovery cases. | Enter one failure or load the 25-case sample batch, then show revenue at risk. |
| Diagnose the cause | Deterministic taxonomy maps Razorpay error fields into five actionable failure reasons; customer history and payment context are attached. | The demo identifies `temporary_network_issue` from gateway fields. |
| Determine the right intervention | A calibrated classifier estimates recovery probability for all five actions; expected net value ranks allowed actions. | Open the case drawer and compare every candidate action and score. |
| Execute a bounded workflow | Deterministic rules can block, delay, stop or escalate a model recommendation before execution. | Show the selected action, reason codes and scheduled workflow status. |
| Observe the result | A signed `payment_link.paid` event must match the unique recovery reference and amount. | The demo attributes the signed ₹1,800 outcome to the exact case. |
| Measure money across a batch | CSV/sample batch intake plus the summary endpoint separate revenue at risk, model-based expected recovery and signed simulated/test observed recovery. | Load 25 cases and point to the three separate evidence-labelled metrics. |
| Compliant escalation | Sensitive `risk_declined` cases and high-value cases route to human review. | Explain the escalation rules from the candidate table/policy card. |
| Stopping rules | Opt-out, already recovered, expiry, retry exhaustion and contact fatigue terminate automation. | Show blocked candidates or a stopped case in the case explorer. |
| Complete audit trail | Every decision and transition is stored in an append-only SHA-256 hash chain with a verifier. | Click **Verify audit chain** and open a case timeline. |

## Evidence boundary

- The dataset is synthetic and exists for development and demonstration.
- Model outputs are predictive estimates, not causal uplift.
- The displayed ₹1,800 recovery is produced by signed local simulation, not production revenue.
- Public, CSV and synthetic cases create only `example.invalid` artifacts. With explicit test credentials, verified Razorpay webhook cases may create Razorpay Test Mode Payment Links; notifications remain disabled.
- The hosted dashboard is a disposable public sandbox; only fictional data should be entered.
- Production uplift requires randomized action assignment and real Razorpay webhook outcomes.
