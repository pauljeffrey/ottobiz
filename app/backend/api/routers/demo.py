"""
Demo payment-simulation endpoints — optional, public-demo-only.

Lets a demo visitor register their own bank account so it can be shown in
place of the vendor's real bank details (see backend/payments/demo_override.py
for why). Delete this file and its `include_router` line in main.py to remove
this feature entirely for a production deployment.
"""
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.payments.demo_override import (
    DEMO_PAYMENT_OVERRIDE_ENABLED,
    clear_override,
    get_override,
    set_override,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/demo", tags=["demo"])


class DemoPaymentAccountRequest(BaseModel):
    user_id: str
    bank_name: str
    bank_account_number: str
    bank_account_name: str


class DemoUserRequest(BaseModel):
    user_id: str


@router.get("/payment-account/{user_id}")
async def get_payment_account(user_id: str):
    if not DEMO_PAYMENT_OVERRIDE_ENABLED:
        return {"enabled": False, "account": None}
    account = await get_override(user_id)
    return {"enabled": True, "account": account}


@router.post("/payment-account")
async def upsert_payment_account(request: DemoPaymentAccountRequest):
    if not DEMO_PAYMENT_OVERRIDE_ENABLED:
        raise HTTPException(status_code=404, detail="Demo payment override is disabled.")
    if not request.bank_name.strip() or not request.bank_account_number.strip() or not request.bank_account_name.strip():
        raise HTTPException(status_code=422, detail="Bank name, account number, and account name are all required.")
    try:
        await set_override(
            request.user_id, request.bank_name, request.bank_account_number, request.bank_account_name
        )
    except Exception:
        logger.exception("demo_payment_account_save_failed | user_id=%s", request.user_id)
        raise HTTPException(status_code=500, detail="Could not save payment account.")
    return {"success": True}


@router.post("/payment-account/clear")
async def clear_payment_account(request: DemoUserRequest):
    await clear_override(request.user_id)
    return {"success": True}
