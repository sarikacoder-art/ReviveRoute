"""Security, mapping, replay, execution and outcome-loop tests."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.main import create_app
from app.webhooks import failed_payment_to_case, normalize_failure_reason, webhook_signature

SECRET = "local-test-secret-with-sufficient-length"


def failed_event(amount_paise: int = 420_000, reason: str = "insufficient_funds") -> dict:
    return {
        "event": "payment.failed",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_failed_demo",
                    "amount": amount_paise,
                    "currency": "INR",
                    "status": "failed",
                    "method": "upi",
                    "customer_id": "cust_webhook_demo",
                    "created_at": int(datetime.now(timezone.utc).timestamp()),
                    "error_code": "BAD_REQUEST_ERROR",
                    "error_source": "customer",
                    "error_step": "payment_authorization",
                    "error_reason": reason,
                    "error_description": "Payment could not be completed",
                }
            }
        },
    }


def paid_event(reference_id: str, amount_paise: int = 420_000) -> dict:
    return {
        "event": "payment_link.paid",
        "payload": {
            "payment": {"entity": {"id": "pay_recovered_demo", "amount": amount_paise, "currency": "INR"}},
            "payment_link": {"entity": {"id": "plink_demo", "reference_id": reference_id, "status": "paid"}},
        },
    }


def signed_post(client: TestClient, event: dict, delivery_id: str, secret: str = SECRET):
    body = json.dumps(event, separators=(",", ":")).encode()
    return client.post(
        "/webhooks/razorpay",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Razorpay-Event-Id": delivery_id,
            "X-Razorpay-Signature": webhook_signature(body, secret),
        },
    )


def direct_case(event_id: str = "evt_executor") -> dict:
    return {
        "event_id": event_id,
        "customer_id": "cust_executor",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "amount_inr": 4200.0,
        "payment_method": "upi",
        "failure_reason": "temporary_network_issue",
        "customer_tenure_days": 100,
        "prior_successes": 3,
        "prior_failures": 1,
        "prior_recoveries": 1,
        "contacts_last_7_days": 0,
        "recent_method_failure_rate": 0.1,
        "degradation_flag": 0,
    }


def test_signature_is_checked_against_exact_raw_body(tmp_path):
    event = failed_event()
    body = json.dumps(event, separators=(",", ":")).encode()
    headers = {"X-Razorpay-Event-Id": "delivery_exact", "X-Razorpay-Signature": webhook_signature(body, SECRET)}
    with TestClient(create_app(tmp_path / "exact.db", webhook_secret=SECRET)) as api:
        altered = body + b" "
        assert api.post("/webhooks/razorpay", content=altered, headers=headers).status_code == 401
        assert api.post("/webhooks/razorpay", content=body, headers=headers).status_code == 200


def test_missing_secret_signature_and_delivery_id_fail_closed(tmp_path):
    event = failed_event()
    body = json.dumps(event).encode()
    with TestClient(create_app(tmp_path / "no-secret.db", webhook_secret="")) as api:
        assert api.post("/webhooks/razorpay", content=body).status_code == 503
    with TestClient(create_app(tmp_path / "secure.db", webhook_secret=SECRET)) as api:
        assert api.post("/webhooks/razorpay", content=body, headers={"X-Razorpay-Signature": "wrong"}).status_code == 401
        signature = webhook_signature(body, SECRET)
        assert api.post("/webhooks/razorpay", content=body, headers={"X-Razorpay-Signature": signature}).status_code == 400


def test_failed_webhook_creates_one_case_and_exact_replay_is_idempotent(tmp_path):
    event = failed_event()
    with TestClient(create_app(tmp_path / "replay.db", webhook_secret=SECRET)) as api:
        first = signed_post(api, event, "delivery_replay")
        assert first.status_code == 200
        assert first.json()["case"]["amount_inr"] == 4200.0
        assert first.json()["case"]["source_payment_id"] == "pay_failed_demo"
        replay = signed_post(api, event, "delivery_replay")
        assert replay.status_code == 200 and replay.json()["duplicate"] is True
        assert api.get("/api/v1/summary").json()["case_count"] == 1


def test_reused_delivery_id_with_changed_signed_body_is_conflict(tmp_path):
    with TestClient(create_app(tmp_path / "conflict.db", webhook_secret=SECRET)) as api:
        assert signed_post(api, failed_event(), "delivery_conflict").status_code == 200
        assert signed_post(api, failed_event(500_000), "delivery_conflict").status_code == 409


def test_unknown_signed_event_is_accepted_and_ignored(tmp_path):
    with TestClient(create_app(tmp_path / "ignored.db", webhook_secret=SECRET)) as api:
        response = signed_post(api, {"event": "payment.authorized", "payload": {}}, "delivery_ignored")
        assert response.status_code == 200
        assert response.json()["status"] == "ignored"


def test_deterministic_failure_taxonomy():
    assert normalize_failure_reason({"error_reason": "insufficient_funds"}) == "insufficient_funds"
    assert normalize_failure_reason({"error_description": "Bank limit exceeded"}) == "bank_limit_exceeded"
    assert normalize_failure_reason({"error_reason": "payment_risk_check_failed"}) == "risk_declined"
    assert normalize_failure_reason({"error_reason": "card_declined"}) == "card_blocked"
    assert normalize_failure_reason({"error_code": "GATEWAY_ERROR"}) == "temporary_network_issue"


def test_mapper_converts_paise_time_method_and_history():
    event = failed_event()
    case = failed_payment_to_case(event, "delivery_map", {"prior_failures": 7, "contacts_last_7_days": 2})
    assert case.amount_inr == 4200.0
    assert case.payment_method == "upi"
    assert case.timestamp_utc.tzinfo is not None
    assert case.prior_failures == 7 and case.contacts_last_7_days == 2


def test_simulated_executor_never_contacts_customer_or_payment_api(tmp_path):
    database = tmp_path / "executor.db"
    with TestClient(create_app(database, webhook_secret=SECRET)) as api:
        api.post("/api/v1/recovery-cases", json=direct_case())
        with sqlite3.connect(database) as connection:
            connection.execute("UPDATE recovery_cases SET workflow_status='SCHEDULED', selected_action='LINK_NOW', execute_after_utc='2000-01-01T00:00:00+00:00'")
            connection.commit()
        response = api.post("/api/v1/executor/run-due").json()
        assert response["execution_mode"] == "SIMULATED"
        assert response["customer_contacted"] is False and response["payment_api_called"] is False
        assert len(response["executions"]) == 1
        execution = response["executions"][0]
        assert execution["artifact_url"].startswith("https://example.invalid/")
        assert api.post("/api/v1/executor/run-due").json()["executions"] == []


def test_executor_will_not_execute_human_review_as_contact_action(tmp_path):
    database = tmp_path / "review.db"
    with TestClient(create_app(database, webhook_secret=SECRET)) as api:
        api.post("/api/v1/recovery-cases", json=direct_case())
        with sqlite3.connect(database) as connection:
            connection.execute("UPDATE recovery_cases SET workflow_status='SCHEDULED', selected_action='HUMAN_REVIEW', execute_after_utc='2000-01-01T00:00:00+00:00'")
            connection.commit()
        assert api.post("/api/v1/executor/run-due").json()["executions"] == []


def test_signed_paid_event_closes_loop_and_separates_observed_metrics(tmp_path):
    database = tmp_path / "outcome.db"
    with TestClient(create_app(database, webhook_secret=SECRET)) as api:
        api.post("/api/v1/recovery-cases", json=direct_case())
        with sqlite3.connect(database) as connection:
            connection.execute("UPDATE recovery_cases SET workflow_status='SCHEDULED', selected_action='LINK_NOW', execute_after_utc='2000-01-01T00:00:00+00:00'")
            connection.commit()
        reference = api.post("/api/v1/executor/run-due").json()["executions"][0]["reference_id"]
        paid = signed_post(api, paid_event(reference), "delivery_paid")
        assert paid.status_code == 200
        case = api.get("/api/v1/recovery-cases/evt_executor").json()
        assert case["workflow_status"] == "RECOVERED"
        summary = api.get("/api/v1/summary").json()
        assert summary["observed_test_recovery"]["recovered_case_count"] == 1
        assert summary["observed_test_recovery"]["recovered_amount_inr"] == 4200.0
        assert summary["evidence_label"].startswith("model-based")
        assert api.get("/api/v1/audit/verify").json()["valid"] is True


def test_paid_event_rejects_unknown_reference_and_amount_mismatch(tmp_path):
    database = tmp_path / "bad-outcome.db"
    with TestClient(create_app(database, webhook_secret=SECRET)) as api:
        assert signed_post(api, paid_event("unknown"), "delivery_unknown").status_code == 409
        api.post("/api/v1/recovery-cases", json=direct_case())
        with sqlite3.connect(database) as connection:
            connection.execute("UPDATE recovery_cases SET workflow_status='SCHEDULED', selected_action='LINK_NOW', execute_after_utc='2000-01-01T00:00:00+00:00'")
            connection.commit()
        reference = api.post("/api/v1/executor/run-due").json()["executions"][0]["reference_id"]
        assert signed_post(api, paid_event(reference, 100), "delivery_wrong_amount").status_code == 409
