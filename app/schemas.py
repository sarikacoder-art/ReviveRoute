"""Validated HTTP request schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class FailedPaymentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(min_length=1, max_length=120)
    customer_id: str = Field(min_length=1, max_length=120)
    timestamp_utc: datetime
    amount_inr: float = Field(gt=0, le=10_000_000)
    payment_method: Literal["debit_card", "credit_card", "upi", "net_banking", "wallet"]
    failure_reason: Literal["insufficient_funds", "temporary_network_issue", "card_blocked", "risk_declined", "bank_limit_exceeded"]
    customer_tenure_days: float = Field(ge=0, le=50_000)
    prior_successes: int = Field(ge=0)
    prior_failures: int = Field(ge=0)
    prior_recoveries: int = Field(ge=0)
    contacts_last_7_days: int = Field(default=0, ge=0)
    recent_method_failure_rate: float = Field(ge=0, le=1)
    degradation_flag: Literal[0, 1] = 0
    automated_attempts: int = Field(default=0, ge=0)
    opted_out: bool = False
    already_recovered: bool = False

    @field_validator("timestamp_utc")
    @classmethod
    def timestamp_must_include_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp_utc must include a timezone")
        return value


class TransitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    to_status: Literal["SCHEDULED", "EXECUTING", "ACTION_SENT", "ESCALATED", "UNDER_REVIEW", "MONITORING", "RECOVERED", "STOPPED", "EXPIRED", "CANCELLED", "FAILED"]
    reason: str = Field(min_length=3, max_length=500)
    metadata: dict[str, Any] = Field(default_factory=dict)


class PromiseToPayRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    promise_id: str = Field(min_length=1, max_length=120)
    customer_id: str = Field(min_length=1, max_length=120)
    display_name: str = Field(min_length=1, max_length=120)
    amount_inr: float = Field(gt=0, le=10_000_000)
    promised_at_utc: datetime
    promised_due_utc: datetime
    source: Literal["MERCHANT_INPUT", "SYNTHETIC_DEMO"] = "MERCHANT_INPUT"

    @field_validator("promised_at_utc", "promised_due_utc")
    @classmethod
    def promise_timestamps_need_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("promise timestamps must include a timezone")
        return value

    @field_validator("promised_due_utc")
    @classmethod
    def due_must_follow_promise(cls, value: datetime, info) -> datetime:
        promised_at = info.data.get("promised_at_utc")
        if promised_at and value <= promised_at:
            raise ValueError("promised_due_utc must be after promised_at_utc")
        return value

