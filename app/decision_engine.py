"""Bounded next-best-action policy for failed-payment recovery."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import joblib
import pandas as pd

from app.audit import AuditTrail
from ml.features import ACTIONS
from ml.train_action_model import score_candidates

MODEL_PATH = Path(__file__).resolve().parents[1] / "models" / "action_model.joblib"

ACTION_COST_INR = {
    "NO_CONTACT": 0.0,
    "LINK_NOW": 3.0,
    "LINK_AFTER_2H": 3.0,
    "LINK_NEXT_MORNING": 3.0,
    "HUMAN_REVIEW": 120.0,
}
CONTACT_ACTIONS = {"LINK_NOW", "LINK_AFTER_2H", "LINK_NEXT_MORNING"}
MAX_CONTACTS_7D = 3
MAX_AUTOMATED_ATTEMPTS = 3
HIGH_VALUE_THRESHOLD_INR = 25_000.0
MIN_EXPECTED_NET_VALUE_INR = 25.0
RECOVERY_WINDOW_HOURS = 72
QUIET_HOUR_START = 21
QUIET_HOUR_END = 8
DEFAULT_MERCHANT_TIMEZONE = "Asia/Kolkata"
MODEL_REFERENCE_DATE = datetime(2026, 3, 1, tzinfo=timezone.utc)


@dataclass(frozen=True)
class RecoveryCase:
    event_id: str
    customer_id: str
    timestamp_utc: datetime
    amount_inr: float
    payment_method: str
    failure_reason: str
    customer_tenure_days: float
    prior_successes: int
    prior_failures: int
    prior_recoveries: int
    contacts_last_7_days: int
    recent_method_failure_rate: float
    degradation_flag: int
    automated_attempts: int = 0
    opted_out: bool = False
    already_recovered: bool = False
    case_created_at_utc: datetime | None = None

    def __post_init__(self) -> None:
        if self.amount_inr <= 0:
            raise ValueError("amount_inr must be positive")
        if self.contacts_last_7_days < 0 or self.automated_attempts < 0:
            raise ValueError("contact and attempt counts cannot be negative")
        for name in ("timestamp_utc", "case_created_at_utc"):
            value = getattr(self, name)
            if value is not None and value.tzinfo is None:
                raise ValueError(f"{name} must be timezone-aware")

    @classmethod
    def from_series(cls, row: pd.Series, **overrides: Any) -> "RecoveryCase":
        timestamp = pd.to_datetime(row["timestamp_utc"], utc=True).to_pydatetime()
        values = {
            "event_id": str(row["event_id"]),
            "customer_id": str(row["customer_id"]),
            "timestamp_utc": timestamp,
            "case_created_at_utc": timestamp,
            "amount_inr": float(row["amount_inr"]),
            "payment_method": str(row["payment_method"]),
            "failure_reason": str(row["failure_reason"]),
            "customer_tenure_days": float(row["customer_tenure_days"]),
            "prior_successes": int(row["prior_successes"]),
            "prior_failures": int(row["prior_failures"]),
            "prior_recoveries": int(row["prior_recoveries"]),
            "contacts_last_7_days": int(row["contacts_last_7_days"]),
            "recent_method_failure_rate": float(row["recent_method_failure_rate"]),
            "degradation_flag": int(row["degradation_flag"]),
        }
        values.update(overrides)
        return cls(**values)

    def model_row(self) -> pd.Series:
        timestamp = self.timestamp_utc.astimezone(timezone.utc)
        return pd.Series({
            "event_id": self.event_id,
            "customer_id": self.customer_id,
            "timestamp_utc": timestamp,
            "amount_inr": self.amount_inr,
            "payment_method": self.payment_method,
            "failure_reason": self.failure_reason,
            "hour": timestamp.hour,
            "weekday": timestamp.weekday(),
            "customer_tenure_days": self.customer_tenure_days,
            "prior_successes": self.prior_successes,
            "prior_failures": self.prior_failures,
            "prior_recoveries": self.prior_recoveries,
            "contacts_last_7_days": self.contacts_last_7_days,
            "recent_method_failure_rate": self.recent_method_failure_rate,
            "degradation_flag": self.degradation_flag,
            "historical_action": "NO_CONTACT",
            "action_delay_minutes": 0,
            "event_day_index": (timestamp - MODEL_REFERENCE_DATE).total_seconds() / 86_400,
        })


@dataclass(frozen=True)
class CandidateScore:
    action: str
    recovery_probability: float
    expected_recovered_amount: float
    action_cost: float
    fatigue_penalty: float
    expected_net_value: float
    allowed: bool
    blocked_reason: str | None = None


@dataclass(frozen=True)
class RecoveryDecision:
    event_id: str
    selected_action: str
    workflow_status: str
    execute_after_utc: str | None
    reason_codes: tuple[str, ...]
    explanation: str
    selected_probability: float
    expected_net_value: float
    candidates: tuple[CandidateScore, ...] = field(default_factory=tuple)

    def audit_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["candidates"] = [asdict(candidate) for candidate in self.candidates]
        return payload


class DecisionEngine:
    def __init__(
        self,
        model_bundle: dict | None = None,
        audit_trail: AuditTrail | None = None,
        merchant_timezone: str = DEFAULT_MERCHANT_TIMEZONE,
    ) -> None:
        self.bundle = model_bundle if model_bundle is not None else joblib.load(MODEL_PATH)
        self.audit = audit_trail if audit_trail is not None else AuditTrail()
        self.merchant_timezone = ZoneInfo(merchant_timezone)

    def _execute_after(self, action: str, timestamp: datetime) -> str | None:
        timestamp = timestamp.astimezone(timezone.utc)
        if action in {"NO_CONTACT", "HUMAN_REVIEW"}:
            return None
        if action == "LINK_NOW":
            scheduled = timestamp + timedelta(minutes=10)
        elif action == "LINK_AFTER_2H":
            scheduled = timestamp + timedelta(hours=2)
        else:
            local = timestamp.astimezone(self.merchant_timezone)
            next_morning = local.replace(hour=8, minute=0, second=0, microsecond=0)
            if local >= next_morning:
                next_morning += timedelta(days=1)
            scheduled = next_morning.astimezone(timezone.utc)
        return scheduled.astimezone(timezone.utc).isoformat()

    def _is_quiet(self, timestamp: datetime) -> bool:
        local_hour = timestamp.astimezone(self.merchant_timezone).hour
        return local_hour >= QUIET_HOUR_START or local_hour < QUIET_HOUR_END

    @staticmethod
    def _hard_override(case: RecoveryCase, now: datetime) -> tuple[str, str, tuple[str, ...], str] | None:
        if case.already_recovered:
            return "NO_CONTACT", "STOPPED", ("ALREADY_RECOVERED",), "Payment is already recovered; all recovery activity stops."
        if case.opted_out:
            return "NO_CONTACT", "STOPPED", ("CUSTOMER_OPTED_OUT",), "Customer opted out; no recovery contact is permitted."
        created = case.case_created_at_utc or case.timestamp_utc
        if now - created > timedelta(hours=RECOVERY_WINDOW_HOURS):
            return "NO_CONTACT", "STOPPED", ("RECOVERY_WINDOW_EXPIRED",), "The 72-hour recovery window expired; automation stops."
        if case.automated_attempts >= MAX_AUTOMATED_ATTEMPTS:
            return "NO_CONTACT", "STOPPED", ("MAX_ATTEMPTS_REACHED",), "Maximum automated attempts reached; automation stops."
        if case.contacts_last_7_days >= MAX_CONTACTS_7D:
            return "NO_CONTACT", "STOPPED", ("CONTACT_FATIGUE_LIMIT",), "Seven-day contact limit reached; further contact is suppressed."
        if case.failure_reason in {"risk_declined", "card_blocked"}:
            return "HUMAN_REVIEW", "ESCALATED", ("SENSITIVE_FAILURE",), "Sensitive failure type requires human review instead of an automated payment link."
        if case.amount_inr >= HIGH_VALUE_THRESHOLD_INR:
            return "HUMAN_REVIEW", "ESCALATED", ("HIGH_VALUE_CASE",), "High-value exposure requires human approval before recovery action."
        return None

    def decide(self, case: RecoveryCase, now: datetime | None = None) -> RecoveryDecision:
        now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        override = self._hard_override(case, now)
        raw_scores = score_candidates(self.bundle, case.model_row()).set_index("action")

        candidates: list[CandidateScore] = []
        for action in ACTIONS:
            probability = float(raw_scores.loc[action, "recovery_probability"])
            expected_recovery = probability * case.amount_inr
            fatigue_penalty = case.contacts_last_7_days * 12.0 if action in CONTACT_ACTIONS else 0.0
            allowed = True
            blocked_reason = None
            if case.degradation_flag and action == "LINK_NOW":
                allowed, blocked_reason = False, "ACTIVE_PAYMENT_DEGRADATION"
            scheduled_text = self._execute_after(action, case.timestamp_utc)
            scheduled = datetime.fromisoformat(scheduled_text) if scheduled_text else case.timestamp_utc
            if action in {"LINK_NOW", "LINK_AFTER_2H"} and self._is_quiet(scheduled):
                allowed, blocked_reason = False, "QUIET_HOURS"
            if action == "HUMAN_REVIEW" and case.amount_inr < 2_000 and case.failure_reason not in {"risk_declined", "card_blocked"}:
                allowed, blocked_reason = False, "REVIEW_NOT_JUSTIFIED"
            net_value = expected_recovery - ACTION_COST_INR[action] - fatigue_penalty
            candidates.append(CandidateScore(action, probability, expected_recovery, ACTION_COST_INR[action], fatigue_penalty, net_value, allowed, blocked_reason))

        if override:
            action, status, codes, explanation = override
        else:
            eligible = [candidate for candidate in candidates if candidate.allowed]
            selected = max(eligible, key=lambda candidate: candidate.expected_net_value)
            if selected.expected_net_value < MIN_EXPECTED_NET_VALUE_INR:
                action, status = "NO_CONTACT", "STOPPED"
                codes = ("EXPECTED_VALUE_BELOW_FLOOR",)
                explanation = "No intervention clears the minimum expected-net-value floor."
            else:
                action, status = selected.action, "SCHEDULED" if selected.action in CONTACT_ACTIONS else "ESCALATED" if selected.action == "HUMAN_REVIEW" else "MONITORING"
                codes_list = ["MAX_EXPECTED_NET_VALUE"]
                if case.degradation_flag:
                    codes_list.append("DEGRADATION_GUARDRAIL")
                if any(candidate.blocked_reason == "QUIET_HOURS" for candidate in candidates):
                    codes_list.append("QUIET_HOURS_GUARDRAIL")
                codes = tuple(codes_list)
                explanation = f"{action} has the highest allowed expected net value after action cost, fatigue and safety rules."

        chosen = next(candidate for candidate in candidates if candidate.action == action)
        decision = RecoveryDecision(
            event_id=case.event_id,
            selected_action=action,
            workflow_status=status,
            execute_after_utc=self._execute_after(action, case.timestamp_utc),
            reason_codes=codes,
            explanation=explanation,
            selected_probability=chosen.recovery_probability,
            expected_net_value=chosen.expected_net_value,
            candidates=tuple(candidates),
        )
        self.audit.append("RECOVERY_DECISION", case.event_id, decision.audit_payload(), recorded_at=now)
        return decision
