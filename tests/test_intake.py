"""Merchant intake, batch bounds and sample-data tests."""

from fastapi.testclient import TestClient

from app.intake import MAX_CSV_BYTES, MAX_CSV_ROWS
from app.main import create_app


def client(tmp_path):
    return TestClient(create_app(tmp_path / "intake.db"))


def test_downloadable_template_has_required_columns_and_example(tmp_path):
    with client(tmp_path) as api:
        response = api.get("/api/v1/intake/template.csv")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/csv")
        assert "reviveroute-import-template.csv" in response.headers["content-disposition"]
        header, example = response.text.splitlines()[:2]
        assert header.startswith("event_id,customer_id,timestamp_utc,amount_inr,payment_method,failure_reason")
        assert "merchant_evt_001" in example


def test_csv_batch_creates_valid_rows_and_reports_invalid_rows(tmp_path):
    body = """event_id,customer_id,timestamp_utc,amount_inr,payment_method,failure_reason
csv_1,cust_1,2026-09-03T10:00:00+00:00,2400,upi,temporary_network_issue
csv_bad,cust_2,2026-09-03T10:00:00+00:00,-1,upi,temporary_network_issue
csv_2,cust_3,2026-09-03T10:00:00+00:00,5100,credit_card,insufficient_funds
"""
    with client(tmp_path) as api:
        result = api.post("/api/v1/intake/csv", content=body, headers={"content-type": "text/csv"})
        assert result.status_code == 200
        payload = result.json()
        assert payload["rows_received"] == 3
        assert payload["created"] == 2
        assert payload["duplicates"] == 0
        assert payload["validation_errors"][0]["row"] == 3
        assert api.get("/api/v1/summary").json()["case_count"] == 2
        assert api.get("/api/v1/audit/verify").json()["valid"] is True


def test_csv_batch_replay_is_idempotent(tmp_path):
    body = """event_id,customer_id,timestamp_utc,amount_inr,payment_method,failure_reason
csv_replay,cust_1,2026-09-03T10:00:00+00:00,2400,upi,temporary_network_issue
"""
    with client(tmp_path) as api:
        first = api.post("/api/v1/intake/csv", content=body).json()
        second = api.post("/api/v1/intake/csv", content=body).json()
        assert first["created"] == 1
        assert second["created"] == 0 and second["duplicates"] == 1
        assert api.get("/api/v1/summary").json()["case_count"] == 1


def test_csv_missing_columns_empty_and_oversized_are_rejected(tmp_path):
    with client(tmp_path) as api:
        missing = api.post("/api/v1/intake/csv", content="event_id,amount_inr\na,20\n")
        assert missing.status_code == 422 and "missing required columns" in missing.json()["detail"]
        empty = api.post(
            "/api/v1/intake/csv",
            content="event_id,customer_id,timestamp_utc,amount_inr,payment_method,failure_reason\n",
        )
        assert empty.status_code == 422 and "no data rows" in empty.json()["detail"]
        oversized = api.post("/api/v1/intake/csv", content=b"x" * (MAX_CSV_BYTES + 1))
        assert oversized.status_code == 422 and "512 KB" in oversized.json()["detail"]


def test_csv_row_limit_is_enforced(tmp_path):
    header = "event_id,customer_id,timestamp_utc,amount_inr,payment_method,failure_reason\n"
    rows = "".join(
        f"row_{index},cust,2026-09-03T10:00:00+00:00,1000,upi,temporary_network_issue\n"
        for index in range(MAX_CSV_ROWS + 1)
    )
    with client(tmp_path) as api:
        response = api.post("/api/v1/intake/csv", content=header + rows)
        assert response.status_code == 422 and "100-row limit" in response.json()["detail"]
        assert api.get("/api/v1/summary").json()["case_count"] == 0


def test_sample_batch_is_bounded_unique_and_explicitly_synthetic(tmp_path):
    with client(tmp_path) as api:
        assert api.post("/api/v1/intake/sample-batch?count=4").status_code == 422
        result = api.post("/api/v1/intake/sample-batch?count=25")
        assert result.status_code == 200
        payload = result.json()
        assert payload["created"] == 25
        assert len(set(payload["event_ids"])) == 25
        assert "synthetic" in payload["evidence_label"]
        assert payload["summary"]["case_count"] == 25
        assert payload["summary"]["observed_test_recovery"]["recovered_amount_inr"] == 0


def test_dashboard_exposes_all_three_intake_paths_and_version(tmp_path):
    with client(tmp_path) as api:
        page = api.get("/").text
        assert "Enter one failure" in page
        assert "Import a CSV batch" in page
        assert "Load sample batch" in page
        assert "Use fictional data only" in page
        assert api.get("/health").json()["version"] == "0.7.0"
