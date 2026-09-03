# Merchant intake and public-demo boundary

ReviveRoute accepts failed payments through four intentionally distinct paths.

| Path | Intended use | Evidence status |
|---|---|---|
| Dashboard manual form | Try one fictional merchant case | Merchant-supplied input; model-estimated decision |
| Dashboard CSV import | Evaluate a fictional batch | Merchant-supplied input; model-estimated decisions |
| Sample batch button | Explore distributions quickly | Explicitly synthetic input; no recovery implied |
| `POST /webhooks/razorpay` | Production-shaped integration | HMAC-verified event; requires real deployment controls |

## CSV import

Download the canonical template from `GET /api/v1/intake/template.csv`. Required columns are:

`event_id, customer_id, timestamp_utc, amount_inr, payment_method, failure_reason`

Historical customer fields are optional and default to conservative zero values. The endpoint accepts UTF-8 CSV, at most 512 KB and at most 100 data rows. It validates every row, reports errors with source row numbers, treats exact event replays as duplicates and rejects reuse of an event ID with different data.

Each accepted row enters the normal decision engine. It receives all five candidate scores, deterministic stopping/escalation/timing rules, persistent workflow state and a hash-chained audit event.

## Public deployment warning

The hosted build is a disposable public sandbox. Users must enter fictional data only. Render's free local filesystem can reset on restart or spin-down, so it is not a system of record.

A production version must add merchant authentication, tenant-scoped authorization, rate limiting, durable managed storage, encryption and retention controls. Signed Razorpay webhooks—not anonymous dashboard forms—are the primary production intake path.
