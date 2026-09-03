"""One-click, fully local demonstration of the complete recovery loop."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

from app.database import RecoveryRepository
from app.decision_engine import DecisionEngine
from app.executor import SimulatedExecutor
from app.webhooks import failed_payment_to_case, parse_webhook, payment_entity, verify_webhook_signature, webhook_signature

DEMO_SIGNING_SECRET = "reviveroute-isolated-demo-signing-secret"


class DemoFlow:
    def __init__(self, repository: RecoveryRepository, engine: DecisionEngine, executor: SimulatedExecutor) -> None:
        self.repository = repository
        self.engine = engine
        self.executor = executor

    @staticmethod
    def _encode(payload: dict) -> bytes:
        return json.dumps(payload, separators=(",", ":")).encode("utf-8")

    def run(self) -> dict:
        token = uuid.uuid4().hex[:12]
        now = datetime.now(timezone.utc)
        failed_delivery = f"demo_failed_{token}"
        payment_id = f"pay_demo_{token}"
        failure_payload = {
            "event": "payment.failed",
            "payload": {
                "payment": {
                    "entity": {
                        "id": payment_id,
                        "amount": 180_000,
                        "currency": "INR",
                        "status": "failed",
                        "method": "upi",
                        "customer_id": f"cust_demo_{token}",
                        "created_at": int(now.timestamp()),
                        "error_code": "GATEWAY_ERROR",
                        "error_source": "bank",
                        "error_step": "payment_authorization",
                        "error_reason": "temporary_network_issue",
                        "error_description": "Temporary bank connectivity issue",
                    }
                }
            },
        }
        raw_failure = self._encode(failure_payload)
        failure_signature = webhook_signature(raw_failure, DEMO_SIGNING_SECRET)
        signature_verified = verify_webhook_signature(raw_failure, failure_signature, DEMO_SIGNING_SECRET)
        webhook = parse_webhook(raw_failure)
        self.repository.register_webhook(failed_delivery, webhook["event"], raw_failure)
        payment = payment_entity(webhook)
        features = self.repository.customer_features(str(payment["customer_id"]), now)
        case = failed_payment_to_case(webhook, failed_delivery, features)
        decision = self.engine.decide(case, now=now)
        case_request = {
            "event_id": case.event_id,
            "source_payment_id": payment_id,
            "customer_id": case.customer_id,
            "timestamp_utc": case.timestamp_utc.isoformat(),
            "amount_inr": case.amount_inr,
            "payment_method": case.payment_method,
            "failure_reason": case.failure_reason,
            "customer_tenure_days": case.customer_tenure_days,
            "prior_successes": case.prior_successes,
            "prior_failures": case.prior_failures,
            "prior_recoveries": case.prior_recoveries,
            "contacts_last_7_days": case.contacts_last_7_days,
            "recent_method_failure_rate": case.recent_method_failure_rate,
            "degradation_flag": case.degradation_flag,
            "automated_attempts": 0,
            "opted_out": False,
            "already_recovered": False,
        }
        stored, _ = self.repository.create_case(case_request, decision)
        self.repository.complete_webhook(failed_delivery, {"status": "processed", "event": "payment.failed", "case_event_id": failed_delivery})

        if decision.workflow_status != "SCHEDULED" or not decision.execute_after_utc:
            raise RuntimeError("demo fixture did not produce a schedulable bounded action")
        due_time = datetime.fromisoformat(decision.execute_after_utc) + timedelta(seconds=1)
        executions = self.executor.run_due(now=due_time, limit=1, event_id=failed_delivery)
        if not executions:
            raise RuntimeError("demo action was not executed")
        execution = executions[0]

        paid_delivery = f"demo_paid_{token}"
        paid_payload = {
            "event": "payment_link.paid",
            "payload": {
                "payment": {"entity": {"id": f"pay_recovered_{token}", "amount": 180_000, "currency": "INR"}},
                "payment_link": {"entity": {"id": f"plink_demo_{token}", "reference_id": execution["reference_id"], "status": "paid"}},
            },
        }
        raw_paid = self._encode(paid_payload)
        paid_signature = webhook_signature(raw_paid, DEMO_SIGNING_SECRET)
        paid_signature_verified = verify_webhook_signature(raw_paid, paid_signature, DEMO_SIGNING_SECRET)
        self.repository.register_webhook(paid_delivery, "payment_link.paid", raw_paid)
        outcome, _ = self.repository.record_recovery_outcome(
            reference_id=execution["reference_id"],
            payment_id=f"pay_recovered_{token}",
            amount_inr=1800.0,
            webhook_delivery_id=paid_delivery,
        )
        self.repository.complete_webhook(paid_delivery, {"status": "processed", "event": "payment_link.paid", "case_event_id": failed_delivery})
        final_case = self.repository.get_case(failed_delivery)
        audit = self.repository.verify_audit_chain()
        return {
            "demo_mode": "SIGNED_SIMULATION",
            "production_claim": False,
            "customer_contacted": False,
            "payment_api_called": False,
            "failure_signature_verified": signature_verified,
            "outcome_signature_verified": paid_signature_verified,
            "timeline": [
                {"stage": "DETECTED", "detail": f"UPI payment failed · ₹{case.amount_inr:,.0f} at risk"},
                {"stage": "DIAGNOSED", "detail": "Temporary network issue identified from Razorpay error fields"},
                {"stage": "DECIDED", "detail": f"{decision.selected_action} selected · {decision.selected_probability:.0%} predicted recovery"},
                {"stage": "EXECUTED", "detail": "Safe simulated recovery artifact created · no customer contacted"},
                {"stage": "RECOVERED", "detail": "Signed demo paid event attributed to the exact recovery reference"},
            ],
            "decision_before_execution": stored,
            "execution": execution,
            "outcome": outcome,
            "case": final_case,
            "summary": self.repository.summary(),
            "audit": audit,
        }
