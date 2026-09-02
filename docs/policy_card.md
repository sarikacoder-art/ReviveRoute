# ReviveRoute Policy Card — Milestone 3

## Purpose

The policy converts calibrated action-outcome predictions into a bounded recovery decision for one failed payment. The model ranks possibilities; deterministic rules retain final authority.

## Expected-net-value objective

For each allowed action:

`expected net value = predicted recovery probability × failed amount − action cost − fatigue penalty`

The policy selects the highest allowed value. A minimum value floor prevents uneconomic intervention. This is a prioritisation heuristic, not a causal uplift estimate.

## Hard rules

| Condition | Outcome |
| --- | --- |
| Already recovered | Stop; no contact |
| Customer opted out | Stop; no contact |
| Recovery case older than 72 hours | Stop automation |
| Three automated attempts | Stop automation |
| Three contacts in seven days | Stop; suppress contact |
| Risk decline or blocked card | Human review |
| Amount at least ₹25,000 | Human review |
| Active payment degradation | Block immediate link |
| A proposed send falls within 21:00–07:59 merchant-local time | Block that immediate or two-hour link |

The prototype defaults to `Asia/Kolkata`; the engine accepts another IANA merchant timezone. Thresholds must become merchant-configurable after compliance review.

## Auditability

Each decision records every candidate probability, cost, penalty, eligibility result, chosen action, reason codes and explanation. Entries form a SHA-256 hash chain. Verification detects later modification or reordering. A hash chain is tamper-evident, not a substitute for authenticated immutable production storage.

## Limitations

- Model training, policy scoring and batch evidence use synthetic data.
- Expected recovery is not measured production revenue.
- Actual actions, Razorpay Payment Links, outcome webhooks and randomized evaluation arrive in later milestones.
- Real deployments need consent, channel-specific regulations and merchant-specific risk limits.
