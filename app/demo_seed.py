"""Idempotent fictional data seeding for an immediately useful public demo."""

from __future__ import annotations

import json
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.database import RecoveryRepository
from app.decision_engine import DecisionEngine, RecoveryCase
from app.demo import DemoFlow
from app.executor import SimulatedExecutor
from app.intake import sample_batch
from app.schemas import PromiseToPayRequest
from app.webhooks import verify_webhook_signature, webhook_signature


SEED_SIGNING_SECRET = "reviveroute-fictional-seed-signing-secret"


def seed_sample_promises(repository: RecoveryRepository) -> int:
    token = uuid.uuid4().hex[:8]
    now = datetime.now(timezone.utc).replace(microsecond=0)
    fixtures = [
        ("Aarav Traders", 18000, -4, None), ("BluePeak Studio", 42500, -1, None),
        ("Cedar Learning", 9600, 0, None), ("Dawn Retail", 27500, 2, None),
        ("Evergreen Foods", 14200, -2, -3), ("Futura Labs", 33000, -3, -1),
    ]
    for index, (name, amount, due_offset, paid_offset) in enumerate(fixtures):
        payload = PromiseToPayRequest(
            promise_id=f"promise_demo_{token}_{index + 1}", customer_id=f"demo_org_{token}_{index + 1}",
            display_name=name, amount_inr=amount, promised_at_utc=now - timedelta(days=7),
            promised_due_utc=now + timedelta(days=due_offset), source="SYNTHETIC_DEMO",
        )
        repository.create_promise(payload.model_dump(mode="json"))
        if paid_offset is not None:
            repository.mark_promise_paid(payload.promise_id, (now + timedelta(days=paid_offset)).isoformat())
    return len(fixtures)


def seed_recovered_portfolio(
    repository: RecoveryRepository,
    executor: SimulatedExecutor,
    candidates: list[tuple[object, object]],
) -> list[dict]:
    """Close varied fictional cases through execution and verified signed outcomes."""
    by_action: dict[str, list[tuple[object, object]]] = defaultdict(list)
    for payload, decision in candidates:
        if decision.workflow_status == "SCHEDULED" and decision.selected_action in {
            "LINK_NOW", "LINK_AFTER_2H", "LINK_NEXT_MORNING"
        }:
            by_action[decision.selected_action].append((payload, decision))

    chosen: list[tuple[object, object]] = []
    for action in ("LINK_NOW", "LINK_AFTER_2H", "LINK_NEXT_MORNING"):
        seen_reasons: set[str] = set()
        for payload, decision in by_action[action]:
            if payload.failure_reason in seen_reasons:
                continue
            chosen.append((payload, decision))
            seen_reasons.add(payload.failure_reason)
            if len(seen_reasons) == 3:
                break

    recovered: list[dict] = []
    due_time = datetime.now(timezone.utc) + timedelta(days=2)
    for index, (payload, decision) in enumerate(chosen, start=1):
        executions = executor.run_due(now=due_time, limit=1, event_id=payload.event_id)
        if not executions:
            raise RuntimeError(f"fictional seed case {payload.event_id} was not executable")
        execution = executions[0]
        delivery_id = f"seed_paid_{uuid.uuid4().hex[:12]}"
        payment_id = f"seed_payment_{index}_{uuid.uuid4().hex[:8]}"
        paid_payload = {
            "event": "payment_link.paid",
            "payload": {
                "payment": {"entity": {"id": payment_id, "amount": int(payload.amount_inr * 100), "currency": "INR"}},
                "payment_link": {"entity": {"reference_id": execution["reference_id"], "status": "paid"}},
            },
        }
        raw = json.dumps(paid_payload, separators=(",", ":")).encode("utf-8")
        signature = webhook_signature(raw, SEED_SIGNING_SECRET)
        if not verify_webhook_signature(raw, signature, SEED_SIGNING_SECRET):
            raise RuntimeError("fictional seed outcome signature verification failed")
        repository.register_webhook(delivery_id, "payment_link.paid", raw)
        outcome, _ = repository.record_recovery_outcome(
            reference_id=execution["reference_id"], payment_id=payment_id,
            amount_inr=payload.amount_inr, webhook_delivery_id=delivery_id,
        )
        repository.complete_webhook(delivery_id, {"status": "processed", "event": "payment_link.paid", "case_event_id": payload.event_id})
        recovered.append({
            "event_id": payload.event_id, "failure_reason": payload.failure_reason,
            "selected_action": decision.selected_action, "amount_inr": outcome["amount_inr"],
        })
    return recovered


def seed_empty_demo(repository: RecoveryRepository, engine: DecisionEngine, executor: SimulatedExecutor) -> dict:
    cases_seeded = 0
    signed_recoveries_seeded = 0
    promises_seeded = 0
    summary_before = repository.summary()
    existing_cases = repository.list_cases(limit=200)
    recovered_actions = {item["recovery_action"] for item in summary_before["observed_test_recovery"].get("breakdown", [])}
    needs_varied_showcase = not {"LINK_NOW", "LINK_AFTER_2H", "LINK_NEXT_MORNING"}.issubset(recovered_actions)
    is_empty = summary_before["case_count"] == 0
    is_older_fictional_demo = (
        0 < summary_before["case_count"] <= 30
        and summary_before["observed_test_recovery"]["recovered_case_count"] <= 1
        and all(item["event_id"].startswith(("sample_", "demo_failed_")) for item in existing_cases)
    )
    if is_empty or is_older_fictional_demo or needs_varied_showcase:
        candidates = []
        local_now = datetime.now(ZoneInfo("Asia/Kolkata"))
        business_time = local_now.replace(hour=10, minute=0, second=0, microsecond=0)
        if business_time > local_now:
            business_time -= timedelta(days=1)
        for index, original in enumerate(sample_batch(40)):
            payload = original.model_copy(update={"timestamp_utc": (business_time + timedelta(minutes=index)).astimezone(timezone.utc)})
            request = payload.model_dump(mode="json")
            case = RecoveryCase(**payload.model_dump(), case_created_at_utc=payload.timestamp_utc)
            decision = engine.decide(case)
            repository.create_case(request, decision)
            candidates.append((payload, decision))
            cases_seeded += 1
        recovered_portfolio = seed_recovered_portfolio(repository, executor, candidates)
        if is_empty:
            DemoFlow(repository, engine, executor).run()
        signed_recoveries_seeded = len(recovered_portfolio) + (1 if is_empty else 0)
    else:
        recovered_portfolio = []
    if repository.promise_summary()["promise_count"] == 0:
        promises_seeded = seed_sample_promises(repository)
    return {
        "mode": "AUTO_UPGRADED_FICTIONAL_DEMO" if (is_older_fictional_demo or (needs_varied_showcase and not is_empty)) else "AUTO_SEEDED_FICTIONAL_DEMO",
        "cases_seeded": cases_seeded,
        "signed_recoveries_seeded": signed_recoveries_seeded,
        "recovery_examples": recovered_portfolio,
        "promises_seeded": promises_seeded,
        "production_claim": False,
    }
