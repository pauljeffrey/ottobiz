"""
Central Agent - Handles 2-3 way communication between customer, vendor, and logistics.
Creates orders on payment confirmation. Tracks finished tasks.
"""

import json
from typing import Any, Dict, List, Optional

import logfire
from pydantic import BaseModel, ConfigDict, Field

from backend.config import CENTRAL_AGENT_MODEL_NAME
from backend.logging_config import get_logger
from backend.db.cache_utils import get_user_state, modify_user_state, get_party_state, modify_party_state
from backend.chatbot.utils.agent_trace_stdout import agent_stdout
from backend.db.db_utils import (
    add_product as db_add_product,
    create_order as db_create_order,
    get_business_info,
    get_logistics_companies,
    mark_order_process_link_completed,
    pick_random_logistics_company_id,
    get_order_by_id,
    get_order_by_number,
    list_orders_for_customer_store,
    get_user_by_id,
    touch_order_process_link,
    update_order_status as db_update_order_status,
    update_product_price_for_business,
    update_product_stock_for_business,
    upsert_order_process_link,
)
from backend.struct import CentralAgentInput, Customer, EntityType, Logistics, Product, Vendor
from backend.whatsapp.utils import whatsapp, PHONE_NUMBER_ID
from pydantic_ai import RunContext
from typing import Literal

from .base_agent import BaseAgent
from .central_agent_utils import (
    CentralOutboundContext,
    apply_process_field_updates,
    build_central_agent_run_instructions,
    deliver_central_outbound,
    get_contact,
    get_or_create_process_for_event,
    get_role,
    merge_customer_chat_into_comm,
    polish_central_message_for_customer,
    _enum_label,
    _sender_role,
    _task_label,
)

logger = get_logger(__name__)

class CentralAgentResponse(BaseModel):
    """Structured response from central agent"""

    reasoning: str = Field(..., description="Think about what changed and what should be done next")
    next_step: str = Field(
        ..., description="Determine your next step and to whom it should be directed"
    )
    sender: EntityType = Field(description="Who is speaking this turn or who sent the last message. Mirror Customer / Vendor / Logistics if quoting or relaying in-thread")
    recipient: EntityType = Field(
        description="Who receives this message. Customer=relay product info/payment/delivery to customer. Vendor=ask vendor for confirmation. Logistics=coordinate shipping.",
    )
    message: str = Field(..., description="'short chat-style text for recipient(max ~3–4 sentences). Only facts and next steps—no essays, no internal monologue. Message to send")
    finished_tasks: List[str] = Field(description="Updated List of your finished tasks")


class CentralAgentDeps(BaseModel):
    """Per-turn deps; active_process is the mutable dict for this process_id in Redis."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    active_process: Dict[str, Any] = Field(default_factory=dict)
    process_id: str = ""
    customer: Optional[Customer] = None
    vendor: Optional[Vendor] = None
    product: Optional[Product] = None
    logistics: Optional[Logistics] = None
    customer_id: str = ""
    business_id: str = ""
    logistic_id: Optional[str] = None
    product_name: Optional[str] = None
    order_id: Optional[str] = None
    id: str = ""


def _slim_order_for_tool(row: Dict[str, Any]) -> Dict[str, Any]:
    keys = (
        "id", "user_id", "business_id", "order_number", "status", "total_amount",
        "tracking_number", "logistic_id", "delivery_address", "delivery_city", "delivery_state",
        "product_name",
        "created_at", "updated_at",
    )
    out: Dict[str, Any] = {}
    for k in keys:
        v = row.get(k)
        if v is None:
            continue
        if k in ("id", "user_id", "business_id", "logistic_id"):
            out[k] = str(v)
        elif k in ("created_at", "updated_at") and hasattr(v, "isoformat"):
            out[k] = v.isoformat()
        else:
            out[k] = v
    pa = row.get("product_attributes")
    if isinstance(pa, dict):
        out["product_attributes"] = pa
    meta = row.get("metadata")
    if isinstance(meta, dict) and meta:
        out["metadata"] = meta
    return out


def _order_product_attributes_for_db(
    explicit: Optional[Dict[str, Any]],
    product: Optional[Product],
    quantity: int,
) -> Dict[str, Any]:
    """Merge tool/model product metadata into a JSON-friendly snapshot for `orders.product_attributes`."""
    out: Dict[str, Any] = {}
    if product and product.metadata:
        out.update(dict(product.metadata))
    if product:
        if getattr(product, "id", None) and str(product.id).strip():
            out.setdefault("product_id", str(product.id).strip())
        try:
            price = float(product.price)
        except (TypeError, ValueError):
            price = None
        if price:
            out.setdefault("unit_price", price)
    if explicit:
        out.update(explicit)
    out.setdefault("quantity", int(quantity))
    return out


def _slim_process_for_tool(pid: str, proc: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "process_id": pid,
        "task_type": proc.get("task_type"),
        "product_name": proc.get("product_name"),
        "order_id": proc.get("order_id"),
        "order_number": proc.get("order_number"),
        "status": proc.get("status"),
        "tracking_number": proc.get("tracking_number"),
        "quantity": proc.get("quantity"),
    }


central_agent_base = BaseAgent(
    model_name=CENTRAL_AGENT_MODEL_NAME,
    system_prompt="""
    You are the Lead Transaction Architect. Your mission is to fulfil the objective (i.e task type) of every "Process" (thread) ranging from initial inquiry to final delivery by coordinating with Customers, Vendor, and Logistics (wherea applicable). 
    You act as the sole intelligence hub connecting Customers, Vendor, and Logistics. 
    You do not just pass messages; you interpret data, verify conditions, and drive the deal/action forward.

#The Three-Step Execution Loop
For every interaction, you MUST internally follow this sequence:
    Status Audit: Check the finished_tasks and thread history. What is the current milestone and task type? (Inquiry → Availability → Payment → Fulfillment → Delivery).
    Tool Execution: Call necessary tools to fetch real-time facts (e.g., check bank API for payment, check vendor stock) or update processes (e.g update stock in db, update order status, mark task as finished). To change catalog rows for the vendor in this thread, use **mutate_vendor_catalog** (`set_price`, `set_stock`, or `add`) only after the vendor clearly authorizes the change (use `product_id` from ops context for updates, not customer-facing text).
    Strategic Routing: Based on the Outcome, decide the single most logical recipient to act next.

#Communication Protocols
1. Customer (The "High-End Salesperson")
    Persona: Professional, persuasive, and clear.
    Goal: Conversion and reassurance.
    Behavior: Use "closing" language. Instead of "The item is available," say "Great news! We’ve confirmed the item is in stock and reserved just for you. Please complete the payment via the link below to finalize your order."
    Constraint: Never share internal IDs or technical jargon.

2. Vendor (The "Ops Manager")
    Persona: Direct and efficiency-focused.
    Goal: Fulfillment readiness.
    Behavior: Provide clear triggers (e.g., "Payment confirmed for Order #123. Please begin packaging for pickup.")
    Constraint: One actionable request per message.

3. Logistics (The "Dispatcher")
    Persona: Technical and precise.
    Goal: Seamless transit.
    Behavior: Always include order_id, pickup location, and specific time windows.
    Constraint: Only engage Logistics after Vendor confirms "Ready for Pickup."
    
Strict Business Rules (The "Guardrails")
    1. The Payment Hard-Gate: You are strictly forbidden from generating an order or contacting Logistics until you (using your tools) have explicitly verified payment_status: SUCCESS or you have received a confirmation message from the vendor that the payment has been verified.
    2. The "Hint" Override: If a hint_recipient is provided, evaluate it against your current state, finished tasks and communication history. For example, If the hint says "Logistics" but payment is not confirmed, ignore the hint and route to the Customer for payment.
    Interpretation of Outcomes: Never dump raw tool data. "Fold" the outcome into a narrative.
        Bad: "Tool result: success."
        Good: (to Customer) "Your payment was successful! We are now coordinating with the vendor to prep your package."
    3. Post-payment delivery routing: After payment is verified / an order exists, call **get_delivery_logistics_context**. If **db_partner_logistic_id** is set, use that logistics party for coordination. 
    If it is null and **party_assigned_logistic_id** is unset, ask the Vendor whether they want to self-handle delivery or want a registered carrier;
    then call **finalize_vendor_delivery_route** (`self_handled=True` for vendor-only shipping, `self_handled=False` with optional `logistic_id`; 
    omit `logistic_id` to auto-pick a registered company). Persisted party state is visible to business chat.
    4. product/inventory update: Any new update you get concerning a product or inventory (i.e price, stock, new SKUs, etc) from the vendor, use **mutate_vendor_catalog** to update the product or inventory in the database first before taking your next step.
    5. process update: Any new update you get concerning a process (i.e order status, quantity, delivery status, etc) from the vendor, use **update_process** to merge fields into the Redis session (quantity, order_id, order_number, address, tracking, logistic_id, status, product_name, price, task_type) using ``process_id`` from context before taking your next step. For **Logistics coordination** after payment verification, ensure the open process is updated with **order_id** (and price/quantity when known) this way before messaging logistics. For **DB** order row changes (shipped/delivered, tracking), still use **update_order_status** when appropriate.
    6. Post-payment update: After verifying payment, update the product inventory in the db, deduct the quantity from the stock and update the process with the new quantity.

Thread Closure: Call **mark_process_completed** once the process objective is reached (e.g. delivery confirmed) so downstream UIs stop surfacing it as active.""",
    deps_type=CentralAgentDeps,
    output_type=CentralAgentResponse,
    model_settings={'thinking': 'medium'}
)

central_agent = central_agent_base.agent


def _customer_id(ctx: RunContext[CentralAgentDeps]) -> str:
    return ctx.deps.customer_id or (ctx.deps.customer.id if ctx.deps.customer else "")


def _business_id(ctx: RunContext[CentralAgentDeps]) -> str:
    return ctx.deps.business_id or (ctx.deps.vendor.id if ctx.deps.vendor else "")


def _logistic_id(ctx: RunContext[CentralAgentDeps]) -> str:
    return ctx.deps.logistic_id or (ctx.deps.logistics.id if ctx.deps.logistics else "")


@central_agent.tool
async def create_order(
    ctx: RunContext[CentralAgentDeps],
    product_name: str,
    total_amount: float,
    quantity: int = 1,
    delivery_address: Optional[str] = None,
    delivery_city: Optional[str] = None,
    delivery_state: Optional[str] = None,
    product_attributes: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Create order in DB and cache in Redis processes. Call only after payment is confirmed.
    Optional `product_attributes` merges with the active product's metadata (size, variant, etc.)."""
    customer_id = _customer_id(ctx)
    business_id = _business_id(ctx)
    pid = (ctx.deps.process_id or "").strip()

    if not customer_id or not business_id:
        return {"error": "Missing customer or business context"}
    if not pid:
        return {"error": "process_id is required to create an order — ensure_central_process must be called first."}

    existing_order_id = (ctx.deps.active_process or {}).get("order_id")
    if existing_order_id:
        existing = await get_order_by_id(str(existing_order_id))
        if existing:
            logger.info(
                "central_agent | create_order_skipped_duplicate | order_id=%s process_id=%s",
                existing_order_id,
                pid,
            )
            return {
                "order_id": str(existing["id"]),
                "order_number": existing["order_number"],
                "status": "already_created",
                "message": f"Order {existing['order_number']} was already created for this process.",
            }

    resolved_name = (product_name or "").strip()
    if not resolved_name and ctx.deps.product and (ctx.deps.product.name or "").strip():
        resolved_name = (ctx.deps.product.name or "").strip()
    resolved_name = resolved_name or None

    attrs = _order_product_attributes_for_db(product_attributes, ctx.deps.product, quantity)

    try:
        order = await db_create_order(
            user_id=customer_id,
            business_id=business_id,
            total_amount=total_amount,
            quantity=quantity,
            delivery_address=delivery_address,
            delivery_city=delivery_city,
            delivery_state=delivery_state,
            metadata={
                **({"product_name": resolved_name} if resolved_name else {}),
                "quantity": quantity,
            },
            product_name=resolved_name,
            product_attributes=attrs,
        )
        order_id = str(order["id"])
        order_number = order["order_number"]

        ap = ctx.deps.active_process
        ap.update(
            {
                "product_name": resolved_name or product_name or ap.get("product_name") or "",
                "order_id": order_id,
                "order_number": order_number,
                "quantity": quantity,
                "customer_address": delivery_address,
                "status": "pending",
            }
        )
        user_state = await get_user_state(customer_id, business_id) or {}
        user_state.setdefault("processes", {})[pid] = ap
        await modify_user_state(customer_id, business_id, user_state)
        await upsert_order_process_link(order_id, pid, customer_id, business_id)

        logger.info(
            "central_agent | order_created | order_number=%s order_id=%s process_id=%s product=%s customer=%s",
            order_number,
            order_id,
            pid,
            resolved_name or product_name,
            customer_id,
        )
        return {
            "order_id": order_id,
            "order_number": order_number,
            "status": "created",
            "message": f"Order {order_number} created for {resolved_name or product_name or 'purchase'}",
        }
    except Exception as e:
        logger.error(
            "central_agent | create_order_failed | process_id=%s customer=%s business=%s err=%s",
            ctx.deps.process_id,
            customer_id,
            business_id,
            e,
            exc_info=True,
        )
        return {"error": str(e)}


@central_agent.tool
async def get_order_info(
    ctx: RunContext[CentralAgentDeps],
    order_id: Optional[str] = None,
    order_number: Optional[str] = None,
) -> Dict[str, Any]:
    """Get order from DB or processes cache. Pass order_id or order_number."""
    customer_id = _customer_id(ctx)
    business_id = _business_id(ctx)
    user_state = await get_user_state(customer_id, business_id) or {}

    if order_id:
        order = await get_order_by_id(order_id)
        if order:
            return _slim_order_for_tool(dict(order))
    if order_number:
        order = await get_order_by_number(order_number)
        if order:
            return _slim_order_for_tool(dict(order))

    processes = user_state.get("processes", {})
    for pid, proc in processes.items():
        if not isinstance(proc, dict):
            continue
        if proc.get("order_id") == order_id or proc.get("order_number") == order_number:
            return _slim_process_for_tool(str(pid), proc)
        if not order_id and not order_number and proc.get("order_id"):
            return _slim_process_for_tool(str(pid), proc)

    return {"error": "Order not found"}

@central_agent.tool
async def list_customer_orders(
    ctx: RunContext[CentralAgentDeps],
    limit: int = 30,
    on_date: Optional[str] = None,
    created_after: Optional[str] = None,
    created_before: Optional[str] = None,
) -> Dict[str, Any]:
    """List DB orders for this customer with this vendor. Use when reconciling history or matching a receipt to a purchase.
    `on_date`: YYYY-MM-DD (UTC calendar day on `created_at`). `created_after` / `created_before`: ISO-8601 datetimes (optional bounds)."""
    customer_id = _customer_id(ctx)
    business_id = _business_id(ctx)
    if not customer_id or not business_id:
        return {"error": "Missing customer or business context", "orders": []}
    rows = await list_orders_for_customer_store(
        customer_id,
        business_id,
        limit=max(1, min(int(limit), 100)),
        on_date=(on_date or "").strip() or None,
        created_after_iso=(created_after or "").strip() or None,
        created_before_iso=(created_before or "").strip() or None,
    )
    return {
        "count": len(rows),
        "orders": [_slim_order_for_tool(dict(r)) for r in rows],
    }


@central_agent.tool
async def update_order_status(
    ctx: RunContext[CentralAgentDeps],
    order_id: str,
    status: Literal["pending", "payment_verified", "shipped", "delivered", "cancelled"],
    tracking_number: Optional[str] = None,
    logistic_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Update order status in DB. Status: pending, payment_verified, shipped, delivered, cancelled. Call when vendor/logistics confirms delivery or shipping."""
    try:
        updated = await db_update_order_status(
            order_id=order_id,
            status=status,
            tracking_number=tracking_number or "",
            logistic_id=logistic_id or "",
        )
        if not updated:
            return {"error": "Order not found", "order_id": order_id}
        await touch_order_process_link(order_id)
        customer_id = _customer_id(ctx)
        business_id = _business_id(ctx)
        user_state = await get_user_state(customer_id, business_id) or {}
        processes = user_state.get("processes", {})
        for pid, proc in processes.items():
            if not isinstance(proc, dict):
                continue
            if str(proc.get("order_id") or "") == str(order_id):
                proc["status"] = status
                if tracking_number:
                    proc["tracking_number"] = tracking_number
                if logistic_id:
                    proc["logistic_id"] = str(logistic_id).strip()
                processes[pid] = proc
                ctx.deps.active_process.update(proc)
                break
        user_state["processes"] = processes
        await modify_user_state(customer_id, business_id, user_state)
        return {"status_updated": "updated", "order_id": order_id, "new_status": status}
    except Exception as e:
        return {"error": str(e)}


@central_agent.tool
async def update_process(
    ctx: RunContext[CentralAgentDeps],
    process_id: Optional[str] = None,
    product_name: Optional[str] = None,
    order_id: Optional[str] = None,
    order_number: Optional[str] = None,
    quantity: Optional[int] = None,
    price: Optional[float] = None,
    customer_address: Optional[str] = None,
    status: Optional[str] = None,
    tracking_number: Optional[str] = None,
    logistic_id: Optional[str] = None,
    task_type: Optional[str] = None,
) -> Dict[str, Any]:
    """Update fields on a session process in Redis (customer–vendor pair). Pass only fields that newly became known (e.g. quantity, order_id, delivery address). Defaults ``process_id`` to the active thread when omitted."""
    pid = (process_id or ctx.deps.process_id or "").strip()
    if not pid:
        return {"error": "process_id is required (or no active process in context)."}
    customer_id = _customer_id(ctx)
    business_id = _business_id(ctx)
    if not customer_id or not business_id:
        return {"error": "Missing customer or vendor context."}
    user_state = await get_user_state(customer_id, business_id) or {}
    processes = user_state.setdefault("processes", {})
    proc = processes.get(pid)
    if not isinstance(proc, dict):
        return {"error": f"Process {pid!r} not found in session."}
    changed = apply_process_field_updates(
        proc,
        product_name=product_name,
        order_id=order_id,
        order_number=order_number,
        quantity=quantity,
        price=price,
        customer_address=customer_address,
        status=status,
        tracking_number=tracking_number,
        logistic_id=logistic_id,
        task_type=task_type,
    )
    if not changed:
        return {
            "ok": True,
            "process_id": pid,
            "updated": [],
            "message": "No fields supplied; pass at least one optional field to update.",
        }
    processes[pid] = proc
    user_state["processes"] = processes
    if ctx.deps.process_id == pid:
        ctx.deps.active_process.clear()
        ctx.deps.active_process.update(proc)
    await modify_user_state(customer_id, business_id, user_state)
    return {
        "ok": True,
        "process_id": pid,
        "updated": changed,
        "process": _slim_process_for_tool(pid, proc),
    }


async def _catalog_set_price_row(
    business_id: str, product_id: str, price: float
) -> Dict[str, Any]:
    row = await update_product_price_for_business(business_id, product_id, price)
    if not row:
        return {"error": "Product not found or not owned by this vendor"}
    return {
        "success": True,
        "action": "set_price",
        "product_id": str(row.get("id", "")),
        "price": float(row.get("price") or 0),
        "name": row.get("name"),
    }


async def _catalog_set_stock_row(
    business_id: str, product_id: str, stock_quantity: int
) -> Dict[str, Any]:
    row = await update_product_stock_for_business(
        business_id, product_id, int(stock_quantity)
    )
    if not row:
        return {"error": "Product not found or not owned by this vendor"}
    return {
        "success": True,
        "action": "set_stock",
        "product_id": str(row.get("id", "")),
        "stock_quantity": row.get("stock_quantity"),
        "name": row.get("name"),
    }


async def _catalog_add_row(
    business_id: str,
    name: str,
    price: float,
    stock_quantity: int,
    description: str,
    category: str,
    attributes: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    row = await db_add_product(
        business_id=business_id,
        name=name,
        price=price,
        stock_quantity=stock_quantity,
        description=description,
        category=category,
        attributes=attributes,
    )
    if not row:
        return {"error": "Could not add product"}
    return {
        "success": True,
        "action": "add",
        "product_id": str(row.get("id", "")),
        "name": row.get("name"),
        "price": row.get("price"),
        "stock_quantity": row.get("stock_quantity"),
    }


@central_agent.tool
async def mutate_vendor_catalog(
    ctx: RunContext[CentralAgentDeps],
    action: Literal["set_price", "set_stock", "add"],
    product_id: Optional[str] = None,
    name: Optional[str] = None,
    price: Optional[float] = None,
    stock_quantity: Optional[int] = None,
    description: str = "",
    category: str = "",
) -> Dict[str, Any]:
    """Update vendor catalog in DB for this thread. Use action ``set_price`` (needs product_id, price), ``set_stock`` (needs product_id, stock_quantity), or ``add`` (needs name, price; optional stock_quantity, description, category)."""
    bid = _business_id(ctx)
    if not bid:
        return {"error": "No vendor context"}

    pid = (product_id or "").strip()
    nm = (name or "").strip()

    if action == "set_price":
        if not pid:
            return {"error": "product_id required for set_price"}
        if price is None:
            return {"error": "price required for set_price"}
        return await _catalog_set_price_row(bid, pid, price)

    if action == "set_stock":
        if not pid:
            return {"error": "product_id required for set_stock"}
        if stock_quantity is None:
            return {"error": "stock_quantity required for set_stock"}
        return await _catalog_set_stock_row(bid, pid, stock_quantity)

    if not nm:
        return {"error": "name required for add"}
    if price is None:
        return {"error": "price required for add"}
    sq = int(stock_quantity) if stock_quantity is not None else 0
    return await _catalog_add_row(bid, nm, price, sq, description, category)


@central_agent.tool
async def mark_task_finished(
    ctx: RunContext[CentralAgentDeps],
    task_description: str,
) -> Dict[str, Any]:
    """Append to finished_tasks for this process (persisted to Redis)."""
    ap = ctx.deps.active_process
    ft = ap.setdefault("finished_tasks", [])
    if task_description not in ft:
        ft.append(task_description)
    customer_id = _customer_id(ctx)
    business_id = _business_id(ctx)
    pid = ctx.deps.process_id
    user_state = await get_user_state(customer_id, business_id) or {}
    user_state.setdefault("processes", {})[pid] = ap
    await modify_user_state(customer_id, business_id, user_state)
    tail = ft[-12:] if len(ft) > 12 else ft
    return {"status": "updated", "finished_tasks": tail, "total": len(ft)}


@central_agent.tool
async def get_delivery_address(
    ctx: RunContext[CentralAgentDeps],
    product_name: Optional[str] = None,
) -> Optional[str]:
    """Get customer delivery address from processes. Pass product_name if known."""
    customer_id = _customer_id(ctx)
    business_id = _business_id(ctx)
    user_state = await get_user_state(customer_id, business_id) or {}
    _cust = user_state.get("customer")
    if isinstance(_cust, dict):
        addr = _cust.get("address")
        if addr:
            return addr
    
    processes = user_state.get("processes", {})
    addr = ctx.deps.active_process.get("customer_address")
    if addr:
        return addr

    pname = product_name or ctx.deps.product_name
    for _pid, proc in processes.items():
        if isinstance(proc, dict) and (proc.get("product_name") or "") == (pname or ""):
            return proc.get("customer_address")

    user_info = await get_user_by_id(customer_id)
    if user_info:
        return user_info.get("delivery_address")
    return "customer address not found. Prompt customer to provide delivery address."


@central_agent.tool
async def get_logistics_info(ctx: RunContext[CentralAgentDeps], limit: int=5) -> Dict[str, Any]:
    """Get logistics companies for the vendor. Returns list of available logistics."""
    try:
        logistics = await get_logistics_companies(limit=limit)
        if logistics:
            return {"logistics": [{"id": str(l["id"]), "name": l["name"], "phone": l.get("phone_number")} for l in logistics]}
        return {"logistics": [], "message": "No logistics companies configured"}
    except Exception as e:
        return {"error": str(e)}


@central_agent.tool
async def get_delivery_logistics_context(ctx: RunContext[CentralAgentDeps]) -> Dict[str, Any]:
    """Read the vendor's current delivery setup: DB-linked partner logistics company (if any),
    the `delivery_route` and `assigned_logistic_id` stored in vendor party Redis, and a registry
    sample of available companies. Call this before deciding whether to assign a logistics partner
    or confirm the vendor handles delivery themselves."""
    bid = _business_id(ctx)
    if not bid:
        return {"error": "No vendor context"}
    try:
        biz = await get_business_info(bid) or {}
        party = await get_party_state(bid) or {}
        db_partner = biz.get("partner_logistic_id")
        party_assigned = party.get("logistic_id")
        partner = db_partner or party_assigned
        pname = None
        if partner:
            pr = await get_business_info(str(partner)) or {}
            pname = pr.get("name")

        # No configured partner and no prior assignment — pull registry so agent can pick one
        registry: List[Dict[str, Any]] = []
        if not partner:
            rows = await get_logistics_companies(limit=5)
            registry = [{"id": str(r["id"]), "name": r.get("name"), "phone": r.get("phone_number")} for r in rows]

        return {
            "db_partner_logistic_id": str(db_partner) if db_partner else None,
            "party_assigned_logistic_id": str(party_assigned) if party_assigned else None,
            "db_partner_name": pname,
            "party_delivery_route": party.get("delivery_route"),
            "registry_sample": registry or None,
        }
    except Exception as e:
        return {"error": str(e)}


@central_agent.tool
async def finalize_vendor_delivery_route(
    ctx: RunContext[CentralAgentDeps],
    self_handled: bool,
    logistic_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Persist the vendor's delivery route to Redis party state.
    `self_handled=True` → vendor delivers themselves (clears any assigned logistics).
    `self_handled=False` → third-party logistics; supply `logistic_id` if already known,
    or leave blank to auto-assign a random registered company.
    The persisted route is read by the business chat and logistics agent on subsequent turns."""
    bid = _business_id(ctx)
    if not bid:
        return {"error": "No vendor context"}
    try:
        st = await get_party_state(bid) or {}
        if self_handled:
            st["delivery_route"] = "vendor"
            st.pop("logistic_id", None)
        else:
            lid = (logistic_id or "").strip()
            if not lid:
                lid = await pick_random_logistics_company_id()
                if not lid:
                    st['delivery_route'] = "vendor"
                    st.pop("logistic_id", None)
                    await modify_party_state(bid, st)
                    return {"error": "No logistics companies in registry. Allow vendor to self-handle delivery."}
            st["delivery_route"] = "logistics"
            st["logistic_id"] = lid
        await modify_party_state(bid, st)
        return {
            "ok": True,
            "delivery_route": st.get("delivery_route"),
            "assigned_logistic_id": st.get("logistic_id"),
        }
    except Exception as e:
        return {"error": str(e)}


@central_agent.tool
async def get_contact_info(
    ctx: RunContext[CentralAgentDeps],
    entity: EntityType,
) -> Dict[str, Any]:
    """Get contact info for Customer, Vendor, or Logistics ONLY WHEN NEEDED."""
    try:
        if entity == EntityType.CUSTOMER:
            uid = _customer_id(ctx)
            info = await get_user_by_id(uid) if uid else None
            if info:
                return {"phone": info.get("phone_number"), "name": info.get("full_name"), "address": info.get("delivery_address")}
        elif entity == EntityType.VENDOR:
            bid = _business_id(ctx)
            info = await get_business_info(bid) if bid else None
            if info:
                return {"phone": info.get("phone_number"), "email": info.get("email"), "name": info.get("name")}
        elif entity == EntityType.LOGISTICS:
            if ctx.deps.logistics:
                return {"id": ctx.deps.logistics.id, "name": ctx.deps.logistics.name, "phone": ctx.deps.logistics.phone}
            lid = ctx.deps.logistic_id
            if lid:
                info = await get_business_info(lid)
                if info:
                    return {"id": str(info.get("id")), "name": info.get("name"), "phone": info.get("phone_number")}
        return {}
    except Exception as e:
        return {"error": str(e)}


@central_agent.tool
async def get_business_bank_details(ctx: RunContext[CentralAgentDeps]) -> Dict[str, Any]:
    """Get vendor bank account details only for payment-associated tasks. USE ONLY WHEN NEEDED. Fetches from cache or DB if not present."""
    business_id = _business_id(ctx)
    if not business_id:
        return {"error": "No business context"}

    customer_id = _customer_id(ctx)
    user_state = await get_user_state(customer_id, business_id) or {}
    business_info = user_state.get("business_information", {})

    has_bank = (
        business_info.get("bank_name")
        or business_info.get("bank_account_number")
        or business_info.get("bank_account_name")
    )
    if not has_bank:
        business_info = await get_business_info(business_id) or {}
        user_state["business_information"] = business_info
        await modify_user_state(customer_id, business_id, user_state)
        if business_info:
            logger.info(
                "central_agent | bank_details_fetched | business_id=%s",
                business_id,
            )

    return {
        "bank_name": business_info.get("bank_name", ""),
        "bank_account_number": business_info.get("bank_account_number", ""),
        "bank_account_name": business_info.get("bank_account_name", ""),
    }


@central_agent.tool
async def mark_process_completed(
    ctx: RunContext[CentralAgentDeps],
    process_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Set completed=True on a process when its objective is done. Persists to customer Redis state."""
    pid = (process_id or ctx.deps.process_id or "").strip()
    if not pid:
        return {"error": "process_id required"}
    customer_id = _customer_id(ctx)
    business_id = _business_id(ctx)
    if not customer_id or not business_id:
        return {"error": "Missing customer or business context"}
    us = await get_user_state(customer_id, business_id) or {}
    procs = us.setdefault("processes", {})
    tgt = procs.get(pid)
    if not isinstance(tgt, dict):
        return {"error": f"process {pid!r} not found"}
    tgt["completed"] = True
    procs[pid] = tgt
    oid = tgt.get("order_id")
    if oid:
        await mark_order_process_link_completed(str(oid))
    await modify_user_state(customer_id, business_id, us)
    if ctx.deps.process_id == pid:
        ctx.deps.active_process["completed"] = True
    return {"ok": True, "process_id": pid}


async def run_central_agent(
    event_message: CentralAgentInput,
    user_state: Optional[Dict[str, Any]] = None,
    vendor_only: bool = False,
    debug: bool = False,
    *,
    caller_agent: str = "unknown",
) -> Dict[str, Any]:
    """Run central agent. Uses Redis state; processes keyed by process_id."""
    customer_id = getattr(event_message.customer, "id", "") if event_message.customer else ""
    business_id = getattr(event_message.business, "id", "") if event_message.business else ""
    logistic_id = getattr(event_message.logistic, "id", None) if event_message.logistic else None

    if not customer_id or not business_id:
        raise ValueError("central agent requires customer.id and business.id")

    try:
        from backend.chatbot.utils.history_summarizer import maybe_summarize_comm_history

        redis_state = user_state or await get_user_state(customer_id, business_id) or {}
        pid, proc = await get_or_create_process_for_event(redis_state, event_message)
        event_message.process_id = pid

        comm = proc.setdefault("communication_history", [])

        comm = await maybe_summarize_comm_history(comm)
        proc["communication_history"] = comm

        product_name = proc.get("product_name") or (
            event_message.product.name if event_message.product else None
        )
        
        order_num_out = proc.get("order_number") or proc.get("order_id") or event_message.order_id

        # Specialist agents (product/payment/logistics/complaint) hint AGENT→VENDOR when they
        # need the vendor told something directly. If central's own routing decision (recipient_lower,
        # below) targets somewhere else instead, still guarantee the vendor's inbox gets the
        # original specialist request rather than silently dropping it.
        force_vendor_inbox = (
            event_message.sender == EntityType.AGENT
            and event_message.recipient == EntityType.VENDOR
        )

        _tt = _task_label(event_message.task_type)
        _msg_prev = (event_message.message or "")[:2000]
        logger.info(
            "central_agent_invoked | caller=%s customer_id=%s business_id=%s process_id=%s "
            "task_type=%s incoming_sender=%s incoming_recipient=%s vendor_only=%s message=%r",
            caller_agent,
            customer_id,
            business_id,
            pid,
            _tt,
            event_message.sender,
            event_message.recipient,
            vendor_only,
            _msg_prev,
        )
        logfire.info(
            "central_agent_invoked",
            caller_agent=caller_agent,
            customer_id=customer_id,
            business_id=business_id,
            process_id=pid,
            task_type=_tt,
            incoming_sender=str(event_message.sender),
            incoming_recipient=str(event_message.recipient),
            vendor_only=vendor_only,
            message_preview=_msg_prev,
        )

        deps = CentralAgentDeps(
            active_process=proc,
            process_id=pid,
            customer=event_message.customer,
            vendor=event_message.business,
            product=event_message.product,
            logistics=event_message.logistic,
            customer_id=customer_id,
            business_id=business_id,
            logistic_id=getattr(event_message.logistic, "id", None) if event_message.logistic else None,
            order_id=event_message.order_id,
            product_name=product_name,
            id=f"{customer_id}:{business_id}",
        )

        role = get_role(event_message)
        comm.append(
            {"role": role, "name": _enum_label(event_message.sender), "content": event_message.message}
        )

        ft = proc.get("finished_tasks") or []
        ft_text = "\n".join(f"- {t}" for t in ft) if ft else "(none yet)"
        hint = (
            # f"Inbound hint (non-binding): sender={_enum_label(event_message.sender)} "
            f"proposed_recipient (hint)={_enum_label(event_message.recipient)}\n\n"
        )
        proc_details = json.dumps(proc)
        run_prompt = (
            hint
            + f"Process details: {proc_details}\n\n"
            + f"Task Type: {_task_label(event_message.task_type)}\n**Finished tasks:**\n{ft_text}\n\n**Thread**\n{json.dumps(comm)}"
        )

        run_instructions = build_central_agent_run_instructions(event_message, pid, proc)
        agent_stdout("central_agent input", run_prompt)
        result = await central_agent.run(run_prompt, deps=deps, instructions=run_instructions)
        response = result.output
        logger.info(
            "central_agent_completed | caller=%s process_id=%s model_recipient=%s next_step_preview=%r",
            caller_agent,
            pid,
            response.recipient,
            (response.next_step or "")[:120],
        )

        recipient_lower = _enum_label(response.recipient).strip().lower()
        outbound_message = (response.message or "").strip()
        
        comm.append(
            {
                "role": _sender_role(response.sender),
                "name": _enum_label(response.sender),
                "content": outbound_message,
            }
        )

        if recipient_lower == "customer" and (customer_id and business_id):
            outbound_message = await polish_central_message_for_customer(
                draft_message=outbound_message,
                customer_id=customer_id,
                business_id=business_id,
                pair_state=redis_state,
            )

        agent_stdout(
            "central_agent output",
            f"recipient={response.recipient}\n"
            f"sender={response.sender}\n"
            f"next_step={response.next_step}\n"
            f"message=\n{outbound_message}",
        )

        # prev_ft = list(proc.get("finished_tasks") or [])
        out_ft = list(response.finished_tasks or [])
        # merged = list(dict.fromkeys(prev_ft + out_ft))
        proc["finished_tasks"] = out_ft
        proc["communication_history"] = comm
        redis_state.setdefault("processes", {})[pid] = proc
        await modify_user_state(customer_id, business_id, redis_state)

        task_type_label = str(proc.get("task_type") or "")

        logistics_party_id: Optional[str] = None
        if event_message.logistic and getattr(event_message.logistic, "id", None):
            logistics_party_id = str(event_message.logistic.id).strip() or None
        if not logistics_party_id and proc.get("logistic_id"):
            logistics_party_id = str(proc.get("logistic_id")).strip() or None
        if not logistics_party_id and recipient_lower == "logistics" and business_id:
            # finalize_vendor_delivery_route persists to the vendor's own party state, not
            # this process dict — fall back to it (and the DB partner) so the first turn
            # that routes to logistics doesn't silently drop the message just because the
            # model never separately called update_process(logistic_id=...).
            vendor_party = await get_party_state(business_id) or {}
            fallback_lid = vendor_party.get("logistic_id")
            if not fallback_lid:
                biz_row = await get_business_info(business_id) or {}
                fallback_lid = (biz_row or {}).get("partner_logistic_id")
            if fallback_lid:
                logistics_party_id = str(fallback_lid).strip() or None
                proc["logistic_id"] = logistics_party_id
                redis_state.setdefault("processes", {})[pid] = proc
                await modify_user_state(customer_id, business_id, redis_state)

        sent_message = await deliver_central_outbound(
            CentralOutboundContext(
                recipient_lower=recipient_lower,
                outbound_message=outbound_message,
                response_sender=_enum_label(response.sender),
                response_recipient=_enum_label(response.recipient),
                customer_id=customer_id,
                business_id=business_id,
                product_name=product_name,
                order_id=str(order_num_out) if order_num_out else None,
                process_id=pid,
                task_type_label=task_type_label,
                event_message=event_message,
                logistics_party_id=logistics_party_id,
            )
        )

        if force_vendor_inbox and recipient_lower != "vendor":
            logger.info(
                "central_agent_vendor_inbox_fallback | caller=%s process_id=%s task_type=%s "
                "(model targeted %s; pushing original agent->vendor message to vendor inbox)",
                caller_agent,
                pid,
                task_type_label,
                recipient_lower,
            )
            await deliver_central_outbound(
                CentralOutboundContext(
                    recipient_lower="vendor",
                    outbound_message=(event_message.message or "").strip(),
                    response_sender="Agent",
                    response_recipient="Vendor",
                    customer_id=customer_id,
                    business_id=business_id,
                    product_name=product_name,
                    order_id=str(order_num_out) if order_num_out else None,
                    process_id=pid,
                    task_type_label=task_type_label,
                    event_message=event_message,
                    logistics_party_id=logistics_party_id,
                )
            )

        try:
            recipient_num = get_contact(_enum_label(response.recipient), event_message)
            if recipient_num:
                whatsapp.send_message(PHONE_NUMBER_ID, recipient_num, sent_message)
        except Exception as e:
            if debug:
                print(f"WhatsApp send error: {e}")

        return {
            "message": sent_message,
            "sender": response.sender,
            "recipient": response.recipient,
            "reasoning": response.reasoning,
            "process_id": pid,
        }
    except Exception as e:
        logger.exception("run_central_agent failed")
        return {
            "message": "",
            "sender": "",
            "recipient": "",
            "reasoning": "",
            "error": str(e),
        }


