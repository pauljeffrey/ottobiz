"""
Paystack REST helpers (per-vendor secret keys).
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)

PAYSTACK_REF_REDIS_TTL = 7 * 24 * 3600


async def persist_paystack_reference(
    reference: str,
    user_id: str,
    business_id: str,
    product_id: Optional[str],
    amount_major: float,
) -> None:
    """So webhooks can resolve business_id/user_id if Paystack metadata is missing."""
    try:
        from backend.db.cache_utils import redis_conn

        await asyncio.to_thread(
            redis_conn._client.setex,
            f"paystack_ref:{reference}",
            PAYSTACK_REF_REDIS_TTL,
            json.dumps(
                {
                    "user_id": str(user_id),
                    "business_id": str(business_id),
                    "product_id": str(product_id or ""),
                    "amount_major": float(amount_major),
                }
            ),
        )
    except Exception:
        logger.exception("paystack_ref_redis_set_failed")

PAYSTACK_API_BASE = "https://api.paystack.co"


def amount_to_kobo(amount_major: float) -> int:
    """NGN: major units to kobo (smallest currency unit)."""
    return max(1, int(round(float(amount_major) * 100)))


def paystack_subunit_to_major(amount_subunit: int) -> float:
    """Paystack `amount` (initialize, webhook, verify): integer in the currency's smallest unit → major units (÷100)."""
    return round(int(amount_subunit) / 100.0, 2)


def kobo_to_major(amount_kobo: int) -> float:
    """Back-compat alias; Paystack uses the same subunit scaling for supported currencies—not NGN-only."""
    return paystack_subunit_to_major(amount_kobo)


def verify_webhook_signature(raw_body: bytes, signature_header: str, secret_key: str) -> bool:
    if not signature_header or not secret_key:
        return False
    expected = hmac.new(
        secret_key.encode("utf-8"), raw_body, hashlib.sha512
    ).hexdigest()
    return hmac.compare_digest(expected, signature_header)


async def initialize_transaction(
    *,
    secret_key: str,
    email: str,
    amount_kobo: int,
    reference: str,
    callback_url: str,
    metadata: Dict[str, str],
    currency: str = "NGN",
) -> Dict[str, Any]:
    payload = {
        "email": email,
        "amount": amount_kobo,
        "reference": reference,
        "callback_url": callback_url,
        "currency": currency,
        "metadata": {k: str(v) for k, v in metadata.items() if v is not None},
    }
    try:
        async with httpx.AsyncClient() as client:
            r = await client.post(
                f"{PAYSTACK_API_BASE}/transaction/initialize",
                json=payload,
                headers={
                    "Authorization": f"Bearer {secret_key}",
                    "Content-Type": "application/json",
                },
                timeout=30.0,
            )
        data = r.json()
        if r.status_code >= 400 or not data.get("status"):
            msg = data.get("message", r.text or "initialize failed")
            logger.warning("paystack_initialize_failed | status=%s body=%s", r.status_code, msg)
            return {"ok": False, "message": msg}
        inner = data.get("data") or {}
        return {
            "ok": True,
            "authorization_url": inner.get("authorization_url"),
            "access_code": inner.get("access_code"),
            "reference": inner.get("reference") or reference,
        }
    except Exception as e:
        logger.exception("paystack_initialize_error")
        return {"ok": False, "message": str(e)}


async def verify_transaction(secret_key: str, reference: str) -> Dict[str, Any]:
    ref = reference.strip()
    if not ref:
        return {"ok": False, "verified": False, "message": "Empty reference"}
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"{PAYSTACK_API_BASE}/transaction/verify/{ref}",
                headers={"Authorization": f"Bearer {secret_key}"},
                timeout=30.0,
            )
        data = r.json()
        if r.status_code >= 400 or not data.get("status"):
            return {
                "ok": False,
                "verified": False,
                "message": data.get("message", "verify failed"),
            }
        inner = data.get("data") or {}
        paid = (inner.get("status") or "").lower() == "success"
        amount_kobo = int(inner.get("amount") or 0)
        return {
            "ok": True,
            "verified": paid,
            "amount_major": paystack_subunit_to_major(amount_kobo),
            "amount_kobo": amount_kobo,
            "currency": inner.get("currency"),
            "paid_at": inner.get("paid_at"),
            "message": "success" if paid else inner.get("gateway_response") or "not successful",
            "raw": inner,
        }
    except Exception as e:
        logger.exception("paystack_verify_error")
        return {"ok": False, "verified": False, "message": str(e)}
