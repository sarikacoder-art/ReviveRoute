"""Append-only, tamper-evident JSONL audit trail for recovery decisions."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

GENESIS_HASH = "0" * 64


def _canonical(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


@dataclass(frozen=True)
class AuditEntry:
    sequence: int
    recorded_at_utc: str
    event_type: str
    event_id: str
    payload: dict[str, Any]
    previous_hash: str
    entry_hash: str


class AuditTrail:
    """In-memory hash chain that can be exported as JSON Lines."""

    def __init__(self, entries: Iterable[AuditEntry] | None = None) -> None:
        self.entries = list(entries or [])

    def append(
        self,
        event_type: str,
        event_id: str,
        payload: dict[str, Any],
        recorded_at: datetime | None = None,
    ) -> AuditEntry:
        timestamp = (recorded_at or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
        previous_hash = self.entries[-1].entry_hash if self.entries else GENESIS_HASH
        unsigned = {
            "sequence": len(self.entries) + 1,
            "recorded_at_utc": timestamp,
            "event_type": event_type,
            "event_id": str(event_id),
            "payload": payload,
            "previous_hash": previous_hash,
        }
        entry_hash = hashlib.sha256(_canonical(unsigned).encode("utf-8")).hexdigest()
        entry = AuditEntry(**unsigned, entry_hash=entry_hash)
        self.entries.append(entry)
        return entry

    def verify(self) -> bool:
        previous_hash = GENESIS_HASH
        for expected_sequence, entry in enumerate(self.entries, start=1):
            unsigned = asdict(entry)
            claimed_hash = unsigned.pop("entry_hash")
            if entry.sequence != expected_sequence or entry.previous_hash != previous_hash:
                return False
            if hashlib.sha256(_canonical(unsigned).encode("utf-8")).hexdigest() != claimed_hash:
                return False
            previous_hash = claimed_hash
        return True

    def write_jsonl(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        text = "\n".join(_canonical(asdict(entry)) for entry in self.entries)
        path.write_text(text + ("\n" if text else ""), encoding="utf-8")

    @classmethod
    def read_jsonl(cls, path: Path) -> "AuditTrail":
        if not path.exists():
            return cls()
        entries = [AuditEntry(**json.loads(line)) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        return cls(entries)

