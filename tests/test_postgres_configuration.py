"""Backend-selection tests for durable hosted storage."""

from datetime import datetime, timedelta, timezone

from app.database import RecoveryRepository
from app.decision_engine import CandidateScore, RecoveryDecision
from app.main import create_app


def test_postgres_urls_select_durable_backend():
    assert RecoveryRepository("postgresql://user:pass@db.example/app").is_postgres
    assert RecoveryRepository("postgres://user:pass@db.example/app").is_postgres
    assert not RecoveryRepository("data/reviveroute.db").is_postgres


def test_postgres_query_translation():
    sql = "INSERT OR IGNORE INTO executions (reference_id) VALUES (?)"
    translated = RecoveryRepository._postgres_sql(sql)
    assert translated == "INSERT INTO executions (reference_id) VALUES (%s) ON CONFLICT DO NOTHING"


def test_database_url_is_used_when_no_explicit_path(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@db.example/app")
    application = create_app(agent_enabled=False)
    assert application.state.repository.is_postgres


def add_due_case(repository, event_id):
    now = datetime.now(timezone.utc)
    request = {
        "event_id": event_id,
        "customer_id": "customer",
        "timestamp_utc": now.isoformat(),
        "amount_inr": 499.0,
        "payment_method": "upi",
        "failure_reason": "temporary_network_issue",
    }
    score = CandidateScore("LINK_NOW", 0.5, 249.5, 3, 0, 246.5, True)
    decision = RecoveryDecision(
        event_id,
        "LINK_NOW",
        "SCHEDULED",
        (now - timedelta(seconds=1)).isoformat(),
        (),
        "test",
        0.5,
        246.5,
        (score,),
    )
    repository.create_case(request, decision)


def test_execute_due_simulated_without_event_id_uses_only_now_and_limit(tmp_path):
    repository = RecoveryRepository(tmp_path / "due-all.db")
    repository.initialize()
    add_due_case(repository, "due_all")

    result = repository.execute_due_simulated(
        datetime.now(timezone.utc), 10, lambda event_id: f"ref_{event_id}"
    )

    assert [item["event_id"] for item in result] == ["due_all"]


def test_execute_due_simulated_with_event_id_filters_to_that_case(tmp_path):
    repository = RecoveryRepository(tmp_path / "due-one.db")
    repository.initialize()
    add_due_case(repository, "due_match")
    add_due_case(repository, "due_other")

    result = repository.execute_due_simulated(
        datetime.now(timezone.utc), 10, lambda event_id: f"ref_{event_id}", event_id="due_match"
    )

    assert [item["event_id"] for item in result] == ["due_match"]