"""Backend-selection tests for durable hosted storage."""

from app.database import RecoveryRepository
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