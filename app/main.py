"""FastAPI entrypoint for the ReviveRoute workflow service."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import uuid

from fastapi import FastAPI, Header, HTTPException, Query, Request, status
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from app.database import CaseConflictError, CaseNotFoundError, InvalidTransitionError, RecoveryAttributionError, RecoveryRepository, WebhookConflictError
from app.agent_worker import RecoveryAgentWorker
from app.decision_engine import DecisionEngine, RecoveryCase
from app.demo import DemoFlow
from app.executor import SimulatedExecutor
from app.intake import IntakeError, csv_template, parse_csv_batch, sample_batch
from app.schemas import FailedPaymentRequest, PromiseToPayRequest, TransitionRequest
from app.webhooks import WebhookPayloadError, failed_payment_to_case, parse_webhook, payment_entity, payment_link_outcome, verify_webhook_signature

DEFAULT_DATABASE_PATH = Path(__file__).resolve().parents[1] / "data" / "reviveroute.db"
STATIC_DIR = Path(__file__).resolve().parents[1] / "static"


def create_app(database_path: str | Path = DEFAULT_DATABASE_PATH, engine: DecisionEngine | None = None, webhook_secret: str | None = None, agent_enabled: bool | None = None, agent_interval_seconds: float = 10.0) -> FastAPI:
    repository = RecoveryRepository(database_path)
    executor = SimulatedExecutor(repository)
    worker = RecoveryAgentWorker(executor, interval_seconds=agent_interval_seconds)
    should_run_agent = agent_enabled if agent_enabled is not None else os.getenv("REVIVEROUTE_AGENT_ENABLED", "true").lower() == "true"

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        repository.initialize()
        if should_run_agent:
            await worker.start()
        try:
            yield
        finally:
            await worker.stop()

    application = FastAPI(
        title="ReviveRoute API",
        version="0.8.0",
        description="Bounded failed-payment recovery workflow prototype",
        lifespan=lifespan,
    )
    application.state.repository = repository
    application.state.engine = engine
    application.state.webhook_secret = webhook_secret if webhook_secret is not None else os.getenv("RAZORPAY_WEBHOOK_SECRET")
    application.state.executor = executor
    application.state.agent_worker = worker

    def get_engine() -> DecisionEngine:
        if application.state.engine is None:
            application.state.engine = DecisionEngine()
        return application.state.engine

    @application.get("/health")
    def health() -> dict:
        return {"status": "ok", "service": "ReviveRoute", "version": application.version}

    @application.get("/", include_in_schema=False)
    def dashboard():
        return FileResponse(STATIC_DIR / "dashboard.html")

    @application.get("/dashboard", include_in_schema=False)
    def dashboard_alias():
        return FileResponse(STATIC_DIR / "dashboard.html")

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

    def store_intake_case(payload: FailedPaymentRequest) -> tuple[dict, bool]:
        request_payload = payload.model_dump(mode="json")
        case = RecoveryCase(**payload.model_dump(), case_created_at_utc=payload.timestamp_utc)
        return repository.create_case(request_payload, get_engine().decide(case))

    @application.get("/api/v1/intake/template.csv")
    def download_intake_template():
        return Response(csv_template(), media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="reviveroute-import-template.csv"'})

    @application.post("/api/v1/intake/csv")
    async def import_intake_csv(request: Request):
        try:
            payloads, validation_errors = parse_csv_batch(await request.body())
        except IntakeError as error:
            raise HTTPException(status_code=422, detail=str(error))
        created = 0
        duplicates = 0
        conflicts: list[dict[str, str]] = []
        for payload in payloads:
            try:
                _, duplicate = store_intake_case(payload)
                duplicates += int(duplicate)
                created += int(not duplicate)
            except CaseConflictError:
                conflicts.append({"event_id": payload.event_id, "error": "event_id conflicts with existing data"})
        return {"evidence_label": "merchant-supplied inputs; recovery values are model estimates until an outcome webhook is recorded", "rows_received": len(payloads) + len(validation_errors), "created": created, "duplicates": duplicates, "validation_errors": validation_errors, "conflicts": conflicts}

    @application.post("/api/v1/intake/sample-batch")
    def load_sample_batch(count: int = Query(default=25, ge=5, le=50)):
        cases = []
        for payload in sample_batch(count):
            stored, _ = store_intake_case(payload)
            cases.append(stored)
        return {"evidence_label": "synthetic sample inputs; no customer contacted and no recovered revenue implied", "created": len(cases), "event_ids": [case["event_id"] for case in cases], "summary": repository.summary()}

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

    @application.post("/api/v1/executor/run-due")
    def run_due_actions(limit: int = Query(default=50, ge=1, le=200)):
        executions = application.state.executor.run_due(limit=limit)
        return {"execution_mode": "SIMULATED", "customer_contacted": False, "payment_api_called": False, "executions": executions}

    @application.get("/api/v1/agent/status")
    def agent_status():
        return worker.status()

    @application.post("/api/v1/promises", status_code=status.HTTP_201_CREATED)
    def create_payment_promise(payload: PromiseToPayRequest):
        stored, duplicate = repository.create_promise(payload.model_dump(mode="json"))
        return {"duplicate": duplicate, "promise": stored}

    @application.get("/api/v1/promises")
    def list_payment_promises(limit: int = Query(default=100, ge=1, le=200)):
        return {"promises": repository.list_promises(limit), "summary": repository.promise_summary()}

    @application.post("/api/v1/promises/{promise_id}/mark-paid")
    def mark_payment_promise_paid(promise_id: str):
        try:
            return repository.mark_promise_paid(promise_id, datetime.now(timezone.utc).isoformat())
        except CaseNotFoundError:
            raise HTTPException(status_code=404, detail="payment promise not found")

    @application.post("/api/v1/promises/sample")
    def load_sample_promises():
        token = uuid.uuid4().hex[:8]
        now = datetime.now(timezone.utc).replace(microsecond=0)
        fixtures = [
            ("Aarav Traders", 18000, -4, None),
            ("BluePeak Studio", 42500, -1, None),
            ("Cedar Learning", 9600, 0, None),
            ("Dawn Retail", 27500, 2, None),
            ("Evergreen Foods", 14200, -2, -3),
            ("Futura Labs", 33000, -3, -1),
        ]
        created = []
        for index, (name, amount, due_offset, paid_offset) in enumerate(fixtures):
            payload = PromiseToPayRequest(
                promise_id=f"promise_demo_{token}_{index + 1}", customer_id=f"demo_org_{token}_{index + 1}",
                display_name=name, amount_inr=amount, promised_at_utc=now - timedelta(days=7),
                promised_due_utc=now + timedelta(days=due_offset), source="SYNTHETIC_DEMO",
            )
            item, _ = repository.create_promise(payload.model_dump(mode="json"))
            if paid_offset is not None:
                item = repository.mark_promise_paid(payload.promise_id, (now + timedelta(days=paid_offset)).isoformat())
            created.append(item)
        return {"evidence_label": "fictional promise-to-pay demonstration; no real customer data", "created": len(created), "summary": repository.promise_summary()}

    @application.post("/api/v1/demo/run")
    def run_complete_demo():
        try:
            return DemoFlow(repository, get_engine(), application.state.executor).run()
        except RuntimeError as error:
            raise HTTPException(status_code=500, detail=str(error))

    @application.post("/webhooks/razorpay")
    async def razorpay_webhook(
        request: Request,
        x_razorpay_signature: str | None = Header(default=None, alias="X-Razorpay-Signature"),
        x_razorpay_event_id: str | None = Header(default=None, alias="X-Razorpay-Event-Id"),
    ):
        secret = application.state.webhook_secret
        if not secret:
            raise HTTPException(status_code=503, detail="webhook secret is not configured")
        raw_body = await request.body()
        if not verify_webhook_signature(raw_body, x_razorpay_signature, secret):
            raise HTTPException(status_code=401, detail="invalid webhook signature")
        if not x_razorpay_event_id:
            raise HTTPException(status_code=400, detail="X-Razorpay-Event-Id header is required")
        try:
            webhook = parse_webhook(raw_body)
            duplicate_response = repository.register_webhook(x_razorpay_event_id, webhook["event"], raw_body)
            if duplicate_response is not None:
                return duplicate_response
            if webhook["event"] == "payment.failed":
                payment = payment_entity(webhook)
                customer_id = payment.get("customer_id") or (payment.get("notes") or {}).get("customer_id") or f"anonymous:{payment.get('id', 'unknown')}"
                event_time = datetime.fromtimestamp(int(payment["created_at"]), tz=timezone.utc)
                features = repository.customer_features(str(customer_id), event_time)
                case = failed_payment_to_case(webhook, x_razorpay_event_id, features)
                decision = get_engine().decide(case)
                case_request = {
                    "event_id": case.event_id, "source_payment_id": str(payment["id"]), "customer_id": case.customer_id,
                    "timestamp_utc": case.timestamp_utc.isoformat(), "amount_inr": case.amount_inr,
                    "payment_method": case.payment_method, "failure_reason": case.failure_reason,
                    "customer_tenure_days": case.customer_tenure_days, "prior_successes": case.prior_successes,
                    "prior_failures": case.prior_failures, "prior_recoveries": case.prior_recoveries,
                    "contacts_last_7_days": case.contacts_last_7_days,
                    "recent_method_failure_rate": case.recent_method_failure_rate,
                    "degradation_flag": case.degradation_flag, "automated_attempts": 0,
                    "opted_out": False, "already_recovered": False,
                }
                stored, _ = repository.create_case(case_request, decision)
                response = {"status": "processed", "event": webhook["event"], "duplicate": False, "case": stored}
            elif webhook["event"] == "payment_link.paid":
                outcome = payment_link_outcome(webhook)
                stored, duplicate = repository.record_recovery_outcome(webhook_delivery_id=x_razorpay_event_id, **outcome)
                response = {"status": "processed", "event": webhook["event"], "duplicate": duplicate, "outcome": stored}
            else:
                response = {"status": "ignored", "event": webhook["event"], "duplicate": False}
            repository.complete_webhook(x_razorpay_event_id, response)
            return JSONResponse(response, status_code=200)
        except WebhookConflictError:
            raise HTTPException(status_code=409, detail="webhook event ID was reused with different content")
        except CaseConflictError:
            raise HTTPException(status_code=409, detail="recovery case event ID conflicts with existing data")
        except RecoveryAttributionError as error:
            raise HTTPException(status_code=409, detail=str(error))
        except (WebhookPayloadError, KeyError, TypeError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error))

    application.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return application


app = create_app()

