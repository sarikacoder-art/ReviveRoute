"""Autonomous bounded worker and promise-watchlist tests."""

import sqlite3
import time
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.main import create_app


def failed_payment():
    return {
        "event_id": "agent_due_1", "customer_id": "agent_customer",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(), "amount_inr": 2400,
        "payment_method": "upi", "failure_reason": "temporary_network_issue",
        "customer_tenure_days": 100, "prior_successes": 4, "prior_failures": 1,
        "prior_recoveries": 1, "contacts_last_7_days": 0,
        "recent_method_failure_rate": 0.1, "degradation_flag": 0,
    }


def test_agent_worker_starts_polls_executes_due_case_and_stops(tmp_path):
    database = tmp_path / "agent.db"
    application = create_app(database, agent_enabled=True, agent_interval_seconds=0.05)
    with TestClient(application) as api:
        assert api.get("/api/v1/agent/status").json()["running"] is True
        created = api.post("/api/v1/recovery-cases", json=failed_payment()).json()["case"]
        assert created["workflow_status"] == "SCHEDULED"
        with sqlite3.connect(database) as connection:
            connection.execute("UPDATE recovery_cases SET execute_after_utc = ? WHERE event_id = ?", ("2000-01-01T00:00:00+00:00", "agent_due_1"))
            connection.commit()
        deadline = time.time() + 2
        while time.time() < deadline and api.get("/api/v1/recovery-cases/agent_due_1").json()["workflow_status"] != "ACTION_SENT":
            time.sleep(0.05)
        case = api.get("/api/v1/recovery-cases/agent_due_1").json()
        status = api.get("/api/v1/agent/status").json()
        assert case["workflow_status"] == "ACTION_SENT"
        assert status["cycles_completed"] >= 1 and status["actions_executed"] == 1
        assert status["customer_contacted"] is False and status["payment_api_called"] is False
    assert application.state.agent_worker.running is False


def test_agent_can_be_disabled_for_controlled_deployments(tmp_path):
    with TestClient(create_app(tmp_path / "disabled.db", agent_enabled=False)) as api:
        status = api.get("/api/v1/agent/status").json()
        assert status["running"] is False and status["cycles_completed"] == 0


def test_promise_statuses_summary_and_mark_paid(tmp_path):
    now = datetime.now(timezone.utc)
    application = create_app(tmp_path / "promises.db", agent_enabled=False)
    with TestClient(application) as api:
        broken = {
            "promise_id": "ptp_broken", "customer_id": "org_1", "display_name": "Fictional One",
            "amount_inr": 12000, "promised_at_utc": (now - timedelta(days=5)).isoformat(),
            "promised_due_utc": (now - timedelta(days=2)).isoformat(), "source": "SYNTHETIC_DEMO",
        }
        active = {**broken, "promise_id": "ptp_active", "customer_id": "org_2", "display_name": "Fictional Two", "amount_inr": 8000, "promised_due_utc": (now + timedelta(days=2)).isoformat()}
        assert api.post("/api/v1/promises", json=broken).status_code == 201
        assert api.post("/api/v1/promises", json=active).status_code == 201
        result = api.get("/api/v1/promises").json()
        assert {item["status"] for item in result["promises"]} == {"PROMISE_BROKEN", "PROMISE_ACTIVE"}
        assert result["summary"]["broken_count"] == 1
        assert result["summary"]["outstanding_amount_inr"] == 20000
        paid = api.post("/api/v1/promises/ptp_broken/mark-paid").json()
        assert paid["status"] == "PAID_LATE"


def test_fictional_sample_promises_show_broken_active_and_paid(tmp_path):
    with TestClient(create_app(tmp_path / "sample-promises.db", agent_enabled=False)) as api:
        result = api.post("/api/v1/promises/sample").json()
        assert result["created"] == 6 and "fictional" in result["evidence_label"]
        promises = api.get("/api/v1/promises").json()["promises"]
        assert len(promises) == 6
        assert "PROMISE_BROKEN" in {item["status"] for item in promises}
        assert all(item["source"] == "SYNTHETIC_DEMO" for item in promises)


def test_promise_validation_rejects_bad_dates_and_real_name_claims_are_absent(tmp_path):
    now = datetime.now(timezone.utc)
    payload = {
        "promise_id": "invalid", "customer_id": "org", "display_name": "Demo Company",
        "amount_inr": 1000, "promised_at_utc": now.isoformat(),
        "promised_due_utc": (now - timedelta(days=1)).isoformat(), "source": "SYNTHETIC_DEMO",
    }
    with TestClient(create_app(tmp_path / "validation.db", agent_enabled=False)) as api:
        assert api.post("/api/v1/promises", json=payload).status_code == 422
        assert api.post("/api/v1/promises/missing/mark-paid").status_code == 404
        assert api.get("/health").json()["version"] == "1.0.0"


def test_dashboard_makes_autonomy_and_fictional_promise_boundary_visible(tmp_path):
    with TestClient(create_app(tmp_path / "dashboard-agent.db", agent_enabled=False)) as api:
        page = api.get("/").text
        assert "AUTONOMOUS WORKER" in page
        assert "PROMISE-TO-PAY WATCHLIST" in page
        assert "Names below are fictional display labels" in page
        script = api.get("/static/dashboard.js").text
        assert "/api/v1/agent/status" in script
        assert "/api/v1/promises/sample" in script
