"""
Business Chat Interface - Handles business owner interactions
Converted to Pydantic AI with analytics and inventory tools
"""
import re
import uuid
import logfire
from fastapi import BackgroundTasks
from typing import Any, Dict, List, Literal, Optional, Tuple, Union
from pydantic_ai import RunContext
from backend.chatbot.agents.base_agent import BaseAgent
from backend.chatbot.agents.central_agent import (
    run_central_agent,
    _catalog_add_row,
    _catalog_set_price_row,
    _catalog_set_stock_row,
)
from backend.chatbot.agents.central_agent_utils import create_structured_input
from backend.db.cache_utils import (
    get_party_state,
    get_user_state,
    modify_party_state,
    modify_user_state,
    party_state_lock,
    user_state_lock,
)
from backend.db.db_utils import (
    get_business_analytics,
    get_business_info,
    get_inventory,
    get_low_stock_products,
    pick_random_logistics_company_id,
)
from backend.struct import (
    BusinessRequest,
    CentralAgentInput,
    Customer,
    EntityType,
    Logistics,
    Product,
    TaskType,
    Vendor,
)
from backend.chatbot.agents.central_agent_utils import ensure_central_process
from pydantic import BaseModel, Field
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    TextPart,
    UserPromptPart,
)

from backend.logging_config import get_logger
from backend.chatbot.utils.agent_trace_stdout import agent_stdout, format_message_history_for_stdout
from backend.chatbot.utils.history_summarizer import maybe_summarize_chat_history

logger = get_logger(__name__)

_VENDOR_TAG_RE = re.compile(
    r"Vendor:\s*([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})",
    re.IGNORECASE,
)


def extract_vendor_id_from_thread_text(text: str) -> Optional[str]:
    """Parse `Vendor: <uuid>` from central/inbox metadata brackets."""
    if not text or not text.strip():
        return None
    m = _VENDOR_TAG_RE.search(text)
    return str(m.group(1)) if m else None


def latest_vendor_id_from_chat_history(history: Any) -> Optional[str]:
    """Walk newest-first; return first vendor UUID found in any message part."""
    if not history:
        return None
    for msg in reversed(history):
        parts = getattr(msg, "parts", None)
        if not parts:
            continue
        for part in parts:
            c = getattr(part, "content", None)
            if isinstance(c, str):
                vid = extract_vendor_id_from_thread_text(c)
                if vid:
                    return vid
    return None


async def _get_business_info(business_id: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Load business row and `business_type`."""
    row = await get_business_info((business_id or "").strip())
    if not row:
        return None, None
    bt = (row.get("business_type") or "").strip()
    return row, bt or None 

class BusinessChatDeps(BaseModel):
    """Dependencies for business chat"""
    business_id: str
    logistic_id: str = ""
    customer_id: Optional[str] = None

class ReplyContext(BaseModel):
    """Reply context extracted from chat history when business is replying about a customer/order/product."""
    customer_id: str
    process_id: Optional[str] = None
    task_type: Optional[str] = None
    vendor_id: str = Field(
        default="",
        description=(
            "Store (vendor) business UUID for this thread. **Logistics:** copy from `Vendor: <uuid>` "
            "in the latest central agent / inbox message. **Vendor:** may be left empty; routing uses the party id."
        ),
    )
    logistic_id: Optional[str] = None # Logistics/logistics company for the order (when business replying)
    product_id: str
    product_name: str
    order_id: Optional[str] = None
    order_number: Optional[str] = None
    price: Optional[float] = None
    quantity: Optional[int] = None
    product_attributes: Optional[Dict[str, Any]] = None


class OutputBusinessChat(BaseModel):
    """Output for business chat. Agent extracts reply_context from chat history when applicable."""
    for_central_agent: bool = Field(
        default=False,
        description=(
            "True when this turn must go through the central coordinator (inbox replies, shopper updates, vendor↔logistics relay). "
            "MUST be True if recipient is Customer—there is no direct channel to the shopper from this chat."
        ),
    )
    reply_context: Optional[ReplyContext] = Field(
        default=None,
        description="Required for inbox/coordination turns: customer_id, process_id from thread markers; vendor_id should match the store UUID when known. Must be accurate and precise.",
    )
    confidence_score: Optional[float] = Field(
        default=None,
        description="Confidence score for the reply context. 0.0 to 1.0.",
    )
    recipient: EntityType = Field(
        description="Who should receive the **next** coordination step: Customer | Vendor | Logistics | Agent. set to None if you are responding directly back to the entity you are chatting with."
    )
    response: Optional[str] = Field(
        default=None,
        description="If for_central_agent True: exact message for central agent to relay (e.g. to Customer). If appropriate message for vendor/logistics UI based on the context.",
    )


def _forward_via_central(out: OutputBusinessChat) -> bool:
    """Shopper-bound turns must use central; the model sometimes omits for_central_agent."""
    if out.for_central_agent:
        return True
    rc = out.reply_context
    if out.recipient == EntityType.CUSTOMER and rc and (rc.customer_id or "").strip():
        return True
    return False


# Initialize business chat agent
business_chat_agent_base = BaseAgent(
    system_prompt="""**ROLE AND PURPOSE**
You are ottobiz AI, the primary AI Business Assistant dedicated to serving businesses (i.e **Vendors** (`vendor_id`) and **Logistics Providers**). You have a dual logic flow mode: 
1. providing direct business operational support
2. acting as a communications bridge between vendors/logistic businesses and external agents/customers.

**MODE 1: DIRECT BUSINESS SUPPORT (Default Mode)**
You provide direct, localized assistance to vendor or logistic businesses queries or questions.
* **Capabilities:** Business analytics, supply chain predictions, inventory management, updating their product in the database (price, stock, new SKUs), low stock alerts, and executing system updates (e.g., updating product stock quantities or prices).
* **Inventory writes:** Use **`mutate_vendor_catalog`** (`set_price`, `set_stock`, `add`) only here—when the vendor/store is **directly** managing catalog rows for their own `business_id`. **Do not** call it on cross-party / inbox / coordination turns (Mode 2); those must set **`for_central_agent = True`** so the central agent applies approved catalog updates on the customer–vendor session.
* **Inventory read:** Call `get_inventory_info` at most once per user question; derive rankings (e.g. best-stocked item) from the returned list—do not call it again in the same reply loop.
* **Action:** Process these requests directly within the current chat context.

**MODE 2: CROSS-PARTY COORDINATION (Thread Handoff)**
Sometimes, the business's message is a response to a third-party's (external agents) message (which contains a Process ID). This means the business (vendor/logistics) needs to coordinate with another party (e.g. customer, another vendor, logistics company). 
In this case, you will act as an effective relay, passing the message to the relevant party (e.g. customer, vendor, logistics or AI agent) through the central agent.
Inbox lines use markers like **`Vendor:`** (store UUID), **`Customer:`**, **`Product:`**, **`Process:`**, **`Task:`**. You MUST copy **`Vendor: <uuid>`** into **`reply_context.vendor_id`** when you are a **logistics** provider replying—this UUID is the customer–vendor session key central uses. If you omit it, copy it from the newest visible bracket line in chat history.

**Hard rules**
- If `recipient` is **Customer**→ set **`for_central_agent = True`**, fill **ReplyContext** (`customer_id`, `process_id`, `product_name` from the thread), and put the shopper-facing text in **`response`** (central relays it). **Never** call **`mutate_vendor_catalog`** on those turns.
- If the vendor/logistics only answers internal business ops with no cross-party relay → `for_central_agent = False`, recipient= None.

Optional `task_type` when the thread names it; `recipient` Vendor/Logistics is for coordination between those parties (still `for_central_agent = True`).""",
    deps_type=BusinessChatDeps,
    output_type=OutputBusinessChat
)

business_chat_agent = business_chat_agent_base.agent


# Business Analytics Tool
@business_chat_agent.tool
async def get_business_analytics_tool(
    ctx: RunContext[BusinessChatDeps],
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
) -> Dict[str, Any]:
    """Sales/order aggregates and up to 5 top products (compact)."""
    try:
        data = await get_business_analytics(ctx.deps.business_id, start_date=start_date, end_date=end_date)
        tp = data.get("top_products") or []
        if isinstance(tp, list) and len(tp) > 5:
            data = {**data, "top_products": tp[:5]}
        return data
    except Exception as e:
        return {"error": f"Analytics unavailable: {e}", "sales": {}, "orders": {}, "top_products": []}


# Inventory Management Tools
def _slim_inventory_row(r: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": str(r.get("id", "")),
        "name": r.get("name"),
        "sku": r.get("sku"),
        "price": r.get("price"),
        "currency": r.get("currency"),
        "stock_quantity": r.get("stock_quantity"),
        "category": r.get("category"),
    }


@business_chat_agent.tool
async def get_inventory_info(
    ctx: RunContext[BusinessChatDeps]
) -> List[Dict[str, Any]]:
    """Returns the **complete** current inventory (up to 50 products). Each row contains name,
    sku, price, currency, stock_quantity, and category. This is a single-shot read — do not call
    it again after receiving results; derive all answers (most stocked, low stock, totals, etc.)
    directly from the returned list."""
    try:
        rows = await get_inventory(ctx.deps.business_id)
        return [_slim_inventory_row(dict(x)) for x in (rows or [])[:50]]
    except Exception as e:
        return [{"error": f"Inventory unavailable: {e}"}]

@business_chat_agent.tool
async def mutate_vendor_catalog(
    ctx: RunContext[BusinessChatDeps],
    action: Literal["set_price", "set_stock", "add"],
    product_id: Optional[str] = None,
    name: Optional[str] = None,
    price: Optional[float] = None,
    stock_quantity: Optional[int] = None,
    description: str = "",
    category: str = "",
    product_attributes: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Update this store's catalog in the database.

    **Mode 1 only** — the vendor is **directly** editing their own catalog in this chat. Use
    ``set_price`` (``product_id``, ``price``), ``set_stock`` (``product_id``, ``stock_quantity``),
    or ``add`` (``name``, ``price``; optional ``stock_quantity``, ``description``, ``category``, ``product_attributes``).

    **Do not call** when the turn is cross-party coordination or any path that sets
    ``for_central_agent = True`` (inbox / relay to customer or central): state the change in
    ``response`` and hand off so central applies it on the customer–vendor session.
    """
    bid = (ctx.deps.business_id or "").strip()
    if not bid:
        return {"error": "No business context"}

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
    return await _catalog_add_row(
        bid, nm, price, sq, description, category, product_attributes
    )


@business_chat_agent.tool
async def get_low_stock_alerts(
    ctx: RunContext[BusinessChatDeps],
    threshold: int = 10
) -> List[Dict[str, Any]]:
    """Products at or below stock threshold (compact, capped)."""
    try:
        rows = await get_low_stock_products(ctx.deps.business_id, threshold)
        return [_slim_inventory_row(dict(x)) for x in (rows or [])[:25]]
    except Exception as e:
        return [{"error": f"Low stock check unavailable: {e}"}]

async def _get_logistic_id_for_business(
    business_id: Union[str, uuid.UUID],
    user_state: Dict[str, Any],
) -> Tuple[Optional[str], Dict[str, Any]]:
    """Resolve logistics UUID for vendor party state: party cache → DB partner → random registry."""
    bid = str(business_id).strip()
    if not bid:
        return None, user_state

    if (user_state.get("delivery_route") or "").lower() == "vendor":
        user_state.pop("logistic_id", None)
        return None, user_state

    # for key, src in (("assigned_logistic_id", "party_assigned"), ("logistic_id", "party_logistic_id")):
    lid = user_state.get("logistic_id")
    if lid:    
        return lid, user_state

    row = await get_business_info(bid) or {}
    partner = row.get("partner_logistic_id")
    if partner:
        lid = str(partner).strip()
        user_state["logistic_id"] = lid
        return lid, user_state
    
    return lid, user_state

async def business_chat(
    business_request: BusinessRequest,
    background_tasks: BackgroundTasks,
    debug: bool = False
) -> Optional[str]:
    """
    Handle business/logistics chat. Agent extracts reply context from chat history.
    """
    state_key_id = (business_request.business_id or "").strip()
    if not state_key_id:
        raise ValueError("Not a vaild business. Valid business_id is required")
    with logfire.span("business_chat", party_id=state_key_id):
        async with party_state_lock(state_key_id):
            return await _business_chat_inner(business_request, background_tasks, debug, state_key_id)


async def _business_chat_inner(
    business_request,
    background_tasks: BackgroundTasks,
    debug: bool,
    state_key_id: str,
) -> Optional[str]:
    try:
        business_user_state = await get_party_state(state_key_id) or {}
        if "chat_history" not in business_user_state:
            business_user_state["chat_history"] = []

        business_info, business_type = await _get_business_info(state_key_id)
        business_is_logistics = (business_type or "").lower() == "logistics"
        if business_is_logistics:
            logistic_id: Optional[str] = state_key_id
        else:
            logistic_id, business_user_state = await _get_logistic_id_for_business(
                state_key_id, business_user_state
            )
            await modify_party_state(state_key_id, business_user_state)

        chat_history = list(business_user_state.get("chat_history", []))
        existing_summary = business_user_state.get("chat_history_summary")
        chat_history, new_summary, _ = await maybe_summarize_chat_history(
            chat_history, existing_summary=existing_summary,
        )
        if new_summary:
            business_user_state["chat_history_summary"] = new_summary
            business_user_state["chat_history"] = chat_history

        _hist_vendor_id = latest_vendor_id_from_chat_history(chat_history)
        _msg_vendor_id = extract_vendor_id_from_thread_text(business_request.message or "")

        agent_stdout(
            f"business_chat chat_history BEFORE agent.run (party_id={state_key_id})",
            format_message_history_for_stdout(chat_history),
        )
        agent_stdout("business_chat_agent input", business_request.message)
        ## add additonal context as instructions conatin information about the business you are chatting with using the state_key_id which should be a business_id
        business_info = (
            f"Business information: {business_info}"
            if business_is_logistics
            else f"Business information: {business_info}, linked_logistics_id: {logistic_id or 'none'}"
        )
        
        result = await business_chat_agent.run(
            business_request.message,
            deps=BusinessChatDeps(
                business_id=state_key_id,
                logistic_id=logistic_id or "",
            ),
            message_history=chat_history,
            instructions=business_info,
        )
        _bc_out = result.output
        coerced_central = _forward_via_central(_bc_out) and not _bc_out.for_central_agent
        if coerced_central:
            logger.info(
                "business_chat | routing_fix recipient=Customer with reply_context → central "
                "(model had for_central_agent=False)"
            )

        agent_stdout(
            "business_chat_agent output",
            f"for_central_agent={_bc_out.for_central_agent} forward_via_central={_forward_via_central(_bc_out)}\n"
            f"recipient={_bc_out.recipient}\n"
            f"reply_context={_bc_out.reply_context}\n"
            f"response={_bc_out.response}",
        )

        if not _forward_via_central(_bc_out):
            business_user_state["chat_history"].append(
                ModelRequest(parts=[UserPromptPart(content=business_request.message)])
            )
            response = result.output.response
            business_user_state["chat_history"].append(
                ModelResponse(parts=[TextPart(content=response)])
            )
            await modify_party_state(state_key_id, business_user_state)
            agent_stdout(
                f"business_chat chat_history AFTER persist (party_id={state_key_id})",
                format_message_history_for_stdout(business_user_state.get("chat_history")),
            )
            return response

        rc = _bc_out.reply_context
        msg = _bc_out.response

        _conf = _bc_out.confidence_score
        if not rc or not rc.customer_id or (
            _conf is not None and _conf < 0.5
        ):
            business_user_state["chat_history"].append(
                ModelRequest(parts=[UserPromptPart(content=business_request.message)])
            )
            response = "I need more context. Which customer or order is this about? Please reply to the specific inbox message. Please ensure you're replying in the context of an inbox message."
            business_user_state["chat_history"].append(
                ModelResponse(parts=[TextPart(content=response)])
            )
            await modify_party_state(state_key_id, business_user_state)
            agent_stdout(
                f"business_chat chat_history AFTER persist (party_id={state_key_id})",
                format_message_history_for_stdout(business_user_state.get("chat_history")),
            )
            return response

        biz_id: str
        if business_is_logistics:
            biz_id = (
                (rc.vendor_id or "").strip()
                or (_hist_vendor_id or "").strip()
                or (_msg_vendor_id or "").strip()
            )
            if not biz_id:
                business_user_state["chat_history"].append(
                    ModelRequest(parts=[UserPromptPart(content=business_request.message)])
                )
                response = (
                    "I could not determine which store this belongs to. Reply in context of an inbox message "
                    "that includes `Vendor: <uuid>` (or paste that line), so central can load the right customer session."
                )
                business_user_state["chat_history"].append(
                    ModelResponse(parts=[TextPart(content=response)])
                )
                await modify_party_state(state_key_id, business_user_state)
                agent_stdout(
                    f"business_chat chat_history AFTER persist (party_id={state_key_id})",
                    format_message_history_for_stdout(business_user_state.get("chat_history")),
                )
                return response
        else:
            biz_id = (state_key_id or "").strip()

        async with user_state_lock(rc.customer_id, biz_id):
            central_user_state = await get_user_state(rc.customer_id, biz_id) or {}
            tt = TaskType.UNKNOWN
            if rc.task_type:
                for t in TaskType:
                    if t.value == rc.task_type or t.name == rc.task_type:
                        tt = t
                        break
            pid = (rc.process_id or "").strip()
            if not pid:
                pid = await ensure_central_process(
                    central_user_state,
                    task_type=tt,
                    customer_id=rc.customer_id,
                    vendor_id=biz_id,
                    product_name=rc.product_name or "",
                    order_id=rc.order_id,
                )
            await modify_user_state(rc.customer_id, biz_id, central_user_state)

            if business_is_logistics:
                _logistic_uuid = (state_key_id or "").strip()
            else:
                _logistic_uuid = (rc.logistic_id or logistic_id or "").strip()
            logistic: Optional[Logistics] = (
                Logistics(id=_logistic_uuid, name=None, phone=None) if _logistic_uuid else None
            )

            agent_input = await create_structured_input(
                sender="Logistics" if business_is_logistics else "Vendor",
                recipient=_bc_out.recipient,
                message=msg,
                customer=Customer(id=(rc.customer_id or "").strip()),
                business=Vendor(id=(biz_id or "").strip() or state_key_id),
                logistic=logistic,
                product=Product(id=rc.product_id or "", name=rc.product_name or "", quantity=rc.quantity or 1, price=rc.price or 0, metadata=rc.product_attributes or None, has_paid=False if not rc.order_id else True) if rc.product_name else None,
                order_id=rc.order_id or None,
                process_id=pid,
                task_type=tt,
            )

            _ttp = tt.value if hasattr(tt, "value") else str(tt)
            _mp = (msg or "")[:2000]
            logger.info(
                "business_chat_central_forward | party_id=%s customer_id=%s process_id=%s task_type=%s "
                "recipient=%s message_preview=%r",
                state_key_id,
                rc.customer_id,
                pid,
                _ttp,
                _bc_out.recipient,
                _mp,
            )

            logfire.info(
                "business_chat_central_forward",
                party_id=state_key_id,
                customer_id=rc.customer_id,
                process_id=pid,
                task_type=_ttp,
                recipient=str(_bc_out.recipient),
                message_preview=_mp,
            )

            await run_central_agent(
                agent_input,
                central_user_state,
                vendor_only=True,
                debug=debug,
                caller_agent="business_chat_interface",
            )

        # Reload so party chat_history includes central appends; then persist this user turn only.
        business_user_state = await get_party_state(state_key_id) or business_user_state
        
        _pn = rc.product_name or ""
        placeholder_message = (
            f"Message  for: \n process-id : {pid}\n customer-id: {rc.customer_id}\n "
            f"product: {_pn}.\n Coordinating with relevant parties."
        )
        
        business_user_state.setdefault("chat_history", [])
        business_user_state["chat_history"].append(
            ModelRequest(parts=[UserPromptPart(content=business_request.message)])
        )
        business_user_state["chat_history"].append(
            ModelResponse(parts=[TextPart(content=placeholder_message)])
        )
        
        await modify_party_state(state_key_id, business_user_state)
        
        agent_stdout(
            f"business_chat chat_history AFTER run_central_agent + persist (party_id={state_key_id})",
            format_message_history_for_stdout(business_user_state.get("chat_history")),
        )
        return placeholder_message
    
    except ValueError:
        raise
    except Exception as e:
        logger.exception("business_chat failed | party_id=%s error=%s", state_key_id, e)
        return "An error occurred while processing your message."