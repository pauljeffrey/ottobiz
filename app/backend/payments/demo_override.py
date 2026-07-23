"""
Demo-only payment simulation layer.

A public demo shouldn't show real vendor bank details to random visitors, or
let them generate a real Paystack checkout. This lets a demo visitor register
THEIR OWN bank account details for their persona; product_agent then shows
that account instead of the vendor's real one, and skips the real Paystack
link, so "paying" never sends money to anyone but the visitor themselves.

This is intentionally isolated from the rest of the codebase: nothing outside
this file and its two call sites in chatbot/agents/product_agent.py knows it
exists. To remove for a production deployment: delete this file, delete
api/routers/demo.py, remove its `include_router` line in main.py, and remove
the three `demo_override` calls in product_agent.py (each is a no-op / falls
back to real vendor data when this module is absent).

Controlled by DEMO_PAYMENT_OVERRIDE_ENABLED (default: on). Set to "false" to
hard-disable without touching code.
"""
import asyncio
import os
from typing import Dict, Optional

from backend.db.cache_utils import redis_conn

DEMO_PAYMENT_OVERRIDE_ENABLED = os.getenv("DEMO_PAYMENT_OVERRIDE_ENABLED", "true").lower() == "true"

_KEY_PREFIX = "demo_payment_override:"


def _key(user_id: str) -> str:
    return f"{_KEY_PREFIX}{user_id}"


async def get_override(user_id: str) -> Optional[Dict[str, str]]:
    """{bank_name, bank_account_number, bank_account_name} for this demo persona, or None."""
    if not DEMO_PAYMENT_OVERRIDE_ENABLED or not (user_id or "").strip():
        return None
    try:
        data = await asyncio.to_thread(redis_conn.get, _key(user_id))
        return data or None
    except Exception:
        return None


async def set_override(
    user_id: str, bank_name: str, bank_account_number: str, bank_account_name: str
) -> None:
    if not (user_id or "").strip():
        raise ValueError("user_id is required")
    await asyncio.to_thread(
        redis_conn.set,
        _key(user_id),
        {
            "bank_name": bank_name.strip(),
            "bank_account_number": bank_account_number.strip(),
            "bank_account_name": bank_account_name.strip(),
        },
    )


async def clear_override(user_id: str) -> None:
    if not (user_id or "").strip():
        return
    await asyncio.to_thread(redis_conn.delete, _key(user_id))
