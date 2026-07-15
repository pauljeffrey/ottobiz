"""
Analytics API endpoints — asyncpg via db_utils (aligned with the rest of the app).
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.db.db_utils import get_business_analytics, get_orders_by_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/analytics", tags=["analytics"])


class AnalyticsRequest(BaseModel):
    user_id: Optional[str] = None
    business_id: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    api_key: Optional[str] = None


def _serialize_order(row: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(row)
    for k, v in list(out.items()):
        if hasattr(v, "isoformat"):
            out[k] = v.isoformat()
        elif hasattr(v, "__str__") and k in ("id", "user_id", "business_id", "logistic_id"):
            out[k] = str(v) if v is not None else None
    return out


def _business_insights(data: Dict[str, Any]) -> List[str]:
    orders = data.get("orders") or {}
    sales = data.get("sales") or {}
    top_products = data.get("top_products") or []

    total_orders = int(orders.get("total_orders") or 0)
    if total_orders == 0:
        return ["No orders yet — insights will appear once customers start ordering."]

    insights: List[str] = []
    delivered = int(orders.get("delivered_orders") or 0)
    pending = int(orders.get("pending_orders") or 0)
    completion_rate = round((delivered / total_orders) * 100, 1) if total_orders else 0
    insights.append(f"{completion_rate}% of orders delivered ({delivered}/{total_orders})")
    if pending:
        insights.append(f"{pending} order(s) still pending fulfillment")

    avg_txn = float(sales.get("average_transaction_value") or 0)
    if sales.get("total_transactions"):
        insights.append(f"Average transaction value: {avg_txn:.2f}")

    top = next((p for p in top_products if float(p.get("revenue") or 0) > 0), None)
    if top:
        insights.append(
            f"Top product: {top.get('name')} — {top.get('order_count')} order(s), "
            f"{float(top.get('revenue') or 0):.2f} revenue"
        )
    return insights


@router.post("/business")
async def business_analytics(request: AnalyticsRequest):
    if not request.business_id:
        raise HTTPException(status_code=422, detail="business_id is required.")
    try:
        data = await get_business_analytics(
            request.business_id,
            start_date=request.start_date,
            end_date=request.end_date,
        )
        data["insights"] = _business_insights(data)
        return data
    except Exception as e:
        logger.exception("business_analytics failed")
        raise HTTPException(status_code=500, detail="Failed to retrieve business analytics.")


@router.post("/user")
async def user_analytics(request: AnalyticsRequest):
    if not request.user_id:
        raise HTTPException(status_code=422, detail="user_id is required.")
    try:
        orders: List[Dict[str, Any]] = await get_orders_by_user(
            request.user_id, limit=100
        )
        total_spent = sum(float(o.get("total_amount") or 0) for o in orders)
        purchase_count = len(orders)
        avg_order_value = total_spent / purchase_count if purchase_count > 0 else 0.0

        spending_by_month: Dict[str, float] = {}
        spending_by_category: Dict[str, float] = {}
        for order in orders:
            created = order.get("created_at")
            if created:
                if isinstance(created, datetime):
                    mk = created.strftime("%Y-%m")
                else:
                    mk = str(created)[:7]
                spending_by_month[mk] = spending_by_month.get(mk, 0) + float(
                    order.get("total_amount") or 0
                )
            meta = order.get("metadata")
            if isinstance(meta, dict):
                cat = meta.get("category", "uncategorized")
                spending_by_category[cat] = spending_by_category.get(
                    cat, 0
                ) + float(order.get("total_amount") or 0)

        recent_purchases = [
            {
                "order_id": str(o.get("id", "")),
                "order_number": o.get("order_number"),
                "amount": float(o.get("total_amount") or 0),
                "status": o.get("status"),
                "product_name": o.get("product_name"),
                "product_attributes": o.get("product_attributes")
                if isinstance(o.get("product_attributes"), dict)
                else {},
                "date": o["created_at"].isoformat()
                if isinstance(o.get("created_at"), datetime)
                else str(o.get("created_at") or ""),
            }
            for o in orders[:5]
        ]

        spending_pattern = "moderate"
        if purchase_count > 0:
            if avg_order_value > 500:
                spending_pattern = "high_value"
            elif avg_order_value < 100:
                spending_pattern = "budget_conscious"
            if purchase_count > 10:
                spending_pattern += "_frequent"
            elif purchase_count < 3:
                spending_pattern += "_occasional"

        recommendations: List[str] = []
        if purchase_count == 0:
            recommendations = [
                "Start exploring our product catalog",
                "Check out our featured products",
                "Sign up for exclusive deals",
            ]
        else:
            if spending_by_category:
                top_cat = max(spending_by_category.items(), key=lambda x: x[1])[0]
                recommendations.append(
                    f"Based on your preferences, you might like more {top_cat} products"
                )
            if avg_order_value < 200:
                recommendations.append("Consider bundling products for better value")
            if purchase_count > 5:
                recommendations.append(
                    "You're a valued customer! Check out our loyalty rewards"
                )
            recommendations.append("Browse our new arrivals and trending products")

        favorite = (
            max(spending_by_category.items(), key=lambda x: x[1])[0]
            if spending_by_category
            else None
        )
        most_active = (
            max(spending_by_month.items(), key=lambda x: x[1])[0]
            if spending_by_month
            else None
        )

        return {
            "user_id": request.user_id,
            "spending_habits": {
                "total_spent": float(total_spent),
                "purchase_count": purchase_count,
                "average_order_value": float(avg_order_value),
                "spending_pattern": spending_pattern,
                "spending_by_month": spending_by_month,
                "spending_by_category": spending_by_category,
                "favorite_category": favorite,
            },
            "recent_purchases": recent_purchases,
            "orders_raw_sample": [_serialize_order(o) for o in orders[:3]],
            "recommendations": recommendations,
            "insights": [
                f"Average order value: ${avg_order_value:.2f}",
                f"Total purchases: {purchase_count}",
                f"Most active month: {most_active or 'N/A'}",
            ],
        }
    except Exception:
        logger.exception("user_analytics failed")
        raise HTTPException(status_code=500, detail="Failed to retrieve user analytics.")
