"""
Inventory Management API endpoints
"""
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from backend.db.db_utils import get_inventory as db_get_inventory
from backend.db.db_utils import get_low_stock_products, get_products, update_product_stock_for_business
from backend.db.cache_utils import get_inventory_activity

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/inventory", tags=["inventory"])


class InventoryRequest(BaseModel):
    """Inventory request"""
    business_id: str
    api_key: Optional[str] = None


class InventoryUpdateRequest(BaseModel):
    """Inventory update request"""
    business_id: str
    product_id: str
    quantity: int
    reorder_level: Optional[int] = None


def _summarize(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    total = len(rows)
    out_stock = sum(1 for r in rows if int(r.get("stock_quantity") or 0) <= 0)
    low = sum(
        1
        for r in rows
        if 0 < int(r.get("stock_quantity") or 0) <= int(r.get("reorder_level") or 10)
    )
    return {
        "total_items": total,
        "in_stock": total - out_stock,
        "low_stock_count": low,
        "out_of_stock_count": out_stock,
        "needs_attention": low + out_stock,
    }


@router.get("/top-products/{business_id}")
async def get_top_products_for_business(
    business_id: str,
    limit: int = 15,
):
    """
    Latest active catalog rows for a vendor (default 15). For simulation UI / stock visibility.
    """
    lim = max(1, min(int(limit), 50))
    try:
        rows = await get_products(business_id=business_id, limit=lim)
    except Exception:
        logger.exception("top_products fetch failed | business_id=%s", business_id)
        raise HTTPException(status_code=500, detail="Failed to retrieve products.")
    products: List[Dict[str, Any]] = []
    for r in rows:
        pid = r.get("id")
        products.append(
            {
                "id": str(pid) if pid is not None else "",
                "name": r.get("name"),
                "price": float(r.get("price") or 0),
                "stock_quantity": int(r.get("stock_quantity") or 0),
                "currency": r.get("currency") or "NGN",
                "category": r.get("category"),
            }
        )
    return JSONResponse(
        content={
            "business_id": business_id,
            "count": len(products),
            "products": products,
        },
        headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
    )


@router.get("/activity/{business_id}")
async def get_inventory_activity_feed(
    business_id: str,
    limit: int = 40,
):
    """
    Recent catalog mutations (stock/price/add) from agents, stored in Redis.
    For simulation / transparency UI only.
    """
    lim = max(1, min(int(limit), 100))
    events = await get_inventory_activity(business_id, lim)
    return JSONResponse(
        content={"business_id": business_id, "count": len(events), "events": events},
        headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
    )


@router.post("/")
async def get_inventory(request: InventoryRequest):
    """Get inventory for a business."""
    try:
        rows = await db_get_inventory(request.business_id)
        low_rows = await get_low_stock_products(request.business_id, threshold=10)
        summary = _summarize(rows)
        alerts: List[str] = []
        if summary["out_of_stock_count"]:
            alerts.append(f"⚠️ {summary['out_of_stock_count']} product(s) out of stock")
        if summary["low_stock_count"]:
            alerts.append(f"⚠️ {summary['low_stock_count']} product(s) low stock")
        if not alerts:
            alerts.append("✅ All products in stock")
        return {
            "business_id": request.business_id,
            "inventory": rows,
            "low_stock_items": low_rows,
            "out_of_stock_items": [
                r for r in rows if int(r.get("stock_quantity") or 0) <= 0
            ],
            "summary": summary,
            "alerts": alerts,
        }
    except Exception:
        logger.exception("inventory fetch failed")
        raise HTTPException(status_code=500, detail="Failed to retrieve inventory.")


@router.post("/update")
async def update_inventory(request: InventoryUpdateRequest):
    """Update a product's stock quantity (scoped to the requesting business)."""
    row = await update_product_stock_for_business(
        request.business_id, request.product_id, request.quantity
    )
    if not row:
        raise HTTPException(
            status_code=404, detail="Product not found for this business."
        )
    return {
        "success": True,
        "product_id": str(row.get("id")),
        "quantity": row.get("stock_quantity"),
    }

