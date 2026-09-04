"""Judge-dashboard and complete signed-demo tests."""

from __future__ import annotations

import sqlite3

from fastapi.testclient import TestClient

from app.main import create_app


def test_dashboard_and_local_assets_are_served(tmp_path):
    with TestClient(create_app(tmp_path / "dashboard.db")) as api:
        page = api.get("/")
        assert page.status_code == 200
        assert "ReviveRoute" in page.text
        assert "Run end-to-end demo" in page.text
        assert "Simulation + Razorpay Test Mode" in page.text
        assert '/static/dashboard.css?v=1.3.0' in page.text
        assert '/static/dashboard.js?v=1.3.0' in page.text
        assert api.get("/dashboard").status_code == 200
        assert api.get("/static/dashboard.css").status_code == 200
        assert api.get("/static/dashboard.js").status_code == 200
        assert api.get("/static/favicon.svg").status_code == 200
        assert api.get("/health").json()["version"] == "1.3.0"


def test_one_click_demo_closes_the_loop_without_external_calls(tmp_path):
    with TestClient(create_app(tmp_path / "demo.db")) as api:
        response = api.post("/api/v1/demo/run")
        assert response.status_code == 200
        result = response.json()
        assert result["demo_mode"] == "SIGNED_SIMULATION"
        assert result["production_claim"] is False
        assert result["customer_contacted"] is False
        assert result["payment_api_called"] is False
        assert result["failure_signature_verified"] is True
        assert result["outcome_signature_verified"] is True
        assert result["case"]["workflow_status"] == "RECOVERED"
        assert [entry["stage"] for entry in result["timeline"]] == [
            "DETECTED", "DIAGNOSED", "DECIDED", "EXECUTED", "RECOVERED"
        ]
        assert result["outcome"]["amount_inr"] == 1800.0
        assert result["audit"]["valid"] is True
        assert result["summary"]["observed_test_recovery"]["recovered_amount_inr"] == 1800.0


def test_demo_executes_its_own_case_when_an_older_case_is_due(tmp_path):
    database = tmp_path / "isolated-demo.db"
    with TestClient(create_app(database)) as api:
        api.post(
            "/api/v1/recovery-cases",
            json={
                "event_id": "older_due_case",
                "customer_id": "customer_old",
                "timestamp_utc": "2026-01-01T00:00:00+00:00",
                "amount_inr": 3000,
                "payment_method": "upi",
                "failure_reason": "temporary_network_issue",
                "customer_tenure_days": 100,
                "prior_successes": 2,
                "prior_failures": 1,
                "prior_recoveries": 1,
                "contacts_last_7_days": 0,
                "recent_method_failure_rate": 0.1,
                "degradation_flag": 0,
            },
        )
        with sqlite3.connect(database) as connection:
            connection.execute(
                """UPDATE recovery_cases SET workflow_status='SCHEDULED', selected_action='LINK_NOW',
                   execute_after_utc='2000-01-01T00:00:00+00:00' WHERE event_id='older_due_case'"""
            )
            connection.commit()

        result = api.post("/api/v1/demo/run").json()
        assert result["execution"]["event_id"] == result["case"]["event_id"]
        assert api.get("/api/v1/recovery-cases/older_due_case").json()["workflow_status"] == "SCHEDULED"


def test_repeated_demo_runs_are_unique_and_accumulate_observed_results(tmp_path):
    with TestClient(create_app(tmp_path / "repeat.db")) as api:
        first = api.post("/api/v1/demo/run").json()
        second = api.post("/api/v1/demo/run").json()
        assert first["case"]["event_id"] != second["case"]["event_id"]
        summary = api.get("/api/v1/summary").json()
        assert summary["case_count"] == 2
        observed = summary["observed_test_recovery"]
        assert observed["evidence_label"] == "signed simulated/test webhook outcomes; not production revenue"
        assert observed["recovered_case_count"] == 2
        assert observed["recovered_amount_inr"] == 3600.0
        assert observed["executed_case_count"] == 2
        assert observed["observed_recovery_rate"] == 1.0
        assert observed["breakdown"]
        assert api.get("/api/v1/audit/verify").json()["valid"] is True
