"""
Supply Chain API endpoints
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from backend.db.db_utils import get_orders_by_business

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/supply-chain", tags=["supply_chain"])

OVERDUE_AFTER_DAYS = 3


class SupplyChainRequest(BaseModel):
    """Supply chain request"""
    business_id: str
    api_key: Optional[str] = None


def _serialize_order(o: Dict[str, Any]) -> Dict[str, Any]:
    created = o.get("created_at")
    return {
        "order_id": str(o.get("id", "")),
        "order_number": o.get("order_number"),
        "status": o.get("status"),
        "product_name": o.get("product_name"),
        "total_amount": float(o.get("total_amount") or 0),
        "created_at": created.isoformat() if hasattr(created, "isoformat") else created,
    }


@router.post("/")
async def get_supply_chain(request: SupplyChainRequest):
    """Real order-pipeline aggregates for a vendor (pending/delivered/overdue)."""
    try:
        orders = await get_orders_by_business(request.business_id, limit=200)
    except Exception:
        logger.exception("supply_chain fetch failed | business_id=%s", request.business_id)
        raise HTTPException(status_code=500, detail="Failed to retrieve supply chain data.")

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=OVERDUE_AFTER_DAYS)

    pending_items: List[Dict[str, Any]] = []
    delivered_items: List[Dict[str, Any]] = []
    overdue_items: List[Dict[str, Any]] = []

    for o in orders:
        status = (o.get("status") or "").lower()
        created = o.get("created_at")
        if status == "delivered":
            delivered_items.append(_serialize_order(o))
            continue
        if status == "cancelled":
            continue
        is_overdue = False
        if isinstance(created, datetime):
            created_ts = created if created.tzinfo else created.replace(tzinfo=timezone.utc)
            is_overdue = created_ts < cutoff
        if is_overdue:
            overdue_items.append(_serialize_order(o))
        else:
            pending_items.append(_serialize_order(o))

    total = len(orders)
    delivered = len(delivered_items)
    pending = len(pending_items)
    overdue = len(overdue_items)
    completion_rate = round((delivered / total) * 100, 1) if total else 0

    alerts: List[str] = []
    if overdue:
        alerts.append(f"⚠️ {overdue} order(s) overdue (pending > {OVERDUE_AFTER_DAYS} days)")
    if pending:
        alerts.append(f"📦 {pending} order(s) in progress")
    if not alerts:
        alerts.append("✅ All orders delivered")

    return JSONResponse(
        content={
            "business_id": request.business_id,
            "supply_chain": [_serialize_order(o) for o in orders],
            "summary": {
                "total_orders": total,
                "pending": pending,
                "delivered": delivered,
                "overdue": overdue,
                "completion_rate": completion_rate,
            },
            "pending_items": pending_items,
            "delivered_items": delivered_items,
            "overdue_items": overdue_items,
            "delivery_status": {
                "on_time": pending,
                "overdue": overdue,
                "pending": pending + overdue,
            },
            "alerts": alerts,
        },
        headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
    )
