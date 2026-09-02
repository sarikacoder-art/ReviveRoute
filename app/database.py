"""SQLite persistence and workflow invariants for ReviveRoute."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
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
                """
            )
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
                   (event_id, customer_id, payload_fingerprint, request_json, amount_inr,
                    selected_action, workflow_status, execute_after_utc, reason_codes_json,
                    explanation, selected_probability, expected_net_value, created_at_utc, updated_at_utc)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    event_id, str(request["customer_id"]), fingerprint, canonical_json(request),
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
                """SELECT event_id, customer_id, amount_inr, selected_action, workflow_status,
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
        }

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

