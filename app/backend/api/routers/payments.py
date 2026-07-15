"""
Paystack: browser callback (customer redirect) and server webhook (authoritative success).
"""
import asyncio
import json
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

from backend.config import PAYSTACK_WEBHOOK_CONFIRMED_MAX
from backend.db.cache_utils import get_user_state, modify_user_state, redis_conn, user_state_lock
from backend.db.db_utils import get_business_info, record_paystack_webhook_event
from backend.payments.paystack_client import paystack_subunit_to_major, verify_webhook_signature

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/payments/paystack", tags=["payments"])


async def _resolve_business_id_for_webhook(
    body: Dict[str, Any], reference: str
) -> Optional[str]:
    data = body.get("data") or {}
    meta = data.get("metadata") or {}
    bid = meta.get("business_id")
    if bid:
        return str(bid)
    try:
        raw = await asyncio.to_thread(redis_conn._client.get, f"paystack_ref:{reference}")
        if raw:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            m = json.loads(raw)
            return str(m.get("business_id")) if m.get("business_id") else None
    except Exception:
        logger.exception("paystack_ref_redis_get_failed")
    return None


@router.get("/callback")
async def paystack_browser_callback(reference: str = "", trxref: str = ""):
    """
    Paystack redirects the customer's browser here after payment (callback_url).
    Query params typically include reference and trxref — same value.
    This does not replace the webhook; it only confirms to the human that they can return to chat.
    """
    ref = reference or trxref or ""
    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"/><title>Payment</title></head>
<body style="font-family:system-ui;max-width:520px;margin:2rem auto;padding:0 1rem">
<h1>Payment received</h1>
<p>If you paid in <strong>WhatsApp</strong> or another chat, you can return there now.</p>
<p>Your payment reference: <code>{ref or "—"}</code></p>
<p>If the assistant asks, send this reference so we can confirm your order.</p>
</body></html>"""
    return HTMLResponse(html)


@router.post("/webhook")
async def paystack_webhook(request: Request):
    """
    Paystack sends charge.success (and other events) here. Signature uses the vendor's secret key.
    Configure the same URL in each vendor's Paystack dashboard, or use one master account with splits later.
    """
    raw = await request.body()
    sig = request.headers.get("x-paystack-signature") or ""
    try:
        body = json.loads(raw.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return JSONResponse({"detail": "invalid json"}, status_code=400)

    event = body.get("event") or ""
    if event != "charge.success":
        return {"received": True, "ignored": event or "unknown"}

    data = body.get("data") or {}
    reference = data.get("reference") or ""
    if not reference:
        return JSONResponse({"detail": "missing reference"}, status_code=400)

    business_id = await _resolve_business_id_for_webhook(body, reference)
    if not business_id:
        logger.warning("paystack_webhook_no_business_id | ref=%s", reference)
        return JSONResponse({"detail": "cannot resolve business"}, status_code=400)

    biz = await get_business_info(business_id)
    secret = (biz or {}).get("paystack_secret_key") or ""
    if not secret or not verify_webhook_signature(raw, sig, secret):
        logger.warning("paystack_webhook_bad_signature | business_id=%s", business_id)
        return JSONResponse({"detail": "invalid signature"}, status_code=401)

    meta = data.get("metadata") or {}
    user_id = meta.get("user_id")
    if not user_id:
        try:
            raw_map = await asyncio.to_thread(redis_conn._client.get, f"paystack_ref:{reference}")
            if raw_map:
                if isinstance(raw_map, bytes):
                    raw_map = raw_map.decode("utf-8")
                m = json.loads(raw_map)
                user_id = m.get("user_id")
        except Exception:
            logger.exception("paystack_webhook_user_resolve_failed")

    if not user_id:
        logger.warning("paystack_webhook_no_user_id | ref=%s", reference)
        return JSONResponse({"detail": "missing user_id"}, status_code=400)

    vendor_id = str(business_id)
    amount_kobo = data.get("amount")
    currency = data.get("currency")
    ak = None
    if amount_kobo is not None:
        try:
            ak = int(amount_kobo)
        except (TypeError, ValueError):
            ak = None
    inserted = await record_paystack_webhook_event(
        reference=reference,
        user_id=str(user_id),
        business_id=vendor_id,
        amount_kobo=ak,
        currency=str(currency) if currency is not None else None,
    )
    logger.info(
        "paystack_webhook | ref=%s user_id=%s business_id=%s db_inserted=%s",
        reference,
        user_id,
        vendor_id,
        inserted,
    )
    try:
        async with user_state_lock(str(user_id), vendor_id):
            us = await get_user_state(str(user_id), vendor_id) or {}
            conf = us.setdefault("paystack_webhook_confirmed", [])
            if isinstance(conf, list):
                entry = {
                    "reference": reference,
                    "amount_kobo": data.get("amount"),
                    "amount_major": float(paystack_subunit_to_major(ak))
                    if ak is not None
                    else None,
                    "currency": currency,
                    "paid_at": data.get("paid_at"),
                }
                if not any(
                    isinstance(x, dict) and x.get("reference") == reference for x in conf
                ):
                    conf.append(entry)
                if len(conf) > PAYSTACK_WEBHOOK_CONFIRMED_MAX:
                    del conf[: len(conf) - PAYSTACK_WEBHOOK_CONFIRMED_MAX]
            await modify_user_state(str(user_id), vendor_id, us)
    except Exception:
        logger.exception("paystack_webhook_state_update_failed")

    return {"received": True, "reference": reference}
