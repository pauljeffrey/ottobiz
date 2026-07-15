"""
Central agent helpers: structured input, process lifecycle (Redis), inbox delivery.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union

from backend.logging_config import get_logger
from backend.db.cache_utils import modify_user_state
from backend.struct import CentralAgentInput, Customer, EntityType, Logistics, Product, TaskType, Vendor

logger = get_logger(__name__)


def merge_customer_chat_into_comm(
    comm: List[Dict[str, Any]],
    chat_history: Any,
    *,
    max_turns: int = 12,
) -> None:
    """When central is driven by vendor/logistics, copy recent customer user lines from pair chat_history into comm."""
    from pydantic_ai.messages import ModelMessagesTypeAdapter, ModelRequest, UserPromptPart

    hist = chat_history or []
    if hist and isinstance(hist[0], dict):
        try:
            hist = ModelMessagesTypeAdapter.validate_python(hist)
        except Exception:
            hist = []

    existing = {str(x.get("content", "")) for x in comm if isinstance(x, dict)}
    lines: List[str] = []
    for m in hist:
        if not isinstance(m, ModelRequest):
            continue
        for p in m.parts:
            if not isinstance(p, UserPromptPart):
                continue
            c = (p.content or "").strip()
            if not c or c.startswith("[Central agent]"):
                continue
            lines.append(c)
    for line in lines[-max_turns:]:
        if line not in existing:
            comm.append({"role": "customer", "name": "Customer", "content": line})
            existing.add(line)


def coerce_entity(value: Union[str, EntityType]) -> EntityType:
    if isinstance(value, EntityType):
        return value
    s = str(value).strip()
    for e in EntityType:
        if s.lower() == e.value.lower() or s.upper() == e.name:
            return e
    return EntityType.AGENT


def _task_label(tt: Optional[TaskType]) -> str:
    if tt is None:
        return TaskType.UNKNOWN.value
    return tt.value if isinstance(tt, TaskType) else str(tt)

def _enum_label(x: Any) -> str:
    return x.value if hasattr(x, "value") else str(x)


def _sender_role(sender: Any) -> str:
    if sender == EntityType.CUSTOMER:
        return "customer"
    if sender == EntityType.VENDOR:
        return "vendor"
    if sender == EntityType.LOGISTICS:
        return "logistics"
    return "agent"

def new_process_dict(
    task_type: TaskType,
    product_name: str = "",
    order_id: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "task_type": _task_label(task_type),
        "product_name": product_name or "",
        "order_id": order_id,
        "price": None,
        "order_number": None,
        "quantity": None,
        "customer_address": None,
        "status": None,
        "tracking_number": None,
        "communication_history": [],
        "finished_tasks": [],
        "completed": False,
    }


def build_central_agent_run_instructions(
    event_message: CentralAgentInput,
    process_id: str,
    proc: Dict[str, Any],
) -> str:
    
    lines: List[str] = []
    cid = getattr(event_message.customer, "id", None) if event_message.customer else None
    bid = getattr(event_message.business, "id", None) if event_message.business else None
    lines.append(
        f"- identifiers: process_id={process_id!r}, customer_id={cid!r}, business_id={bid!r}"
    )

    def _emit(label: str, value: Any) -> None:
        if value is None:
            return
        if isinstance(value, str) and not value.strip():
            return
        lines.append(f"- {label}: {value!r}")

    for key in (
        "order_id",
        "order_number",
        "status",
        "tracking_number",
        "quantity",
        "customer_address",
        "product_name",
        "price",
        "logistic_id",
    ):
        if key not in proc:
            continue
        v = proc.get(key)
        if v is None or v == "":
            continue
        lines.append(f"- process[{key!r}]: {v!r}")

    if proc.get("completed"):
        lines.append("- process[completed]: True")

    ev_oid = event_message.order_id
    pr_oid = proc.get("order_id")
    if ev_oid and str(ev_oid).strip() and str(ev_oid) != str(pr_oid or ""):
        _emit("event_message.order_id (override or extra)", str(ev_oid).strip())

    if event_message.product:
        p = event_message.product
        pb: List[str] = []
        if (p.name or "").strip():
            pb.append(f"name={p.name!r}")
        if p.quantity and int(p.quantity) != 1:
            pb.append(f"quantity={p.quantity}")
        if p.price is not None and float(p.price) != 0.0:
            pb.append(f"price={p.price}")
        if getattr(p, "has_paid", False):
            pb.append("has_paid=True")
        if pb:
            lines.append("- event_message.product: " + ", ".join(pb))

    if event_message.customer:
        c = event_message.customer
        if (c.address or "").strip():
            _emit("event_message.customer.address", (c.address or "").strip())
        if (c.phone or "").strip():
            _emit("event_message.customer.phone", (c.phone or "").strip())

    if event_message.logistic:
        lg = event_message.logistic
        lid = getattr(lg, "id", None)
        if lid:
            _emit("event_message.logistic.id", str(lid).strip())
        if (lg.name or "").strip():
            _emit("event_message.logistic.name", (lg.name or "").strip())

    return (
        "### Transaction snapshot (structured; the **Thread** block below is conversational only)\n"
        + "\n".join(lines)
    )


def _pair_ids_from_event(event_message: CentralAgentInput) -> tuple[str, str]:
    customer_id = (
        str(getattr(event_message.customer, "id", "") or "").strip()
        if event_message.customer
        else ""
    )
    business_id = (
        str(getattr(event_message.business, "id", "") or "").strip()
        if event_message.business
        else ""
    )
    return customer_id, business_id


async def get_or_create_process_for_event(
    redis_state: Dict[str, Any],
    event_message: CentralAgentInput,
) -> tuple[str, Dict[str, Any]]:
    """Resolve process_id and mutable process dict under redis_state['processes']; persists pair state when mutated."""
    customer_id, business_id = _pair_ids_from_event(event_message)
    processes: Dict[str, Any] = redis_state.setdefault("processes", {})
    pid = (event_message.process_id or "").strip()

    if pid and pid in processes:
        raw = processes[pid]
        proc = raw if isinstance(raw, dict) else {}
        if not isinstance(raw, dict):
            processes[pid] = proc
            if customer_id and business_id:
                await modify_user_state(customer_id, business_id, redis_state)
        return pid, proc

    pname = (event_message.product.name if event_message.product else "") or ""
    tt = _task_label(event_message.task_type)
    oid = event_message.order_id

    for key, raw in list(processes.items()):
        if not isinstance(raw, dict):
            continue
        if raw.get("task_type") != tt:
            continue
        if (raw.get("product_name") or "") != (pname or ""):
            continue
        if oid and raw.get("order_id") and str(raw.get("order_id")) != str(oid):
            continue
        return str(key), raw

    new_id = str(uuid.uuid4())
    processes[new_id] = new_process_dict(
        event_message.task_type or TaskType.UNKNOWN,
        product_name=pname,
        order_id=oid,
    )
    if customer_id and business_id:
        await modify_user_state(customer_id, business_id, redis_state)
    return new_id, processes[new_id]


async def ensure_central_process(
    user_state: Dict[str, Any],
    *,
    task_type: TaskType,
    customer_id: str,
    vendor_id: str,
    product_name: str = "",
    order_id: Optional[str] = None,
    process_id: Optional[str] = None,
) -> str:
    """Create or reuse a process before notifying central; mutates user_state. Persists Redis when a new process is created."""
    cid = (customer_id or "").strip()
    vid = (vendor_id or "").strip()
    processes: Dict[str, Any] = user_state.setdefault("processes", {})
    pid_in = (process_id or "").strip()
    if pid_in and pid_in in processes:
        return pid_in

    tt = _task_label(task_type)
    pname = product_name or ""

    for key, raw in list(processes.items()):
        if not isinstance(raw, dict):
            continue
        if raw.get("task_type") != tt:
            continue
        if (raw.get("product_name") or "") != pname:
            continue
        if order_id and raw.get("order_id") and str(raw.get("order_id")) != str(order_id):
            continue
        return str(key)

    new_id = str(uuid.uuid4())
    processes[new_id] = new_process_dict(task_type, product_name=pname, order_id=order_id)
    if cid and vid:
        await modify_user_state(cid, vid, user_state)
    return new_id


def normalize_task_type_string(raw: Optional[str]) -> Optional[str]:
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    for t in TaskType:
        if s.lower() == t.value.lower() or s.lower() == t.name.lower():
            return t.value
    return s


def apply_process_field_updates(
    proc: Dict[str, Any],
    *,
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
) -> List[str]:
    """
    Merge supplied fields into a session ``process`` dict (mutates in place).
    Only arguments that are not ``None`` are applied. Returns keys touched.
    """
    changed: List[str] = []
    if product_name is not None:
        proc["product_name"] = str(product_name).strip()
        changed.append("product_name")
    if order_id is not None:
        proc["order_id"] = str(order_id).strip()
        changed.append("order_id")
    if order_number is not None:
        proc["order_number"] = str(order_number).strip()
        changed.append("order_number")
    if quantity is not None:
        proc["quantity"] = int(quantity)
        changed.append("quantity")
    if price is not None:
        proc["price"] = float(price)
        changed.append("price")
    if customer_address is not None:
        proc["customer_address"] = str(customer_address).strip()
        changed.append("customer_address")
    if status is not None:
        proc["status"] = str(status).strip()
        changed.append("status")
    if tracking_number is not None:
        proc["tracking_number"] = str(tracking_number).strip()
        changed.append("tracking_number")
    if logistic_id is not None:
        proc["logistic_id"] = str(logistic_id).strip()
        changed.append("logistic_id")
    if task_type is not None:
        tt = normalize_task_type_string(task_type)
        if tt:
            proc["task_type"] = tt
            changed.append("task_type")
    return changed


async def create_structured_input(
    sender: Union[str, EntityType],
    recipient: Union[str, EntityType],
    message: str,
    product: Optional[Product] = None,
    customer: Optional[Customer] = None,
    business: Optional[Vendor] = None,
    logistic: Optional[Logistics] = None,
    order_id: Optional[str] = None,
    process_id: Optional[str] = None,
    task_type: Optional[TaskType] = None,
) -> CentralAgentInput:
    return CentralAgentInput(
        sender=coerce_entity(sender),
        recipient=coerce_entity(recipient),
        message=message,
        product=product,
        customer=customer,
        business=business,
        logistic=logistic,
        order_id=order_id,
        process_id=process_id,
        task_type=task_type or TaskType.UNKNOWN,
    )


def get_role(event_message: CentralAgentInput) -> str:
    if event_message.sender == EntityType.CUSTOMER:
        return "customer"
    if event_message.sender == EntityType.VENDOR:
        return "vendor"
    if event_message.sender == EntityType.LOGISTICS:
        return "logistics"
    if event_message.sender == EntityType.AGENT:
        return "agent"
    return "agent"


def get_contact(entity: str, event_message: CentralAgentInput) -> Optional[str]:
    entity_lower = (entity or "").strip().lower()
    if entity_lower == "agent" and event_message.business:
        return getattr(event_message.business, "phone", None) or getattr(
            event_message.business, "id", None
        )
    if entity_lower == "customer" and event_message.customer:
        return getattr(event_message.customer, "phone", None) or getattr(
            event_message.customer, "id", None
        )
    if entity_lower == "vendor" and event_message.business:
        return getattr(event_message.business, "phone", None) or getattr(
            event_message.business, "id", None
        )
    if entity_lower == "logistics" and event_message.logistic:
        return getattr(event_message.logistic, "phone", None) or getattr(
            event_message.logistic, "id", None
        )
    return None


@dataclass
class CentralOutboundContext:
    recipient_lower: str
    outbound_message: str
    response_sender: str
    response_recipient: str
    customer_id: str
    business_id: str
    product_name: Optional[str]
    order_id: Optional[str]
    process_id: str
    task_type_label: str
    event_message: CentralAgentInput
    # Redis party key for logistics when recipient is logistics but inbound event has no logistic object.
    logistics_party_id: Optional[str] = None


async def deliver_central_outbound(ctx: CentralOutboundContext) -> str:
    """Push vendor/logistics/customer inbox updates; returns final prefixed message text for side channels."""
    from backend.db.cache_utils import (
        append_inbox_turn_to_customer_pair,
        append_inbox_turn_to_party_state,
        push_to_inbox_with_retry,
    )

    recipient_id: Optional[str] = None
    if ctx.recipient_lower == "vendor":
        recipient_id = ctx.business_id or None
    elif ctx.recipient_lower == "logistics":
        recipient_id = None
        if ctx.event_message.logistic:
            recipient_id = getattr(ctx.event_message.logistic, "id", None)
        if not recipient_id and ctx.logistics_party_id:
            recipient_id = str(ctx.logistics_party_id).strip() or None
    elif ctx.recipient_lower == "customer":
        recipient_id = ctx.customer_id

    sent_message = ctx.outbound_message
    if not recipient_id:
        if ctx.recipient_lower == "logistics":
            logger.warning(
                "central_outbound | logistics recipient but no party id (set logistic on inbound or process.logistic_id)"
            )
        elif ctx.recipient_lower not in ("vendor", "customer"):
            logger.info(
                "central_outbound | no external delivery for recipient=%r (process_id=%s) — treated as a no-op",
                ctx.recipient_lower,
                ctx.process_id,
            )
        return sent_message

    msg = ctx.outbound_message
    if ctx.recipient_lower in ("vendor", "logistics") and (
        ctx.business_id
        or ctx.customer_id
        or ctx.product_name
        or ctx.order_id
        or ctx.process_id
    ):
        parts: List[str] = []
        if ctx.business_id:
            parts.append(f"Vendor: {ctx.business_id}")
        if ctx.customer_id:
            parts.append(f"Customer: {ctx.customer_id}")
        if ctx.product_name:
            parts.append(f"Product: {ctx.product_name}")
        if ctx.process_id:
            parts.append(f"Process: {ctx.process_id}")
        if ctx.task_type_label:
            parts.append(f"Task: {ctx.task_type_label}")
        order_num = ctx.order_id
        if order_num:
            parts.append(f"Order: {order_num}")
        if parts:
            msg = f"[{' | '.join(parts)}] {ctx.outbound_message}"

    sent_message = msg
    inbox_payload: Dict[str, Any] = {
        "message": msg,
        "sender": ctx.response_sender,
        "recipient": ctx.response_recipient,
        "process_id": ctx.process_id,
        "task_type": ctx.task_type_label,
    }
    if ctx.customer_id and ctx.recipient_lower in ("vendor", "logistics"):
        inbox_payload["customer_id"] = ctx.customer_id
    if ctx.product_name:
        inbox_payload["product_name"] = ctx.product_name
    if ctx.order_id:
        inbox_payload["order_id"] = ctx.order_id
    if ctx.business_id:
        inbox_payload["business_id"] = ctx.business_id

    logger.info(
        "central_agent | inbox_push | recipient_id=%s sender=%s process_id=%s order_id=%s",
        recipient_id,
        ctx.response_sender,
        ctx.process_id or "",
        ctx.order_id or "",
    )
    ok = await push_to_inbox_with_retry(recipient_id, inbox_payload, retries=3)
    if not ok:
        logger.error(
            "central_agent | inbox_push_failed_after_retries | recipient_id=%s process_id=%s order_id=%s",
            recipient_id,
            ctx.process_id or "",
            ctx.order_id or "",
        )

    if ctx.recipient_lower == "vendor" and ctx.business_id:
        await append_inbox_turn_to_party_state(ctx.business_id, msg)
    elif ctx.recipient_lower == "logistics" and recipient_id:
        await append_inbox_turn_to_party_state(recipient_id, msg)
    elif ctx.recipient_lower == "customer" and ctx.customer_id and ctx.business_id:
        await append_inbox_turn_to_customer_pair(ctx.customer_id, ctx.business_id, msg)

    if ctx.recipient_lower in ("vendor", "logistics"):
        from backend.chatbot.utils.agent_trace_stdout import (
            agent_stdout,
            format_message_history_for_stdout,
        )

        party_key = ctx.business_id if ctx.recipient_lower == "vendor" else recipient_id
        if party_key:
            from backend.db.cache_utils import get_party_state

            st = await get_party_state(str(party_key))
            agent_stdout(
                f"party_state chat_history AFTER central → {ctx.recipient_lower} (party_id={party_key})",
                format_message_history_for_stdout(st.get("chat_history")),
            )

    return sent_message


async def polish_central_message_for_customer(
    draft_message: str,
    *,
    customer_id: str,
    business_id: str,
    pair_state: Dict[str, Any],
) -> str:
    """Turn a central draft into customer-channel text via conversational_agent; persists the turn on the pair state."""
    from backend.chatbot.agents.conversational_agent import run_conversational_agent
    from backend.db.cache_utils import modify_user_state
    from backend.db.db_utils import get_business_info
    from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart

    d = (draft_message or "").strip()
    if not d:
        return draft_message or ""
    st = pair_state
    if not st.get("business_information"):
        bi0 = await get_business_info(business_id) or {}
        if bi0:
            st["business_information"] = dict(bi0)
    bi = st.get("business_information") or {}
    chat_history = list(st.get("chat_history") or [])
    um = f"Draft to polish (keep all facts):\n{d}"
    out = await run_conversational_agent(
        user_message=um,
        chat_history=chat_history,
        user_id=customer_id,
        business_id=business_id,
        user_state=st,
        business_name=(bi or {}).get("name"),
        polish_only=True,
    )
    text = (out or "").strip() or d
    chat_history.append(ModelResponse(parts=[TextPart(content=text)]))
    st["chat_history"] = chat_history
    await modify_user_state(customer_id, business_id, st)
    return text
