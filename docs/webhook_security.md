# Razorpay-Style Webhook Security — Milestone 5

## Implemented contract

1. Read the exact raw HTTP request bytes.
2. Calculate HMAC-SHA256 using the configured webhook secret.
3. Compare against `X-Razorpay-Signature` in constant time.
4. Require `X-Razorpay-Event-Id` and store its raw-body hash.
5. Return the previous result for an exact retry; reject the same delivery ID with different content.
6. Parse and map JSON only after signature verification succeeds.

This follows Razorpay's current guidance to verify the raw body and use the event-ID header for deduplication:

- https://razorpay.com/docs/us/webhooks/validate-test
- https://razorpay.com/docs/webhooks/best-practices/
- https://razorpay.com/docs/us/webhooks/payments

## Supported events

- `payment.failed`: normalizes paise to INR, payment method and a deterministic five-class failure taxonomy before running the bounded policy.
- `payment_link.paid`: attributes a full recovery using the unique execution `reference_id`, validates the amount, records the payment ID and stops the workflow as `RECOVERED`.
- Other correctly signed event types are acknowledged as ignored so Razorpay does not retry them unnecessarily.

## Safe execution boundary

The Milestone 5 executor is intentionally `SIMULATED`. It creates a deterministic reference and a non-routable `example.invalid` artifact. It sets both `customer_contacted` and `payment_api_called` to false. Only due `LINK_NOW`, `LINK_AFTER_2H` and `LINK_NEXT_MORNING` decisions can execute; human review and no-contact actions cannot.

## Evidence boundary

`observed_test_recovery` is separate from model-expected recovery. It only counts signed demo/test outcome events and must never be described as production revenue. Real Razorpay test-mode Payment Link creation comes next and will use credentials held only in environment variables.

## Known boundary

The initial feature adapter derives customer counts from ReviveRoute's own history. Method-level payment degradation requires merchant success-and-failure telemetry and therefore remains synthetic until that adapter is connected.
