"""Tests for the opt-in, test-mode-only Razorpay adapter."""

import pytest

from app.main import create_app
from app.razorpay_test import RazorpayTestClient, RazorpayTestConfigurationError
from fastapi.testclient import TestClient


class FakeResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {"id": "plink_test_123", "short_url": "https://rzp.io/i/test-only", "status": "created"}


def test_client_rejects_live_or_missing_credentials():
    with pytest.raises(RazorpayTestConfigurationError):
        RazorpayTestClient("rzp_live_forbidden", "secret")
    with pytest.raises(RazorpayTestConfigurationError):
        RazorpayTestClient("rzp_test_example", "")


def test_test_adapter_builds_non_notifying_payment_link_request():
    captured = {}

    def fake_post(url, **kwargs):
        captured.update({"url": url, **kwargs})
        return FakeResponse()

    result = RazorpayTestClient("rzp_test_example", "secret", post=fake_post).create_payment_link(
        amount_inr=2499, reference_id="rr_test_reference", description="Fictional recovery"
    )
    assert result["provider"] == "RAZORPAY_TEST"
    assert result["payment_link_id"] == "plink_test_123"
    assert captured["json"]["amount"] == 249900
    assert captured["json"]["notify"] == {"sms": False, "email": False}
    assert captured["json"]["reminder_enable"] is False


def test_integration_status_never_exposes_secret(tmp_path, monkeypatch):
    monkeypatch.setenv("RAZORPAY_TEST_KEY_ID", "rzp_test_example")
    monkeypatch.setenv("RAZORPAY_TEST_KEY_SECRET", "super-secret")
    monkeypatch.setenv("RAZORPAY_TEST_MODE_ENABLED", "true")
    with TestClient(create_app(tmp_path / "status.db", agent_enabled=False)) as api:
        payload = api.get("/api/v1/integrations/razorpay-test/status").json()
        assert payload == {"mode": "RAZORPAY_TEST", "enabled": True, "configured": True, "ready": True, "scope": "SIGNED_RAZORPAY_WEBHOOK_CASES_ONLY", "live_credentials_accepted": False, "secret_exposed": False}
        assert "super-secret" not in str(payload)
