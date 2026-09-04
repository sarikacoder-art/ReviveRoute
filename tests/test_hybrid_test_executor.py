"""Safety boundary tests for autonomous Razorpay Test Mode execution."""

from datetime import datetime, timedelta, timezone

from app.database import RecoveryRepository
from app.decision_engine import CandidateScore, RecoveryDecision
from app.executor import HybridTestExecutor


class FakeRazorpayTestClient:
    def __init__(self):
        self.calls = []

    def create_payment_link(self, *, amount_inr, reference_id, description):
        self.calls.append((amount_inr, reference_id, description))
        return {"provider": "RAZORPAY_TEST", "payment_link_id": f"plink_{reference_id}", "short_url": "https://rzp.io/i/test-only", "status": "created", "reference_id": reference_id, "amount_inr": amount_inr}


def add_due_case(repository, event_id, source_payment_id=None):
    now = datetime.now(timezone.utc)
    request = {"event_id": event_id, "source_payment_id": source_payment_id, "customer_id": "fictional", "timestamp_utc": now.isoformat(), "amount_inr": 499.0, "payment_method": "upi", "failure_reason": "temporary_network_issue"}
    score = CandidateScore("LINK_NOW", .5, 249.5, 3, 0, 246.5, True)
    decision = RecoveryDecision(event_id, "LINK_NOW", "SCHEDULED", (now - timedelta(seconds=1)).isoformat(), (), "test", .5, 246.5, (score,))
    repository.create_case(request, decision)


def test_public_manual_case_stays_simulated(tmp_path):
    repository = RecoveryRepository(tmp_path / "manual.db")
    repository.initialize()
    add_due_case(repository, "manual_case")
    client = FakeRazorpayTestClient()
    result = HybridTestExecutor(repository, client).run_due()
    assert result[0]["mode"] == "SIMULATED"
    assert client.calls == []


def test_signed_razorpay_case_creates_test_link_and_is_audited(tmp_path):
    repository = RecoveryRepository(tmp_path / "signed.db")
    repository.initialize()
    add_due_case(repository, "signed_case", source_payment_id="pay_test_123")
    client = FakeRazorpayTestClient()
    result = HybridTestExecutor(repository, client).run_due()
    assert result[0]["mode"] == "RAZORPAY_TEST"
    assert result[0]["payment_api_called"] is True
    assert len(client.calls) == 1
    case = repository.get_case("signed_case")
    assert case["workflow_status"] == "ACTION_SENT"
    assert any(event["event_type"] == "RAZORPAY_TEST_LINK_CREATED" for event in case["events"])
    assert repository.verify_audit_chain()["valid"] is True
