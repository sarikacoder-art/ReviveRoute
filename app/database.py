"""SQLite persistence and workflow invariants for ReviveRoute."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from app.audit import GENESIS_HASH
from app.decision_engine import RecoveryDecision

TERMINAL_STATUSES = {"RECOVERED", "STOPPED", "EXPIRED", "CANCELLED", "FAILED"}
ALLOWED_TRANSITIONS = {
    "SCHEDULED": {"EXECUTING", "RECOVERED", "STOPPED", "EXPIRED", "CANCELLED"},
    "EXECUTING": {"ACTION_SENT", "RECOVERED", "STOPPED", "FAILED"},
    "ACTION_SENT": {"RECOVERED", "STOPPED", "EXPIRED", "FAILED"},
    "ESCALATED": {"UNDER_REVIEW", "RECOVERED", "STOPPED"},
    "UNDER_REVIEW": {"SCHEDULED", "RECOVERED", "STOPPED"},
    "MONITORING": {"SCHEDULED", "RECOVERED", "STOPPED", "EXPIRED"},
}


class CaseConflictError(Exception):
    """An event ID was replayed with a different payload."""


class InvalidTransitionError(Exception):
    """A requested workflow transition violates the state machine."""


class CaseNotFoundError(Exception):
    """No recovery case exists for the supplied event ID."""


class WebhookConflictError(Exception):
    """A delivery ID was reused with different signed content."""


class RecoveryAttributionError(Exception):
    """A paid event cannot be attributed safely to one recovery case."""


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def payload_fingerprint(payload: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


class RecoveryRepository:
    def __init__(self, database_path: str | Path) -> None:
        self.database_path = str(database_path)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode = WAL;
                CREATE TABLE IF NOT EXISTS recovery_cases (
                    event_id TEXT PRIMARY KEY,
                    source_payment_id TEXT,
                    customer_id TEXT NOT NULL,
                    payload_fingerprint TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    amount_inr REAL NOT NULL CHECK (amount_inr > 0),
                    selected_action TEXT NOT NULL,
                    workflow_status TEXT NOT NULL,
                    execute_after_utc TEXT,
                    reason_codes_json TEXT NOT NULL,
                    explanation TEXT NOT NULL,
                    selected_probability REAL NOT NULL CHECK (selected_probability BETWEEN 0 AND 1),
                    expected_net_value REAL NOT NULL,
                    created_at_utc TEXT NOT NULL,
                    updated_at_utc TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS candidate_scores (
                    event_id TEXT NOT NULL REFERENCES recovery_cases(event_id) ON DELETE CASCADE,
                    action TEXT NOT NULL,
                    recovery_probability REAL NOT NULL,
                    expected_recovered_amount REAL NOT NULL,
                    action_cost REAL NOT NULL,
                    fatigue_penalty REAL NOT NULL,
                    expected_net_value REAL NOT NULL,
                    allowed INTEGER NOT NULL CHECK (allowed IN (0, 1)),
                    blocked_reason TEXT,
                    PRIMARY KEY (event_id, action)
                );
                CREATE TABLE IF NOT EXISTS workflow_events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    recorded_at_utc TEXT NOT NULL,
                    event_id TEXT NOT NULL REFERENCES recovery_cases(event_id) ON DELETE CASCADE,
                    event_type TEXT NOT NULL,
                    from_status TEXT,
                    to_status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    previous_hash TEXT NOT NULL,
                    entry_hash TEXT NOT NULL UNIQUE
                );
                CREATE INDEX IF NOT EXISTS idx_cases_status ON recovery_cases(workflow_status);
                CREATE INDEX IF NOT EXISTS idx_events_case ON workflow_events(event_id, sequence);
                CREATE TABLE IF NOT EXISTS webhook_deliveries (
                    delivery_id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    processing_status TEXT NOT NULL,
                    response_json TEXT,
                    received_at_utc TEXT NOT NULL,
                    processed_at_utc TEXT
                );
                CREATE TABLE IF NOT EXISTS executions (
                    reference_id TEXT PRIMARY KEY,
                    event_id TEXT NOT NULL UNIQUE REFERENCES recovery_cases(event_id) ON DELETE CASCADE,
                    action TEXT NOT NULL,
                    execution_mode TEXT NOT NULL CHECK (execution_mode = 'SIMULATED'),
                    artifact_url TEXT NOT NULL,
                    created_at_utc TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS recovery_outcomes (
                    event_id TEXT PRIMARY KEY REFERENCES recovery_cases(event_id) ON DELETE CASCADE,
                    webhook_delivery_id TEXT NOT NULL UNIQUE,
                    reference_id TEXT NOT NULL UNIQUE REFERENCES executions(reference_id),
                    payment_id TEXT NOT NULL UNIQUE,
                    recovered_amount_inr REAL NOT NULL CHECK (recovered_amount_inr > 0),
                    evidence_mode TEXT NOT NULL,
                    recovered_at_utc TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS payment_promises (
                    promise_id TEXT PRIMARY KEY,
                    customer_id TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    amount_inr REAL NOT NULL CHECK (amount_inr > 0),
                    promised_at_utc TEXT NOT NULL,
                    promised_due_utc TEXT NOT NULL,
                    paid_at_utc TEXT,
                    source TEXT NOT NULL,
                    created_at_utc TEXT NOT NULL
                );
                """
            )
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(recovery_cases)").fetchall()}
            if "source_payment_id" not in columns:
                connection.execute("ALTER TABLE recovery_cases ADD COLUMN source_payment_id TEXT")
            connection.commit()

    @staticmethod
    def _append_event(
        connection: sqlite3.Connection,
        event_id: str,
        event_type: str,
        from_status: str | None,
        to_status: str,
        payload: dict[str, Any],
        recorded_at: str,
    ) -> None:
        previous = connection.execute("SELECT entry_hash FROM workflow_events ORDER BY sequence DESC LIMIT 1").fetchone()
        previous_hash = previous["entry_hash"] if previous else GENESIS_HASH
        unsigned = {
            "recorded_at_utc": recorded_at,
            "event_id": event_id,
            "event_type": event_type,
            "from_status": from_status,
            "to_status": to_status,
            "payload": payload,
            "previous_hash": previous_hash,
        }
        entry_hash = hashlib.sha256(canonical_json(unsigned).encode("utf-8")).hexdigest()
        connection.execute(
            """INSERT INTO workflow_events
               (recorded_at_utc, event_id, event_type, from_status, to_status,
                payload_json, previous_hash, entry_hash)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (recorded_at, event_id, event_type, from_status, to_status, canonical_json(payload), previous_hash, entry_hash),
        )

    def create_case(self, request: dict[str, Any], decision: RecoveryDecision) -> tuple[dict[str, Any], bool]:
        fingerprint = payload_fingerprint(request)
        event_id = str(request["event_id"])
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute("SELECT payload_fingerprint FROM recovery_cases WHERE event_id = ?", (event_id,)).fetchone()
            if existing:
                connection.rollback()
                if existing["payload_fingerprint"] != fingerprint:
                    raise CaseConflictError(event_id)
                return self.get_case(event_id), True

            connection.execute(
                """INSERT INTO recovery_cases
                   (event_id, source_payment_id, customer_id, payload_fingerprint, request_json, amount_inr,
                    selected_action, workflow_status, execute_after_utc, reason_codes_json,
                    explanation, selected_probability, expected_net_value, created_at_utc, updated_at_utc)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    event_id, request.get("source_payment_id"), str(request["customer_id"]), fingerprint, canonical_json(request),
                    float(request["amount_inr"]), decision.selected_action, decision.workflow_status,
                    decision.execute_after_utc, canonical_json(list(decision.reason_codes)), decision.explanation,
                    decision.selected_probability, decision.expected_net_value, now, now,
                ),
            )
            for candidate in decision.candidates:
                connection.execute(
                    """INSERT INTO candidate_scores
                       (event_id, action, recovery_probability, expected_recovered_amount,
                        action_cost, fatigue_penalty, expected_net_value, allowed, blocked_reason)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (event_id, candidate.action, candidate.recovery_probability, candidate.expected_recovered_amount,
                     candidate.action_cost, candidate.fatigue_penalty, candidate.expected_net_value,
                     int(candidate.allowed), candidate.blocked_reason),
                )
            self._append_event(connection, event_id, "CASE_DECIDED", None, decision.workflow_status, decision.audit_payload(), now)
            connection.commit()
        return self.get_case(event_id), False

    def get_case(self, event_id: str) -> dict[str, Any]:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM recovery_cases WHERE event_id = ?", (event_id,)).fetchone()
            if not row:
                raise CaseNotFoundError(event_id)
            candidates = connection.execute("SELECT * FROM candidate_scores WHERE event_id = ? ORDER BY expected_net_value DESC", (event_id,)).fetchall()
            events = connection.execute("SELECT * FROM workflow_events WHERE event_id = ? ORDER BY sequence", (event_id,)).fetchall()
        result = dict(row)
        result.pop("payload_fingerprint")
        result["request"] = json.loads(result.pop("request_json"))
        result["reason_codes"] = json.loads(result.pop("reason_codes_json"))
        result["candidates"] = [{**dict(item), "allowed": bool(item["allowed"])} for item in candidates]
        result["events"] = [{**dict(item), "payload": json.loads(item["payload_json"])} for item in events]
        for event in result["events"]:
            event.pop("payload_json")
        return result

    def list_cases(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT event_id, source_payment_id, customer_id, amount_inr, selected_action, workflow_status,
                          expected_net_value, created_at_utc, updated_at_utc
                   FROM recovery_cases ORDER BY created_at_utc DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def transition(self, event_id: str, to_status: str, reason: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT workflow_status FROM recovery_cases WHERE event_id = ?", (event_id,)).fetchone()
            if not row:
                connection.rollback()
                raise CaseNotFoundError(event_id)
            current = row["workflow_status"]
            if to_status not in ALLOWED_TRANSITIONS.get(current, set()):
                connection.rollback()
                raise InvalidTransitionError(f"{current} -> {to_status}")
            payload = {"reason": reason, "metadata": metadata or {}}
            connection.execute("UPDATE recovery_cases SET workflow_status = ?, updated_at_utc = ? WHERE event_id = ?", (to_status, now, event_id))
            self._append_event(connection, event_id, "STATUS_TRANSITION", current, to_status, payload, now)
            connection.commit()
        return self.get_case(event_id)

    def summary(self) -> dict[str, Any]:
        with self.connect() as connection:
            totals = connection.execute(
                """SELECT COUNT(*) AS cases, COALESCE(SUM(amount_inr), 0) AS amount_at_risk,
                          COALESCE(SUM(CASE WHEN expected_net_value > 0 THEN expected_net_value ELSE 0 END), 0) AS expected_net_recovery
                   FROM recovery_cases"""
            ).fetchone()
            statuses = connection.execute("SELECT workflow_status, COUNT(*) AS count FROM recovery_cases GROUP BY workflow_status").fetchall()
            actions = connection.execute("SELECT selected_action, COUNT(*) AS count FROM recovery_cases GROUP BY selected_action").fetchall()
            observed = connection.execute(
                "SELECT COUNT(*) AS count, COALESCE(SUM(recovered_amount_inr), 0) AS amount FROM recovery_outcomes"
            ).fetchone()
        amount = float(totals["amount_at_risk"])
        expected = float(totals["expected_net_recovery"])
        return {
            "evidence_label": "model-based expectations; not observed or causal revenue",
            "case_count": int(totals["cases"]),
            "revenue_at_risk_inr": round(amount, 2),
            "expected_net_recovery_inr": round(expected, 2),
            "expected_net_recovery_rate": round(expected / amount, 4) if amount else 0.0,
            "status_distribution": {row["workflow_status"]: row["count"] for row in statuses},
            "action_distribution": {row["selected_action"]: row["count"] for row in actions},
            "observed_test_recovery": {
                "evidence_label": "signed simulated/test webhook outcomes; not production revenue",
                "recovered_case_count": int(observed["count"]),
                "recovered_amount_inr": round(float(observed["amount"]), 2),
            },
        }

    def create_promise(self, payload: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as connection:
            existing = connection.execute("SELECT * FROM payment_promises WHERE promise_id = ?", (payload["promise_id"],)).fetchone()
            if existing:
                return self._promise_view(dict(existing)), True
            connection.execute(
                """INSERT INTO payment_promises
                   (promise_id, customer_id, display_name, amount_inr, promised_at_utc,
                    promised_due_utc, paid_at_utc, source, created_at_utc)
                   VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?)""",
                (payload["promise_id"], payload["customer_id"], payload["display_name"],
                 float(payload["amount_inr"]), payload["promised_at_utc"],
                 payload["promised_due_utc"], payload["source"], now),
            )
            connection.commit()
        return self.get_promise(payload["promise_id"]), False

    @staticmethod
    def _promise_view(row: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
        current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        due = datetime.fromisoformat(row["promised_due_utc"])
        if row.get("paid_at_utc"):
            status = "PROMISE_KEPT" if datetime.fromisoformat(row["paid_at_utc"]) <= due else "PAID_LATE"
        elif current > due:
            status = "PROMISE_BROKEN"
        elif due.date() == current.date():
            status = "DUE_TODAY"
        else:
            status = "PROMISE_ACTIVE"
        return {**row, "status": status, "days_overdue": max(0, (current.date() - due.date()).days) if not row.get("paid_at_utc") else 0}

    def get_promise(self, promise_id: str) -> dict[str, Any]:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM payment_promises WHERE promise_id = ?", (promise_id,)).fetchone()
        if not row:
            raise CaseNotFoundError(promise_id)
        return self._promise_view(dict(row))

    def list_promises(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute("SELECT * FROM payment_promises ORDER BY promised_due_utc LIMIT ?", (limit,)).fetchall()
        return [self._promise_view(dict(row)) for row in rows]

    def mark_promise_paid(self, promise_id: str, paid_at_utc: str) -> dict[str, Any]:
        with self.connect() as connection:
            changed = connection.execute("UPDATE payment_promises SET paid_at_utc = ? WHERE promise_id = ? AND paid_at_utc IS NULL", (paid_at_utc, promise_id))
            connection.commit()
        if changed.rowcount == 0:
            return self.get_promise(promise_id)
        return self.get_promise(promise_id)

    def promise_summary(self) -> dict[str, Any]:
        promises = self.list_promises(500)
        broken = [item for item in promises if item["status"] == "PROMISE_BROKEN"]
        paid = [item for item in promises if item["paid_at_utc"]]
        kept = [item for item in promises if item["status"] == "PROMISE_KEPT"]
        return {
            "evidence_label": "promise tracking only; fictional labels in demo data and no ML inference",
            "promise_count": len(promises),
            "broken_count": len(broken),
            "broken_amount_inr": round(sum(item["amount_inr"] for item in broken), 2),
            "outstanding_amount_inr": round(sum(item["amount_inr"] for item in promises if not item["paid_at_utc"]), 2),
            "promise_kept_rate": round(len(kept) / len(paid), 4) if paid else 0.0,
        }

    def register_webhook(self, delivery_id: str, event_type: str, raw_body: bytes) -> dict[str, Any] | None:
        body_hash = hashlib.sha256(raw_body).hexdigest()
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM webhook_deliveries WHERE delivery_id = ?", (delivery_id,)).fetchone()
            if row:
                connection.rollback()
                if row["payload_hash"] != body_hash or row["event_type"] != event_type:
                    raise WebhookConflictError(delivery_id)
                if row["processing_status"] == "PROCESSED":
                    response = json.loads(row["response_json"])
                    response["duplicate"] = True
                    return response
                return None
            connection.execute(
                """INSERT INTO webhook_deliveries
                   (delivery_id, event_type, payload_hash, processing_status, received_at_utc)
                   VALUES (?, ?, ?, 'RECEIVED', ?)""",
                (delivery_id, event_type, body_hash, now),
            )
            connection.commit()
        return None

    def complete_webhook(self, delivery_id: str, response: dict[str, Any]) -> None:
        with self.connect() as connection:
            connection.execute(
                """UPDATE webhook_deliveries SET processing_status = 'PROCESSED', response_json = ?, processed_at_utc = ?
                   WHERE delivery_id = ?""",
                (canonical_json(response), datetime.now(timezone.utc).isoformat(), delivery_id),
            )
            connection.commit()

    def customer_features(self, customer_id: str, now: datetime) -> dict[str, Any]:
        cutoff = (now - timedelta(days=7)).isoformat()
        with self.connect() as connection:
            history = connection.execute(
                """SELECT COUNT(*) AS failures, MIN(created_at_utc) AS first_seen,
                          SUM(CASE WHEN workflow_status = 'RECOVERED' THEN 1 ELSE 0 END) AS recoveries
                   FROM recovery_cases WHERE customer_id = ?""",
                (customer_id,),
            ).fetchone()
            contacts = connection.execute(
                """SELECT COUNT(*) AS count FROM executions e JOIN recovery_cases c ON c.event_id = e.event_id
                   WHERE c.customer_id = ? AND e.created_at_utc >= ?""",
                (customer_id, cutoff),
            ).fetchone()["count"]
        first_seen = datetime.fromisoformat(history["first_seen"]) if history["first_seen"] else now
        recoveries = int(history["recoveries"] or 0)
        return {
            "customer_tenure_days": max((now - first_seen).total_seconds() / 86_400, 0.0),
            "prior_successes": recoveries,
            "prior_failures": int(history["failures"] or 0),
            "prior_recoveries": recoveries,
            "contacts_last_7_days": int(contacts),
            "recent_method_failure_rate": 0.0,
            "degradation_flag": 0,
        }

    def execute_due_simulated(
        self, now: datetime, limit: int, reference_factory, event_id: str | None = None
    ) -> list[dict[str, Any]]:
        results = []
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                """SELECT event_id, selected_action, workflow_status FROM recovery_cases
                   WHERE workflow_status = 'SCHEDULED' AND execute_after_utc IS NOT NULL AND execute_after_utc <= ?
                     AND (? IS NULL OR event_id = ?)
                     AND selected_action IN ('LINK_NOW', 'LINK_AFTER_2H', 'LINK_NEXT_MORNING')
                   ORDER BY execute_after_utc LIMIT ?""",
                (now.isoformat(), event_id, event_id, limit),
            ).fetchall()
            for row in rows:
                event_id, action = row["event_id"], row["selected_action"]
                reference_id = reference_factory(event_id)
                artifact_url = f"https://example.invalid/recovery/{reference_id}"
                connection.execute(
                    """INSERT OR IGNORE INTO executions
                       (reference_id, event_id, action, execution_mode, artifact_url, created_at_utc)
                       VALUES (?, ?, ?, 'SIMULATED', ?, ?)""",
                    (reference_id, event_id, action, artifact_url, now.isoformat()),
                )
                self._append_event(connection, event_id, "EXECUTION_STARTED", "SCHEDULED", "EXECUTING", {"mode": "SIMULATED"}, now.isoformat())
                payload = {"mode": "SIMULATED", "reference_id": reference_id, "artifact_url": artifact_url, "customer_contacted": False, "payment_api_called": False}
                self._append_event(connection, event_id, "ACTION_SIMULATED", "EXECUTING", "ACTION_SENT", payload, now.isoformat())
                connection.execute("UPDATE recovery_cases SET workflow_status = 'ACTION_SENT', updated_at_utc = ? WHERE event_id = ?", (now.isoformat(), event_id))
                results.append({"event_id": event_id, "action": action, **payload})
            connection.commit()
        return results

    def record_recovery_outcome(
        self, reference_id: str, payment_id: str, amount_inr: float, webhook_delivery_id: str
    ) -> tuple[dict[str, Any], bool]:
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            execution = connection.execute(
                """SELECT e.event_id, c.amount_inr, c.workflow_status FROM executions e
                   JOIN recovery_cases c ON c.event_id = e.event_id WHERE e.reference_id = ?""",
                (reference_id,),
            ).fetchone()
            if not execution:
                connection.rollback()
                raise RecoveryAttributionError("unknown recovery reference_id")
            if abs(float(execution["amount_inr"]) - amount_inr) > 0.01:
                connection.rollback()
                raise RecoveryAttributionError("paid amount does not match the failed payment amount")
            existing = connection.execute("SELECT * FROM recovery_outcomes WHERE event_id = ?", (execution["event_id"],)).fetchone()
            if existing:
                connection.rollback()
                if existing["payment_id"] != payment_id or existing["reference_id"] != reference_id:
                    raise RecoveryAttributionError("case already has a different recovery outcome")
                return dict(existing), True
            connection.execute(
                """INSERT INTO recovery_outcomes
                   (event_id, webhook_delivery_id, reference_id, payment_id, recovered_amount_inr, evidence_mode, recovered_at_utc)
                   VALUES (?, ?, ?, ?, ?, 'SIGNED_DEMO_WEBHOOK', ?)""",
                (execution["event_id"], webhook_delivery_id, reference_id, payment_id, amount_inr, now),
            )
            payload = {"reference_id": reference_id, "payment_id": payment_id, "amount_inr": amount_inr, "evidence_mode": "SIGNED_DEMO_WEBHOOK"}
            self._append_event(connection, execution["event_id"], "RECOVERY_OBSERVED", execution["workflow_status"], "RECOVERED", payload, now)
            connection.execute("UPDATE recovery_cases SET workflow_status = 'RECOVERED', updated_at_utc = ? WHERE event_id = ?", (now, execution["event_id"]))
            connection.commit()
        return payload, False

    def verify_audit_chain(self) -> dict[str, Any]:
        with self.connect() as connection:
            rows = connection.execute("SELECT * FROM workflow_events ORDER BY sequence").fetchall()
        previous_hash = GENESIS_HASH
        for row in rows:
            payload = json.loads(row["payload_json"])
            unsigned = {
                "recorded_at_utc": row["recorded_at_utc"], "event_id": row["event_id"],
                "event_type": row["event_type"], "from_status": row["from_status"],
                "to_status": row["to_status"], "payload": payload, "previous_hash": row["previous_hash"],
            }
            calculated = hashlib.sha256(canonical_json(unsigned).encode("utf-8")).hexdigest()
            if row["previous_hash"] != previous_hash or row["entry_hash"] != calculated:
                return {"valid": False, "entries_checked": row["sequence"] - 1, "failed_sequence": row["sequence"]}
            previous_hash = row["entry_hash"]
        return {"valid": True, "entries_checked": len(rows), "failed_sequence": None}

