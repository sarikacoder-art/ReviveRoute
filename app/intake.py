"""Bounded merchant intake helpers for CSV and sample batches."""

from __future__ import annotations

import csv
import io
import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import ValidationError

from app.schemas import FailedPaymentRequest

MAX_CSV_BYTES = 512 * 1024
MAX_CSV_ROWS = 100
REQUIRED_COLUMNS = (
    "event_id",
    "customer_id",
    "timestamp_utc",
    "amount_inr",
    "payment_method",
    "failure_reason",
)
OPTIONAL_COLUMNS = (
    "customer_tenure_days",
    "prior_successes",
    "prior_failures",
    "prior_recoveries",
    "contacts_last_7_days",
    "recent_method_failure_rate",
    "degradation_flag",
    "automated_attempts",
    "opted_out",
    "already_recovered",
)
CSV_COLUMNS = REQUIRED_COLUMNS + OPTIONAL_COLUMNS

DEFAULTS: dict[str, Any] = {
    "customer_tenure_days": 0,
    "prior_successes": 0,
    "prior_failures": 0,
    "prior_recoveries": 0,
    "contacts_last_7_days": 0,
    "recent_method_failure_rate": 0,
    "degradation_flag": 0,
    "automated_attempts": 0,
    "opted_out": False,
    "already_recovered": False,
}


class IntakeError(ValueError):
    """CSV intake is malformed or exceeds a safety bound."""


def csv_template() -> str:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=CSV_COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerow(
        {
            "event_id": "merchant_evt_001",
            "customer_id": "customer_001",
            "timestamp_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "amount_inr": "2499.00",
            "payment_method": "upi",
            "failure_reason": "temporary_network_issue",
            "customer_tenure_days": "180",
            "prior_successes": "8",
            "prior_failures": "1",
            "prior_recoveries": "1",
            "contacts_last_7_days": "0",
            "recent_method_failure_rate": "0.10",
            "degradation_flag": "0",
            "automated_attempts": "0",
            "opted_out": "false",
            "already_recovered": "false",
        }
    )
    return output.getvalue()


def _clean_row(row: dict[str, str | None]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, value in row.items():
        if key is None:
            continue
        normalized_key = key.strip().lstrip("\ufeff")
        normalized_value = value.strip() if isinstance(value, str) else value
        if normalized_key in CSV_COLUMNS and normalized_value not in (None, ""):
            cleaned[normalized_key] = normalized_value
    for key, value in DEFAULTS.items():
        cleaned.setdefault(key, value)
    return cleaned


def parse_csv_batch(raw_body: bytes) -> tuple[list[FailedPaymentRequest], list[dict[str, Any]]]:
    if len(raw_body) > MAX_CSV_BYTES:
        raise IntakeError(f"CSV exceeds the {MAX_CSV_BYTES // 1024} KB limit")
    try:
        text = raw_body.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise IntakeError("CSV must use UTF-8 encoding") from error
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise IntakeError("CSV header row is required")
    headers = {header.strip().lstrip("\ufeff") for header in reader.fieldnames if header}
    missing = [column for column in REQUIRED_COLUMNS if column not in headers]
    if missing:
        raise IntakeError(f"missing required columns: {', '.join(missing)}")

    requests: list[FailedPaymentRequest] = []
    errors: list[dict[str, Any]] = []
    for row_number, row in enumerate(reader, start=2):
        if row_number - 1 > MAX_CSV_ROWS:
            raise IntakeError(f"CSV exceeds the {MAX_CSV_ROWS}-row limit")
        if not any(value and value.strip() for value in row.values() if isinstance(value, str)):
            continue
        try:
            requests.append(FailedPaymentRequest.model_validate(_clean_row(row)))
        except ValidationError as error:
            messages = [f"{'.'.join(map(str, item['loc']))}: {item['msg']}" for item in error.errors()]
            errors.append({"row": row_number, "errors": messages})
    if not requests and not errors:
        raise IntakeError("CSV contains no data rows")
    return requests, errors


def sample_batch(count: int) -> list[FailedPaymentRequest]:
    token = uuid.uuid4().hex[:10]
    now = datetime.now(timezone.utc).replace(microsecond=0)
    methods = ("upi", "debit_card", "credit_card", "net_banking", "wallet")
    reasons = (
        "temporary_network_issue",
        "insufficient_funds",
        "bank_limit_exceeded",
        "risk_declined",
        "card_blocked",
    )
    amounts = (499.0, 1299.0, 2499.0, 7999.0, 14999.0, 29999.0)
    rows: list[FailedPaymentRequest] = []
    for index in range(count):
        rows.append(
            FailedPaymentRequest(
                event_id=f"sample_{token}_{index + 1:03d}",
                customer_id=f"sample_customer_{token}_{index % max(5, count // 3):03d}",
                timestamp_utc=now,
                amount_inr=amounts[index % len(amounts)],
                payment_method=methods[index % len(methods)],
                failure_reason=reasons[index % len(reasons)],
                customer_tenure_days=30 + (index * 17) % 720,
                prior_successes=index % 12,
                prior_failures=index % 4,
                prior_recoveries=index % 3,
                contacts_last_7_days=index % 4,
                recent_method_failure_rate=round((index % 6) / 10, 2),
                degradation_flag=1 if index % 13 == 0 else 0,
                automated_attempts=index % 3,
            )
        )
    return rows
