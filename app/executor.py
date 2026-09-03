"""Safe, offline action executor used before Razorpay test-mode activation."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from app.database import RecoveryRepository


class SimulatedExecutor:
    """Creates non-routable artifacts and never contacts a customer or payment API."""

    mode = "SIMULATED"

    def __init__(self, repository: RecoveryRepository) -> None:
        self.repository = repository

    @staticmethod
    def reference_for(event_id: str) -> str:
        digest = hashlib.sha256(event_id.encode("utf-8")).hexdigest()[:20]
        return f"rr_demo_{digest}"

    def run_due(self, now: datetime | None = None, limit: int = 50) -> list[dict]:
        now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        return self.repository.execute_due_simulated(now, limit, self.reference_for)
