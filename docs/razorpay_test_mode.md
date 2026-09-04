# Razorpay Test Mode integration

ReviveRoute can create real Razorpay **test-mode** Payment Links from the autonomous worker. The integration rejects live key IDs and is limited to cases received through verified Razorpay webhooks. Manual, CSV and synthetic dashboard cases remain simulated.

## Render environment variables

Set these in the Render service under **Environment**:

```text
RAZORPAY_TEST_KEY_ID=rzp_test_...
RAZORPAY_TEST_KEY_SECRET=<private test secret>
RAZORPAY_TEST_MODE_ENABLED=true
RAZORPAY_WEBHOOK_SECRET=<private webhook secret>
REVIVEROUTE_AGENT_ENABLED=true
```

Never commit these values. After Render redeploys, `GET /api/v1/integrations/razorpay-test/status` must return `ready: true`, `mode: RAZORPAY_TEST`, and `scope: SIGNED_RAZORPAY_WEBHOOK_CASES_ONLY` without exposing either credential.

## Razorpay dashboard webhook

Create a Test Mode webhook pointing to:

```text
https://reviveroute-ai.onrender.com/webhooks/razorpay
```

Use the same secret as `RAZORPAY_WEBHOOK_SECRET` and enable `payment.failed` plus `payment_link.paid`.

## Safety boundary

- Only `rzp_test_` key IDs are accepted.
- Payment Link notifications and reminders are disabled.
- Public dashboard, CSV and seeded cases never call Razorpay.
- A provider failure moves the case to `FAILED` and creates an audit event.
- The created test checkout is stored against the exact recovery reference.
- A signed `payment_link.paid` webhook attributes the result and closes the case as `RECOVERED`.

