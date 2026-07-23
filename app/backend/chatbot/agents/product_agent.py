"""
Product Agent - Handles product inquiries and purchases
Converted to pydantic_ai
"""

import uuid
from typing import Any, Dict, List, Optional

from pydantic import BaseModel
from pydantic_ai import RunContext

from backend.chatbot.agents.central_agent import run_central_agent
from backend.chatbot.agents.central_agent_utils import (
    create_structured_input,
    ensure_central_process,
)
from backend.chatbot.utils.agent_utils import (
    format_handoff_process_context,
    get_or_create_user_state,
    get_process_snapshot,
    save_user_state,
)
from backend.db.cache_utils import get_user_state, modify_user_state
from backend.config import BASE_URL, PAYSTACK_DEFAULT_CURRENCY
from backend.db.db_utils import get_business_info, get_product_by_id, get_products
from backend.payments.paystack_client import (
    amount_to_kobo,
    initialize_transaction,
    persist_paystack_reference,
)
from backend.payments.demo_override import get_override as get_demo_payment_override
from backend.modules.products import get_product_images, get_products_by_business
from backend.struct import Customer, EntityType, Product, TaskType, Vendor

from .base_agent import BaseAgent
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    TextPart,
    UserPromptPart,
)

class ProductInfo(BaseModel):
    """Product information structure"""

    product_name: str
    price: float
    items_in_stock: int
    description: Optional[str] = None
    category: Optional[str] = None


class ProductAgentDeps(BaseModel):
    """Dependencies for product agent"""

    user_id: str
    business_id: str
    chat_history: Optional[List[Any]] = None
    process_id: Optional[str] = None


# Initialize product agent
product_agent_base = BaseAgent(
    system_prompt="""You are the expert product specialist and sales lead for this storefront. Your goal is to provide accurate stock information, handle purchase intent with precision, and bridge the gap between the customer and the vendor when items are missing*

**Workflow**
1. **Verify First**: Always call `get_product_info` before answering. Never guess stock or price.
2. **Browsing**: If no product is named, list up to 8 items from the tool (Format: **Name** - **Price**). Hide IDs and stock counts.
3. **Closing the Sale**: Before payment, re-call `get_product_info` to confirm live price/stock. 
    * Call `fetch_payment_link`. On success, provide the **link** and **reference code**.
    * If it fails, call `get_business_payment_info` and present bank transfer details.
4. **Zero Matches**: If the specific model/color is missing, call `notify_vendor` immediately with the user's request. Tell the customer you're checking with the store; suggest only **one** relevant alternative if it exists.
5. **System Gaps**: If the catalog or payment setup is missing, call `notify_vendor`. Keep the user in-chat; never redirect to external sites or email.

**Tone**
Expert, concise, and confident. Use short chat lines. Acknowledge buying signals naturally..""",
    deps_type=ProductAgentDeps,
)

product_agent = product_agent_base.agent


@product_agent.tool
async def get_product_info(
    ctx: RunContext[ProductAgentDeps], product_name: Optional[str] = None, category: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Up to 8 matching products: id, name, price, stock, category, short description; image_urls only for the first row (max 2 URLs)."""
    try:
        products = await get_products(
            business_id=ctx.deps.business_id,
            name=product_name if product_name else None,
            category=category,
            limit=8,
        )
        out: List[Dict[str, Any]] = []
        for i, p in enumerate(products or []):
            slim: Dict[str, Any] = {
                "id": str(p.get("id", "")),
                "name": p.get("name"),
                "price": p.get("price"),
                "currency": p.get("currency"),
                "stock_quantity": p.get("stock_quantity"),
                "category": p.get("category"),
            }
            desc = (p.get("description") or "").strip()
            if desc:
                slim["description"] = desc[:240]
            if i == 0 and p.get("id"):
                imgs = await get_product_images(p["id"])
                if imgs:
                    slim["image_urls"] = imgs[:2]
            out.append(slim)
        return out
    except Exception as e:
        return [{"error": f"Could not fetch products: {e}"}]


@product_agent.tool
async def fetch_payment_link(
    ctx: RunContext[ProductAgentDeps],
    product_id: Optional[str] = None,
    amount: Optional[float] = None,
) -> Dict[str, Any]:
    """Create a Paystack payment page for this vendor. Returns payment_url, reference, and ok flag; on failure ok=false."""
    if await get_demo_payment_override(ctx.deps.user_id):
        return {
            "ok": False,
            "payment_url": None,
            "reference": None,
            "message": "Online checkout is disabled in demo mode. Use bank transfer details instead.",
        }
    user_state = await get_user_state(ctx.deps.user_id, ctx.deps.business_id) or {}
    biz = user_state.get("business_information") or {}
    secret = (biz.get("paystack_secret_key") or "").strip()
    if not secret:
        bi = await get_business_info(ctx.deps.business_id)
        if bi:
            user_state["business_information"] = bi
            biz = bi
            secret = (biz.get("paystack_secret_key") or "").strip()
    if not secret:
        return {
            "ok": False,
            "payment_url": None,
            "reference": None,
            "message": "Paystack is not configured for this store (no secret key). Use bank transfer.",
        }

    amt_major: Optional[float] = None
    pid = (product_id or "").strip() or None
    if amount is not None and float(amount) > 0:
        amt_major = float(amount)
    elif pid:
        row = await get_product_by_id(pid)
        if row and row.get("price") is not None:
            amt_major = float(row["price"])
    if amt_major is None or amt_major <= 0:
        return {
            "ok": False,
            "payment_url": None,
            "reference": None,
            "message": "Need a valid amount or product_id with a price.",
        }

    reference = f"OBZ{uuid.uuid4().hex[:20]}"
    email = (user_state.get("customer_email") or "").strip() or f"{ctx.deps.user_id}@customers.ottobiz.app"
    callback_url = f"{BASE_URL.rstrip('/')}/api/v1/payments/paystack/callback"
    meta = {
        "user_id": str(ctx.deps.user_id),
        "business_id": str(ctx.deps.business_id),
        "product_id": str(pid or ""),
    }
    init = await initialize_transaction(
        secret_key=secret,
        email=email,
        amount_kobo=amount_to_kobo(amt_major),
        reference=reference,
        callback_url=callback_url,
        metadata=meta,
        currency=PAYSTACK_DEFAULT_CURRENCY,
    )
    if not init.get("ok"):
        return {
            "ok": False,
            "payment_url": None,
            "reference": None,
            "message": init.get("message", "Could not start Paystack checkout."),
        }

    ref = str(init.get("reference") or reference)
    url = init.get("authorization_url")
    pending = user_state.setdefault("pending_paystack", {})
    pending[ref] = {
        "amount": amt_major,
        "product_id": pid,
        "payment_url": url,
        "currency": PAYSTACK_DEFAULT_CURRENCY,
    }
    user_state["last_paystack_reference"] = ref
    await modify_user_state(ctx.deps.user_id, ctx.deps.business_id, user_state)
    await persist_paystack_reference(ref, ctx.deps.user_id, ctx.deps.business_id, pid, amt_major)

    return {
        "ok": True,
        "payment_url": url,
        "reference": ref,
        "amount": amt_major,
        "currency": PAYSTACK_DEFAULT_CURRENCY,
        "message": "Share the link with the customer and tell them the reference for payment confirmation.",
    }


@product_agent.tool
async def get_business_payment_info(
    ctx: RunContext[ProductAgentDeps],
) -> Dict[str, str]:
    """Get business payment information (bank account details)"""
    override = await get_demo_payment_override(ctx.deps.user_id)
    if override:
        return {
            "bank_name": override.get("bank_name", ""),
            "bank_account_number": override.get("bank_account_number", ""),
            "bank_account_name": override.get("bank_account_name", ""),
            "paystack_public_key": "",
        }

    user_state = await get_user_state(ctx.deps.user_id, ctx.deps.business_id) or {}
    business_info = user_state.get("business_information", {})

    return {
        "bank_name": business_info.get("bank_name", ""),
        "bank_account_number": business_info.get("bank_account_number", ""),
        "bank_account_name": business_info.get("bank_account_name", ""),
        "paystack_public_key": business_info.get("paystack_public_key", ""),
    }

@product_agent.tool
async def modify_task_type_for_process_id(
    ctx: RunContext[ProductAgentDeps],
    process_id: str,
    task_type: TaskType,
) -> Dict[str, Any]:
    """Modify task type for the current (existing) process. Use this to change the task type from PRODUCT_ENQUIRY to payment verification once product has been purchased."""
    us = await get_user_state(ctx.deps.user_id, ctx.deps.business_id) or {}
    pid = await ensure_central_process(
        us,
        task_type=task_type or TaskType.PRODUCT_ENQUIRY,
        customer_id=ctx.deps.user_id,
        vendor_id=ctx.deps.business_id,
        process_id=process_id,
    )
    proc = us.get("processes", {}).get(pid)
    if not isinstance(proc, dict):
        return {"status": "error", "message": f"Process {pid!r} not found."}
    proc["task_type"] = task_type
    us["processes"][pid] = proc
    await modify_user_state(ctx.deps.user_id, ctx.deps.business_id, us)
    return {"status": "success", "message": f"Task type modified to {task_type.value}."}
        
        
        
@product_agent.tool
async def notify_vendor(
    ctx: RunContext[ProductAgentDeps],
    message: str,
    product_name: str,
    price: float,
    quantity: int = 1,
    task_type: Optional[TaskType] = None,
    process_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Pushes a request to the **vendor inbox** via the central agent. Use when: catalog/database (get_product_info tool) has no match for what the customer asked, stock/price unknown, or payment setup missing. Pass a single clear sentence for `message` (what the customer wants + any specs)."""
    try:
        user_state = await get_user_state(ctx.deps.user_id, ctx.deps.business_id) or {}
        pid = await ensure_central_process(
            user_state,
            task_type=task_type or TaskType.PRODUCT_ENQUIRY,
            customer_id=ctx.deps.user_id,
            vendor_id=ctx.deps.business_id,
            product_name=product_name,
            process_id=process_id or ctx.deps.process_id,
        )
        agent_input = await create_structured_input(
            sender=EntityType.AGENT,
            recipient=EntityType.VENDOR,
            message=message,
            customer=Customer(id=ctx.deps.user_id),
            business=Vendor(id=ctx.deps.business_id),
            product=Product(id="", name=product_name, quantity=quantity, price=price) if product_name else None,
            process_id=pid,
            task_type=TaskType.PRODUCT_ENQUIRY,
        )
        await run_central_agent(
            event_message=agent_input,
            user_state=user_state,
            caller_agent="product_agent",
        )
        return {"status": "vendor_notified", "message": "Message sent to vendor. The customer will be updated when the vendor responds."}
    except Exception as e:
        return {"status": "error", "message": f"Could not reach vendor: {e}"}


async def run_product_agent(
    customer_message: str,
    product_name: str,
    product_category: str,
    intent: str = "enquiry",
    user_id: str = "",
    business_id: str = "",
    user_state: Optional[Dict[str, Any]] = None,
    api_key: Optional[str] = None,
    product_attributes_json: Optional[str] = None,
    debug: bool = False,
    append_chat_history: bool = True,
    instructions: Optional[str] = None,
    process_id: Optional[str] = None,
) -> tuple[str, Dict[str, Any]]:
    """
    Run product agent to handle customer product inquiries.

    Args:
        customer_message: Customer's message
        product_name: Name of the product inquired about
        product_category: Category of the product
        intent: Customer intent (enquiry, purchase)
        user_id: User ID
        business_id: Business ID
        user_state: Optional user state (will be fetched if not provided)
        api_key: Optional API key
        debug: Debug mode

    Returns:
        Tuple of (response_message, updated_user_state)
    """
    if not user_state:
        user_state = await get_or_create_user_state(user_id, business_id)

    # Get business info for dynamic system prompt
    business_info = user_state.get("business_information", {})
    if not business_info:
        from backend.db.db_utils import get_business_info

        business_info = await get_business_info(business_id) or {}
        user_state["business_information"] = business_info

    # Get chat history
    chat_history = user_state.get("chat_history", [])

    # Build dynamic system prompt with business account details
    # Demo mode: a visitor-supplied account (see payments/demo_override.py) takes
    # priority over the vendor's real bank details, and disables the real
    # Paystack link — see fetch_payment_link — so no real money can move.
    demo_override = await get_demo_payment_override(user_id)
    payment_source = demo_override or business_info
    dynamic_prompt = ""
    if payment_source:
        bank_details = []
        if payment_source.get("bank_name"):
            bank_details.append(f"Bank Name: {payment_source.get('bank_name')}")
        if payment_source.get("bank_account_name"):
            bank_details.append(f"Account Name: {payment_source.get('bank_account_name')}")
        if payment_source.get("bank_account_number"):
            bank_details.append(f"Account Number: {payment_source.get('bank_account_number')}")

        if bank_details:
            dynamic_prompt = "\n\n**Business Payment Details:**\n" + "\n".join(bank_details)
            if demo_override:
                dynamic_prompt += "\n\nThis is demo mode: only bank transfer to this account is available (no payment link)."
            else:
                dynamic_prompt += "\n\nIf payment link is not available, provide these bank details for bank transfer."

    proc = get_process_snapshot(user_state, process_id)
    if proc and (not product_name or product_name.strip().upper() == "NONE") and proc.get("product_name"):
        product_name = str(proc.get("product_name") or "").strip()

    # Prepare prompt
    prompt_parts = [f"Customer message: {customer_message}"]
    if proc and (process_id or "").strip():
        prompt_parts.append("\n" + format_handoff_process_context(str(process_id).strip(), proc))
    if product_attributes_json and product_attributes_json.strip():
        prompt_parts.append(
            f"\nProduct image / attribute hints (JSON): {product_attributes_json.strip()}"
        )

    # Always fetch products for this vendor — use product_name filter when specific, else fetch all
    name_filter = product_name if product_name.strip() != "NONE" else None
    cache_key = product_name if product_name.strip() != "NONE" else "__all__"
    products_cache = user_state.get("products", {})
    product_cache = products_cache.get(cache_key, {})

    if not product_cache.get("db_queried", False):
        try:
            products = await get_products(name=name_filter, category=product_category or None, business_id=business_id)
        except Exception:
            products = []
        import time
        product_cache = {"retrieved_results": products, "db_queried": True, "_ts": time.time()}
        user_state.setdefault("products", {})[cache_key] = product_cache

    products = product_cache.get("retrieved_results", [])

    if products:
        biz_cur = str(business_info.get("currency") or "").strip() or "NGN"
        products_info = "\n".join(
            [
                f"- {p.get('name', p.get('product_name', ''))}: {p.get('price', 0)} "
                f"{(p.get('currency') or '').strip() or biz_cur} "
                f"(Stock: {p.get('stock_quantity', p.get('items_left_in_stock', 0))})"
                for p in products[:10]
            ]
        )
        prompt_parts.append(f"\nVendor's products from database:\n{products_info}")
    else:
        prompt_parts.append("\nNo products found in this vendor's inventory.")

    if name_filter:
        prompt_parts.append(
            "\n**Rule:** If this list is empty OR no item matches the customer's exact product (model, color, storage, etc.), "
            "you MUST call `notify_vendor` with their exact request, then answer the customer briefly."
        )

    if intent == "purchase":
        prompt_parts.append(
            "\nCustomer intent: Purchase - call fetch_payment_link first. If ok=false, provide bank transfer details."
        )

    # Create dependencies
    deps = ProductAgentDeps(
        user_id=user_id or "",
        business_id=business_id or "",
        chat_history=chat_history,
        process_id=(process_id or "").strip() or None,
    )

    # Run agent with dynamic prompt
    full_prompt =  dynamic_prompt + "\n".join(prompt_parts) 

    # Session adjunct `instructions` (from orchestrator handoff) omits session product cache — specialist builds catalog lines above.
    run_kw: Dict[str, Any] = {}
    if instructions and instructions.strip():
        run_kw["instructions"] = instructions.strip()
    result = await product_agent.run(full_prompt, deps=deps, **run_kw)

    response = result.output

    if append_chat_history:
        user_state.setdefault("chat_history", []).extend([
            ModelRequest(parts=[UserPromptPart(content=customer_message)]),
            ModelResponse(parts=[TextPart(content=response)]),
        ])

    await save_user_state(user_id, business_id, user_state)

    return response, user_state
