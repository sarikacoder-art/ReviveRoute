"""End-to-end API, persistence and workflow tests."""

from datetime import datetime, timezone
import sqlite3

from fastapi.testclient import TestClient

from app.main import create_app


def payload(event_id="evt_api_1"):
    return {
        "event_id": event_id,
        "customer_id": "cust_api_1",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "amount_inr": 4200.0,
        "payment_method": "upi",
        "failure_reason": "insufficient_funds",
        "customer_tenure_days": 240,
        "prior_successes": 8,
        "prior_failures": 2,
        "prior_recoveries": 1,
        "contacts_last_7_days": 0,
        "recent_method_failure_rate": 0.18,
        "degradation_flag": 0,
    }


def client(tmp_path):
    application = create_app(tmp_path / "test.db")
    return TestClient(application)


def test_health_and_empty_summary(tmp_path):
    with client(tmp_path) as api:
        assert api.get("/health").json()["status"] == "ok"
        summary = api.get("/api/v1/summary").json()
        assert summary["case_count"] == 0 and summary["expected_net_recovery_rate"] == 0


def test_create_get_list_and_summary(tmp_path):
    with client(tmp_path) as api:
        response = api.post("/api/v1/recovery-cases", json=payload())
        assert response.status_code == 201
        body = response.json()
        assert body["duplicate"] is False
        assert len(body["case"]["candidates"]) == 5
        assert len(body["case"]["events"]) == 1
        assert api.get("/api/v1/recovery-cases/evt_api_1").status_code == 200
        assert len(api.get("/api/v1/recovery-cases").json()["cases"]) == 1
        assert api.get("/api/v1/summary").json()["case_count"] == 1


def test_identical_event_replay_is_idempotent(tmp_path):
    request = payload()
    with client(tmp_path) as api:
        assert api.post("/api/v1/recovery-cases", json=request).json()["duplicate"] is False
        replay = api.post("/api/v1/recovery-cases", json=request)
        assert replay.status_code == 201 and replay.json()["duplicate"] is True
        assert api.get("/api/v1/summary").json()["case_count"] == 1


def test_changed_duplicate_event_is_rejected(tmp_path):
    request = payload()
    with client(tmp_path) as api:
        api.post("/api/v1/recovery-cases", json=request)
        request["amount_inr"] = 9999
        response = api.post("/api/v1/recovery-cases", json=request)
        assert response.status_code == 409


def test_invalid_payload_and_missing_case_are_rejected(tmp_path):
    request = payload()
    request["amount_inr"] = -1
    with client(tmp_path) as api:
        assert api.post("/api/v1/recovery-cases", json=request).status_code == 422
        assert api.get("/api/v1/recovery-cases/missing").status_code == 404


def test_valid_transition_is_persisted_and_audited(tmp_path):
    request = payload()
    request["failure_reason"] = "risk_declined"
    with client(tmp_path) as api:
        created = api.post("/api/v1/recovery-cases", json=request).json()["case"]
        assert created["workflow_status"] == "ESCALATED"
        changed = api.post(
            "/api/v1/recovery-cases/evt_api_1/transitions",
            json={"to_status": "UNDER_REVIEW", "reason": "assigned to risk analyst"},
        )
        assert changed.status_code == 200
        case = changed.json()
        assert case["workflow_status"] == "UNDER_REVIEW"
        assert len(case["events"]) == 2
        assert api.get("/api/v1/audit/verify").json() == {"valid": True, "entries_checked": 2, "failed_sequence": None}


def test_invalid_and_terminal_transitions_are_rejected(tmp_path):
    request = payload()
    request["opted_out"] = True
    with client(tmp_path) as api:
        created = api.post("/api/v1/recovery-cases", json=request).json()["case"]
        assert created["workflow_status"] == "STOPPED"
        response = api.post(
            "/api/v1/recovery-cases/evt_api_1/transitions",
            json={"to_status": "RECOVERED", "reason": "should not reopen terminal state"},
        )
        assert response.status_code == 409


def test_database_survives_application_restart(tmp_path):
    database = tmp_path / "persistent.db"
    with TestClient(create_app(database)) as api:
        api.post("/api/v1/recovery-cases", json=payload())
    with TestClient(create_app(database)) as restarted:
        assert restarted.get("/api/v1/recovery-cases/evt_api_1").status_code == 200
        assert restarted.get("/api/v1/audit/verify").json()["valid"] is True


def test_persistent_audit_verifier_detects_database_tampering(tmp_path):
    database = tmp_path / "tampered.db"
    with TestClient(create_app(database)) as api:
        api.post("/api/v1/recovery-cases", json=payload())
        assert api.get("/api/v1/audit/verify").json()["valid"] is True
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE workflow_events SET payload_json = ? WHERE sequence = 1", ('{"altered":true}',))
        connection.commit()
    with TestClient(create_app(database)) as api:
        verification = api.get("/api/v1/audit/verify").json()
        assert verification["valid"] is False
        assert verification["failed_sequence"] == 1
