"""Continuously runs due bounded actions while the API process is alive."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from app.executor import SimulatedExecutor


class RecoveryAgentWorker:
    def __init__(self, executor: SimulatedExecutor, interval_seconds: float = 10.0) -> None:
        self.executor = executor
        self.interval_seconds = max(0.05, interval_seconds)
        self.task: asyncio.Task | None = None
        self.running = False
        self.cycles = 0
        self.executions = 0
        self.last_run_utc: str | None = None
        self.last_error: str | None = None

    async def start(self) -> None:
        if self.task and not self.task.done():
            return
        self.running = True
        self.task = asyncio.create_task(self._loop(), name="reviveroute-bounded-agent")

    async def stop(self) -> None:
        self.running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass

    async def run_once(self) -> list[dict]:
        try:
            results = await asyncio.to_thread(self.executor.run_due, None, 50)
            self.executions += len(results)
            self.last_error = None
            return results
        except Exception as error:  # keep the bounded loop alive and visible
            self.last_error = f"{type(error).__name__}: {error}"
            return []
        finally:
            self.cycles += 1
            self.last_run_utc = datetime.now(timezone.utc).isoformat()

    async def _loop(self) -> None:
        while self.running:
            await self.run_once()
            await asyncio.sleep(self.interval_seconds)

    def status(self) -> dict:
        persisted = self.executor.repository.execution_summary()
        return {
            "agent_mode": "AUTONOMOUS_SIMULATED",
            "running": self.running,
            "poll_interval_seconds": self.interval_seconds,
            "cycles_completed": self.cycles,
            "actions_executed": self.executions,
            **persisted,
            "last_run_utc": self.last_run_utc,
            "last_error": self.last_error,
            "customer_contacted": False,
            "payment_api_called": False,
        }
