"""Razorpay webhook verification and deterministic payload mapping."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timezone
from typing import Any

from app.decision_engine import RecoveryCase


class WebhookPayloadError(ValueError):
    """A signed webhook does not contain the fields required for processing."""


def webhook_signature(raw_body: bytes, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()


def verify_webhook_signature(raw_body: bytes, supplied_signature: str | None, secret: str) -> bool:
    if not supplied_signature or not secret:
        return False
    expected = webhook_signature(raw_body, secret)
    return hmac.compare_digest(expected, supplied_signature.strip())


def parse_webhook(raw_body: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(raw_body)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise WebhookPayloadError("webhook body must be valid UTF-8 JSON") from error
    if not isinstance(payload, dict) or not isinstance(payload.get("event"), str):
        raise WebhookPayloadError("webhook event name is required")
    return payload


def payment_entity(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        entity = payload["payload"]["payment"]["entity"]
    except (KeyError, TypeError) as error:
        raise WebhookPayloadError("payload.payment.entity is required") from error
    if not isinstance(entity, dict):
        raise WebhookPayloadError("payload.payment.entity must be an object")
    return entity


def normalize_method(payment: dict[str, Any]) -> str:
    method = str(payment.get("method") or "").lower()
    if method == "card":
        card = payment.get("card") or {}
        return "debit_card" if str(card.get("type", "")).lower() == "debit" else "credit_card"
    mapping = {"upi": "upi", "netbanking": "net_banking", "wallet": "wallet"}
    if method not in mapping:
        raise WebhookPayloadError(f"unsupported payment method: {method or 'missing'}")
    return mapping[method]


def normalize_failure_reason(payment: dict[str, Any]) -> str:
    reason = str(payment.get("error_reason") or "").lower()
    code = str(payment.get("error_code") or "").lower()
    description = str(payment.get("error_description") or "").lower()
    combined = " ".join((reason, code, description))
    if "insufficient" in combined or "low_balance" in combined:
        return "insufficient_funds"
    if "limit" in combined or "amount_exceeds" in combined:
        return "bank_limit_exceeded"
    if "risk" in combined or "fraud" in combined:
        return "risk_declined"
    if "blocked" in combined or "card_declined" in combined or "expired_card" in combined:
        return "card_blocked"
    return "temporary_network_issue"


def failed_payment_to_case(
    payload: dict[str, Any],
    delivery_id: str,
    customer_features: dict[str, Any] | None = None,
) -> RecoveryCase:
    if payload.get("event") != "payment.failed":
        raise WebhookPayloadError("expected payment.failed event")
    payment = payment_entity(payload)
    required = ("id", "amount", "created_at")
    missing = [name for name in required if payment.get(name) is None]
    if missing:
        raise WebhookPayloadError(f"payment fields required: {', '.join(missing)}")
    try:
        amount_inr = int(payment["amount"]) / 100.0
        timestamp = datetime.fromtimestamp(int(payment["created_at"]), tz=timezone.utc)
    except (TypeError, ValueError, OSError) as error:
        raise WebhookPayloadError("payment amount or created_at is invalid") from error
    if amount_inr <= 0:
        raise WebhookPayloadError("payment amount must be positive")
    if str(payment.get("currency") or "INR").upper() != "INR":
        raise WebhookPayloadError("only INR payments are supported by this prototype")

    features = {
        "customer_tenure_days": 0.0,
        "prior_successes": 0,
        "prior_failures": 0,
        "prior_recoveries": 0,
        "contacts_last_7_days": 0,
        "recent_method_failure_rate": 0.0,
        "degradation_flag": 0,
    }
    features.update(customer_features or {})
    customer_id = payment.get("customer_id") or (payment.get("notes") or {}).get("customer_id") or f"anonymous:{payment['id']}"
    return RecoveryCase(
        event_id=delivery_id,
        customer_id=str(customer_id),
        timestamp_utc=timestamp,
        case_created_at_utc=timestamp,
        amount_inr=amount_inr,
        payment_method=normalize_method(payment),
        failure_reason=normalize_failure_reason(payment),
        **features,
    )


def payment_link_outcome(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("event") != "payment_link.paid":
        raise WebhookPayloadError("expected payment_link.paid event")
    payment = payment_entity(payload)
    try:
        link = payload["payload"]["payment_link"]["entity"]
    except (KeyError, TypeError) as error:
        raise WebhookPayloadError("payload.payment_link.entity is required") from error
    reference_id = link.get("reference_id")
    if not reference_id or payment.get("id") is None or payment.get("amount") is None:
        raise WebhookPayloadError("payment link reference_id, payment id and amount are required")
    if str(payment.get("currency") or "INR").upper() != "INR":
        raise WebhookPayloadError("only INR payments are supported by this prototype")
    return {
        "reference_id": str(reference_id),
        "payment_id": str(payment["id"]),
        "amount_inr": int(payment["amount"]) / 100.0,
    }
