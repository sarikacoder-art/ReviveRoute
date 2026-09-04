"""Public dashboard auto-seeding tests."""

from fastapi.testclient import TestClient

from app.main import create_app


def test_empty_public_demo_is_populated_with_explicit_evidence(tmp_path):
    application = create_app(tmp_path / "seeded.db", agent_enabled=False, auto_seed=True)
    with TestClient(application) as api:
        summary = api.get("/api/v1/summary").json()
        promises = api.get("/api/v1/promises").json()
        seed = api.get("/api/v1/demo/seed-status").json()
        assert summary["case_count"] == 41
        assert summary["observed_test_recovery"]["recovered_case_count"] >= 7
        assert summary["observed_test_recovery"]["recovered_amount_inr"] > 1800
        assert promises["summary"]["promise_count"] == 6
        assert seed == {
            "mode": "AUTO_SEEDED_FICTIONAL_DEMO", "cases_seeded": 40,
            "signed_recoveries_seeded": summary["observed_test_recovery"]["recovered_case_count"],
            "recovery_examples": seed["recovery_examples"],
            "promises_seeded": 6, "production_claim": False,
        }
        examples = seed["recovery_examples"]
        assert {item["selected_action"] for item in examples} == {"LINK_NOW", "LINK_AFTER_2H", "LINK_NEXT_MORNING"}
        assert len({item["failure_reason"] for item in examples}) >= 3


def test_restart_does_not_seed_an_existing_database_twice(tmp_path):
    database = tmp_path / "restart.db"
    with TestClient(create_app(database, agent_enabled=False, auto_seed=True)) as api:
        assert api.get("/api/v1/summary").json()["case_count"] == 41
    with TestClient(create_app(database, agent_enabled=False, auto_seed=True)) as api:
        assert api.get("/api/v1/summary").json()["case_count"] == 41
        assert api.get("/api/v1/promises").json()["summary"]["promise_count"] == 6
        seed = api.get("/api/v1/demo/seed-status").json()
        assert seed["cases_seeded"] == 0 and seed["promises_seeded"] == 0


def test_auto_seed_can_be_disabled(tmp_path):
    with TestClient(create_app(tmp_path / "empty.db", agent_enabled=False, auto_seed=False)) as api:
        assert api.get("/api/v1/summary").json()["case_count"] == 0
        assert api.get("/api/v1/promises").json()["summary"]["promise_count"] == 0
        assert api.get("/api/v1/demo/seed-status").json()["mode"] == "DISABLED"


def test_older_fictional_demo_is_upgraded_once(tmp_path):
    database = tmp_path / "older-demo.db"
    with TestClient(create_app(database, agent_enabled=False, auto_seed=False)) as api:
        assert api.post("/api/v1/intake/sample-batch?count=25").json()["created"] == 25
        assert api.post("/api/v1/demo/run").status_code == 200
        assert api.get("/api/v1/summary").json()["case_count"] == 26
    with TestClient(create_app(database, agent_enabled=False, auto_seed=True)) as api:
        summary = api.get("/api/v1/summary").json()
        seed = api.get("/api/v1/demo/seed-status").json()
        assert summary["case_count"] == 66
        assert summary["observed_test_recovery"]["recovered_case_count"] >= 7
        assert seed["mode"] == "AUTO_UPGRADED_FICTIONAL_DEMO"
        assert seed["cases_seeded"] == 40
    with TestClient(create_app(database, agent_enabled=False, auto_seed=True)) as api:
        assert api.get("/api/v1/summary").json()["case_count"] == 66
        assert api.get("/api/v1/demo/seed-status").json()["cases_seeded"] == 0
