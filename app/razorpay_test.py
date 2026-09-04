"""Credential-gated Razorpay test-mode payment-link adapter.

It is deliberately separate from the safe simulated executor. Nothing calls the
Razorpay network unless an operator explicitly configures test credentials and
invokes this client.
"""

from __future__ import annotations

import os
from typing import Any, Callable

import httpx


class RazorpayTestConfigurationError(RuntimeError):
    pass


class RazorpayTestClient:
    endpoint = "https://api.razorpay.com/v1/payment_links"

    def __init__(
        self,
        key_id: str,
        key_secret: str,
        post: Callable[..., Any] | None = None,
    ) -> None:
        if not key_id.startswith("rzp_test_"):
            raise RazorpayTestConfigurationError("only rzp_test_ credentials are accepted")
        if not key_secret:
            raise RazorpayTestConfigurationError("Razorpay test secret is missing")
        self.key_id = key_id
        self.key_secret = key_secret
        self._post = post

    @classmethod
    def from_environment(cls) -> "RazorpayTestClient":
        return cls(os.getenv("RAZORPAY_TEST_KEY_ID", ""), os.getenv("RAZORPAY_TEST_KEY_SECRET", ""))

    @classmethod
    def status(cls) -> dict[str, Any]:
        key_id = os.getenv("RAZORPAY_TEST_KEY_ID", "")
        secret = os.getenv("RAZORPAY_TEST_KEY_SECRET", "")
        enabled = os.getenv("RAZORPAY_TEST_MODE_ENABLED", "false").lower() == "true"
        configured = key_id.startswith("rzp_test_") and bool(secret)
        return {
            "mode": "RAZORPAY_TEST" if enabled and configured else "SIMULATED",
            "enabled": enabled,
            "configured": configured,
            "ready": enabled and configured,
            "scope": "SIGNED_RAZORPAY_WEBHOOK_CASES_ONLY",
            "live_credentials_accepted": False,
            "secret_exposed": False,
        }

    def create_payment_link(self, *, amount_inr: float, reference_id: str, description: str) -> dict[str, Any]:
        payload = {
            "amount": int(round(amount_inr * 100)),
            "currency": "INR",
            "reference_id": reference_id,
            "description": description[:255],
            "notify": {"sms": False, "email": False},
            "reminder_enable": False,
            "notes": {"reviveroute_mode": "TEST", "recovery_reference": reference_id},
        }
        if self._post:
            response = self._post(self.endpoint, auth=(self.key_id, self.key_secret), json=payload, timeout=10.0)
        else:
            response = httpx.post(self.endpoint, auth=(self.key_id, self.key_secret), json=payload, timeout=10.0)
        response.raise_for_status()
        body = response.json()
        return {
            "provider": "RAZORPAY_TEST",
            "payment_link_id": body["id"],
            "short_url": body["short_url"],
            "status": body.get("status", "created"),
            "reference_id": reference_id,
            "amount_inr": amount_inr,
        }
