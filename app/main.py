"""FastAPI entrypoint for the ReviveRoute workflow service."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, status

from app.database import CaseConflictError, CaseNotFoundError, InvalidTransitionError, RecoveryRepository
from app.decision_engine import DecisionEngine, RecoveryCase
from app.schemas import FailedPaymentRequest, TransitionRequest

DEFAULT_DATABASE_PATH = Path(__file__).resolve().parents[1] / "data" / "reviveroute.db"


def create_app(database_path: str | Path = DEFAULT_DATABASE_PATH, engine: DecisionEngine | None = None) -> FastAPI:
    repository = RecoveryRepository(database_path)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        repository.initialize()
        yield

    application = FastAPI(
        title="ReviveRoute API",
        version="0.4.0",
        description="Bounded failed-payment recovery workflow prototype",
        lifespan=lifespan,
    )
    application.state.repository = repository
    application.state.engine = engine

    def get_engine() -> DecisionEngine:
        if application.state.engine is None:
            application.state.engine = DecisionEngine()
        return application.state.engine

    @application.get("/health")
    def health() -> dict:
        return {"status": "ok", "service": "ReviveRoute", "version": application.version}

    @application.post("/api/v1/recovery-cases", status_code=status.HTTP_201_CREATED)
    def create_recovery_case(payload: FailedPaymentRequest):
        request = payload.model_dump(mode="json")
        case = RecoveryCase(
            **payload.model_dump(),
            case_created_at_utc=payload.timestamp_utc,
        )
        decision = get_engine().decide(case)
        try:
            stored, duplicate = repository.create_case(request, decision)
        except CaseConflictError:
            raise HTTPException(status_code=409, detail="event_id already exists with a different payload")
        return {"duplicate": duplicate, "case": stored}

    @application.get("/api/v1/recovery-cases")
    def list_recovery_cases(limit: int = Query(default=50, ge=1, le=200)):
        return {"cases": repository.list_cases(limit)}

    @application.get("/api/v1/recovery-cases/{event_id}")
    def get_recovery_case(event_id: str):
        try:
            return repository.get_case(event_id)
        except CaseNotFoundError:
            raise HTTPException(status_code=404, detail="recovery case not found")

    @application.post("/api/v1/recovery-cases/{event_id}/transitions")
    def transition_recovery_case(event_id: str, payload: TransitionRequest):
        try:
            return repository.transition(event_id, payload.to_status, payload.reason, payload.metadata)
        except CaseNotFoundError:
            raise HTTPException(status_code=404, detail="recovery case not found")
        except InvalidTransitionError as error:
            raise HTTPException(status_code=409, detail=f"invalid workflow transition: {error}")

    @application.get("/api/v1/summary")
    def recovery_summary():
        return repository.summary()

    @application.get("/api/v1/audit/verify")
    def verify_audit():
        return repository.verify_audit_chain()

    return application


app = create_app()

