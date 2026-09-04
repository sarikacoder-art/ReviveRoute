"""Bounded simulated and explicitly enabled Razorpay Test Mode executors."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from app.database import RecoveryRepository
from app.razorpay_test import RazorpayTestClient


class SimulatedExecutor:
    """Creates non-routable artifacts and never contacts a customer or payment API."""

    mode = "SIMULATED"

    def __init__(self, repository: RecoveryRepository) -> None:
        self.repository = repository

    @staticmethod
    def reference_for(event_id: str) -> str:
        digest = hashlib.sha256(event_id.encode("utf-8")).hexdigest()[:20]
        return f"rr_demo_{digest}"

    def run_due(self, now: datetime | None = None, limit: int = 50, event_id: str | None = None) -> list[dict]:
        now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        return self.repository.execute_due_simulated(now, limit, self.reference_for, event_id=event_id)


class HybridTestExecutor:
    """Uses Razorpay Test Mode only for signed Razorpay-sourced cases.

    Manually entered, CSV and synthetic cases always stay in the non-routable
    simulator, preventing public dashboard visitors from consuming API quota.
    """

    mode = "HYBRID_RAZORPAY_TEST"

    def __init__(self, repository: RecoveryRepository, client: RazorpayTestClient) -> None:
        self.repository = repository
        self.client = client
        self.simulated = SimulatedExecutor(repository)

    @staticmethod
    def reference_for(event_id: str) -> str:
        digest = hashlib.sha256(event_id.encode("utf-8")).hexdigest()[:20]
        return f"rr_test_{digest}"

    def run_due(self, now: datetime | None = None, limit: int = 50, event_id: str | None = None) -> list[dict]:
        now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        # Explicit synthetic proof cases must remain simulated.
        if event_id is not None:
            return self.simulated.run_due(now, limit, event_id)
        results: list[dict] = []
        claimed = self.repository.claim_due_razorpay_test(now, limit)
        for case in claimed:
            try:
                provider = self.client.create_payment_link(
                    amount_inr=float(case["amount_inr"]),
                    reference_id=self.reference_for(case["event_id"]),
                    description=f"ReviveRoute test recovery {case['event_id']}",
                )
                results.append(self.repository.complete_razorpay_test_execution(
                    case["event_id"], case["selected_action"], provider, now
                ))
            except Exception as error:
                self.repository.fail_razorpay_test_execution(
                    case["event_id"], f"{type(error).__name__}: {error}", now
                )
        remaining = max(0, limit - len(claimed))
        if remaining:
            results.extend(self.simulated.run_due(now, remaining))
        return results
