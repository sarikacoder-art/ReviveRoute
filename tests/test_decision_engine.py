"""Tests for bounded recovery decisions and audit integrity."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import joblib
import pandas as pd

from app.audit import AuditEntry, AuditTrail
from app.decision_engine import DecisionEngine, RecoveryCase
from app.run_policy_demo import run_demo


def make_case(**overrides) -> RecoveryCase:
    values = {
        "event_id": "evt_test",
        "customer_id": "cust_test",
        "timestamp_utc": datetime(2026, 8, 20, 14, tzinfo=timezone.utc),
        "case_created_at_utc": datetime(2026, 8, 20, 14, tzinfo=timezone.utc),
        "amount_inr": 4_000.0,
        "payment_method": "upi",
        "failure_reason": "insufficient_funds",
        "customer_tenure_days": 200.0,
        "prior_successes": 6,
        "prior_failures": 2,
        "prior_recoveries": 1,
        "contacts_last_7_days": 0,
        "recent_method_failure_rate": 0.2,
        "degradation_flag": 0,
    }
    values.update(overrides)
    return RecoveryCase(**values)


def engine() -> DecisionEngine:
    return DecisionEngine(joblib.load("models/action_model.joblib"), AuditTrail())


def decide_current(policy: DecisionEngine, case: RecoveryCase):
    """Evaluate the historical fixture while its recovery window is open."""
    return policy.decide(case, now=case.timestamp_utc + timedelta(minutes=1))


def test_normal_decision_has_all_candidate_scores_and_audit_entry():
    policy = engine()
    decision = policy.decide(make_case(), now=datetime(2026, 8, 20, 14, 1, tzinfo=timezone.utc))
    assert len(decision.candidates) == 5
    assert decision.selected_action in {candidate.action for candidate in decision.candidates}
    assert policy.audit.verify() and len(policy.audit.entries) == 1


def test_opt_out_stops_contact():
    case = make_case(opted_out=True)
    decision = decide_current(engine(), case)
    assert decision.selected_action == "NO_CONTACT"
    assert decision.workflow_status == "STOPPED"
    assert "CUSTOMER_OPTED_OUT" in decision.reason_codes


def test_already_recovered_stops_contact():
    case = make_case(already_recovered=True)
    assert decide_current(engine(), case).reason_codes == ("ALREADY_RECOVERED",)


def test_contact_fatigue_limit_stops_contact():
    case = make_case(contacts_last_7_days=3)
    decision = decide_current(engine(), case)
    assert decision.selected_action == "NO_CONTACT"
    assert "CONTACT_FATIGUE_LIMIT" in decision.reason_codes


def test_max_attempts_is_a_stopping_rule():
    case = make_case(automated_attempts=3)
    decision = decide_current(engine(), case)
    assert decision.workflow_status == "STOPPED"
    assert "MAX_ATTEMPTS_REACHED" in decision.reason_codes


def test_expired_window_is_a_stopping_rule():
    case = make_case()
    decision = engine().decide(case, now=case.timestamp_utc + timedelta(hours=73))
    assert "RECOVERY_WINDOW_EXPIRED" in decision.reason_codes


def test_sensitive_failures_escalate_without_link():
    for reason in ("risk_declined", "card_blocked"):
        case = make_case(failure_reason=reason)
        decision = decide_current(engine(), case)
        assert decision.selected_action == "HUMAN_REVIEW"
        assert decision.workflow_status == "ESCALATED"


def test_high_value_case_requires_human_review():
    case = make_case(amount_inr=25_000)
    assert decide_current(engine(), case).selected_action == "HUMAN_REVIEW"


def test_degradation_blocks_immediate_link():
    case = make_case(degradation_flag=1)
    decision = decide_current(engine(), case)
    now_score = next(candidate for candidate in decision.candidates if candidate.action == "LINK_NOW")
    assert not now_score.allowed and now_score.blocked_reason == "ACTIVE_PAYMENT_DEGRADATION"
    assert decision.selected_action != "LINK_NOW"


def test_quiet_hours_blocks_immediate_and_two_hour_links():
    case = make_case(timestamp_utc=datetime(2026, 8, 20, 23, tzinfo=timezone.utc))
    decision = decide_current(engine(), case)
    blocked = {candidate.action for candidate in decision.candidates if candidate.blocked_reason == "QUIET_HOURS"}
    assert blocked == {"LINK_NOW", "LINK_AFTER_2H"}


def test_next_morning_is_eight_am_in_merchant_timezone():
    policy = engine()
    case = make_case(timestamp_utc=datetime(2026, 8, 20, 23, tzinfo=timezone.utc))
    scheduled = datetime.fromisoformat(policy._execute_after("LINK_NEXT_MORNING", case.timestamp_utc))
    local = scheduled.astimezone(policy.merchant_timezone)
    assert (local.hour, local.minute) == (8, 0)


def test_invalid_case_is_rejected():
    try:
        make_case(amount_inr=0)
        assert False, "expected validation error"
    except ValueError:
        pass


def test_audit_chain_detects_tampering(tmp_path):
    audit = AuditTrail()
    audit.append("RECOVERY_DECISION", "one", {"action": "NO_CONTACT"})
    audit.append("RECOVERY_DECISION", "two", {"action": "LINK_NOW"})
    assert audit.verify()
    second = audit.entries[1]
    audit.entries[1] = replace(second, payload={"action": "HUMAN_REVIEW"})
    assert not audit.verify()
    path = tmp_path / "audit.jsonl"
    AuditTrail(audit.entries[:1]).write_jsonl(path)
    assert AuditTrail.read_jsonl(path).verify()


def test_policy_demo_produces_bounded_audited_batch():
    summary = run_demo(limit=10)
    assert summary["batch_cases"] == 10
    assert summary["audit_entries"] == 10
    assert summary["audit_chain_valid"] is True
    assert 0 <= summary["expected_net_recovery_rate"] <= 1
