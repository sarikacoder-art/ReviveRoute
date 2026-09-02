# ReviveRoute Workflow API — Milestone 4

## Boundary

This API accepts normalized failed-payment context. It does not yet claim to accept authentic Razorpay webhooks; signature verification and Razorpay payload mapping are deliberately reserved for Milestone 5.

## Intake guarantees

- Input types, ranges, enumerations and timezone awareness are validated.
- One `event_id` creates at most one recovery case.
- An identical replay is idempotent and returns the existing decision.
- Reusing an `event_id` with changed content returns HTTP 409.
- Every case persists all five candidate scores, eligibility results, reason codes and the selected action.

## State machine

| Current state | Allowed next states |
| --- | --- |
| `SCHEDULED` | `EXECUTING`, `RECOVERED`, `STOPPED`, `EXPIRED`, `CANCELLED` |
| `EXECUTING` | `ACTION_SENT`, `RECOVERED`, `STOPPED`, `FAILED` |
| `ACTION_SENT` | `RECOVERED`, `STOPPED`, `EXPIRED`, `FAILED` |
| `ESCALATED` | `UNDER_REVIEW`, `RECOVERED`, `STOPPED` |
| `UNDER_REVIEW` | `SCHEDULED`, `RECOVERED`, `STOPPED` |
| `MONITORING` | `SCHEDULED`, `RECOVERED`, `STOPPED`, `EXPIRED` |

`RECOVERED`, `STOPPED`, `EXPIRED`, `CANCELLED` and `FAILED` are terminal. Invalid transitions return HTTP 409 and do not alter state.

## Audit chain

Case creation and every valid transition add a persistent workflow event. Each event hash covers its timestamp, case ID, event type, old and new status, payload, and previous hash. `/api/v1/audit/verify` recalculates the complete chain and reports the first corrupted sequence.

## Evidence labels

The summary endpoint reports revenue at risk and model-estimated net recovery. These are synthetic conditional predictions—not observed payments or causal uplift. Later outcome webhooks will maintain separate observed-recovery metrics.
