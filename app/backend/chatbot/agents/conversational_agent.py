"""
Conversational agent — single orchestrator for the customer chat channel.
Delegates to specialists via tools. Orchestrator run passes session context (incl. product cache) via `instructions`;
specialist handoffs use slimmer profiles to avoid duplicating each agent's own prompt body.
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Dict, List, Optional, Literal, Union

from fastapi import BackgroundTasks
from pydantic import BaseModel, ConfigDict, Field
from pydantic_ai import RunContext

from backend.chatbot.agents.base_agent import BaseAgent
from backend.config import PRODUCTS_CACHE_TTL_HOURS
from backend.chatbot.utils.agent_trace_stdout import agent_stdout
from backend.chatbot.agents.central_agent_utils import apply_process_field_updates
from backend.db.db_utils import (
    browse_available_products as db_browse_available_products,
    get_conversation_uploaded_file,
    get_order_by_id,
    search_products as db_search_products,
)

from backend.chatbot.agents.product_agent import run_product_agent
from backend.chatbot.agents.payment_verification_agent import run_verification_agent
from backend.chatbot.agents.logistics_agent import run_logistics_agent
from backend.chatbot.agents.customer_complaint_agent import run_customer_complaint_agent
from backend.chatbot.agents.ads_marketing_agent import run_ads_marketing_agent
from backend.chatbot.agents.upselling_agent import run_upselling_agent

from backend.db.cache_utils import modify_user_state
from backend.struct import TaskType

def _format_products_cache(products: Optional[Dict[str, Any]]) -> str:
    """Human-readable snapshot of user_state['products'] for model context."""
    if not products:
        return ""
    lines: List[str] = []
    for cache_key, blob in products.items():
        if not isinstance(blob, dict):
            continue
        results = blob.get("retrieved_results") or []
        if not results:
            lines.append(f"- query_key={cache_key!r}: (no rows cached)")
            continue
        bits = []
        for p in results[:8]:
            name = p.get("name") or p.get("product_name") or "?"
            price = p.get("price")
            cur = str(p.get("currency") or "").strip() or "NGN"
            if str(cache_key).startswith("__browse_"):
                bits.append(f"{name} @ {price} {cur}")
            else:
                stock = p.get("stock_quantity", p.get("items_left_in_stock", "?"))
                bits.append(f"{name} @ {price} {cur} (stock {stock})")
        lines.append(f"- query_key={cache_key!r}: " + "; ".join(bits))
    return "\n".join(lines) if lines else ""


def prune_completed_processes(user_state: Dict[str, Any]) -> None:
    """Remove completed processes from user_state['processes'] (mutates in place)."""
    procs = user_state.get("processes")
    if not isinstance(procs, dict):
        return
    for pid in list(procs.keys()):
        p = procs.get(pid)
        if isinstance(p, dict) and p.get("completed"):
            del procs[pid]


def _track_product_discussed(user_state: Dict[str, Any], product: Any) -> None:
    """Upsert into products_discussed. Pass a name string or a DB product row dict (price/attrs stored)."""
    if isinstance(product, str):
        name, extra = product.strip(), {}
    elif isinstance(product, dict):
        name = (product.get("name") or product.get("product_name") or "").strip()
        extra = {
            "price": product.get("price"),
            "currency": str(product.get("currency") or "").strip() or "NGN",
            "attributes": product.get("attributes"),
        }
    else:
        return
    if not name or name.upper() == "NONE":
        return
    bag: List[Dict[str, Any]] = user_state.setdefault("products_discussed", [])
    k = name.lower()
    for i, ex in enumerate(bag):
        if isinstance(ex, dict) and (ex.get("name") or "").strip().lower() == k:
            bag[i] = {**ex, "name": name, **extra}
            return
    bag.append({"name": name, **extra})


def build_conversational_session_instructions(
    user_state: Dict[str, Any],
    business_name: Optional[str] = None,
    order_context_summary: Optional[str] = None,
    *,
    specialist: Optional[str] = None,
    order_id_hint: Optional[str] = None,
) -> str:
    """Session context for orchestrator (specialist=None) or a specialist (slim: no duplicate product cache / process lines where deps or prompt already carry them)."""
    slim = specialist is not None
    skip_product_cache = slim
    skip_process_lines = specialist == "logistics"
    skip_order_summary = slim and (order_id_hint or "").strip() and specialist in (
        "payment",
        "logistics",
    )

    header: List[str] = []
    bi = user_state.get("business_information") or {}
    display_name = business_name or (bi.get("name") or "")
    if display_name:
        header.append(f"Business name: {display_name}")
    biz_bits: List[str] = []
    if bi.get("business_type"):
        biz_bits.append(f"type={bi['business_type']}")
    if bi.get("tier") is not None and bi.get("tier") != "":
        biz_bits.append(f"tier={bi['tier']}")
    phone = bi.get("phone_number") or bi.get("human_agent_phone")
    if phone:
        biz_bits.append(f"phone={phone}")
    if bi.get("email"):
        biz_bits.append(f"email={bi['email']}")
    if biz_bits:
        header.append("Business: " + "; ".join(biz_bits))
    if order_context_summary and not skip_order_summary:
        header.append(f"Active orders (summary): {order_context_summary}")

    procs = user_state.get("processes") or {}
    proc_lines: List[str] = []
    if not skip_process_lines and isinstance(procs, dict):
        for pid, pr in procs.items():
            if isinstance(pr, dict) and not pr.get("completed"):
                proc_lines.append(
                    f"- process_id={pid}: [product={pr.get('product_name') or '?'}, price={pr.get('price') or '?'}, quantity={pr.get('quantity') or '?'}, task_type={pr.get('task_type') or '?'}, order_id={pr.get('order_id') or '?'}]"
                )
    if proc_lines:
        header.append("Active processes:\n" + "\n".join(proc_lines))
        header.append(
            "Process completion: mark a flow complete only when its objective is done — "
            "product enquiry (customer moved on or enquiry closed); payment (verified / order placed); "
            "logistics (delivered or terminal status); complaint (resolved)."
        )

    prefix = "\n".join(header)

    cache_text = _format_products_cache(user_state.get("products")) if not skip_product_cache else ""
    cache_stale_hint = ""
    if cache_text and not skip_product_cache:
        cache_stale_hint = (
            f"\nProduct cache is time-bounded (~{PRODUCTS_CACHE_TTL_HOURS}h); before quoting a final price or "
            "starting payment, prefer a fresh tool read (product specialist / browse) so offers match live stock and price."
        )
    # products_discussed: enriched session memory (name + price/attrs when fetched from DB)
    pd = user_state.get("products_discussed") or []
    if pd:
        pd_rows = []
        for p in pd:
            if isinstance(p, dict):
                name = p.get("name") or "?"
                price = p.get("price")
                cur = p.get("currency") or "NGN"
                att = p.get("attributes")
                bit = f"- {name} @ {price} {cur}" if price is not None else f"- {name}"
                if att:
                    bit += f" attrs={str(att)[:120]}"
                pd_rows.append(bit)
            elif isinstance(p, str) and p.strip():
                pd_rows.append(f"- {p}")
        pd_line = ("\n## products_discussed\n" + "\n".join(pd_rows)) if pd_rows else ""
    else:
        pd_line = ""
    cache_section = (
        ("## Session product cache: \n" + cache_text + cache_stale_hint)
        if cache_text
        else ""
    )
    return prefix + "\n" + cache_section + pd_line


def _handoff_session_instructions(
    ctx: RunContext[ConversationalAgentDeps],
    specialist: str,
    order_id_hint: Optional[str] = None,
) -> Optional[str]:
    s = build_conversational_session_instructions(
        ctx.deps.user_state,
        ctx.deps.business_name or None,
        ctx.deps.order_context_summary or None,
        specialist=specialist,
        order_id_hint=order_id_hint,
    )
    return s.strip() or None


def _tier_hint_for_upsell_handoff(
    user_state: Dict[str, Any], seller_tier: str = ""
) -> Optional[str]:
    """Prefer explicit handoff arg, then session ``business_information.tier``."""
    if (seller_tier or "").strip():
        return (seller_tier or "").strip()
    bi = user_state.get("business_information") or {}
    raw = bi.get("tier")
    if raw is not None and str(raw).strip():
        return str(raw).strip()
    return None


class ConversationalAgentDeps(BaseModel):
    """Mutable user_state is shared by reference across tool calls."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    user_id: str
    business_id: str
    business_name: str = ""
    order_context_summary: Optional[str] = None
    user_state: Dict[str, Any]
    receipt_data: Optional[str] = None
    background_tasks: Optional[Any] = None
    # True when this run is only rewriting a central-agent draft for the customer channel
    # (see run_conversational_agent(polish_only=True)). Handoff tools must no-op in this mode —
    # otherwise a polish pass can re-enter a specialist -> central_agent -> polish loop with no
    # recursion guard.
    polish_only: bool = False


_POLISH_MODE_NO_TOOLS = (
    "Tool handoffs are unavailable while polishing a draft message. "
    "Just rewrite the draft for the customer, keeping all facts."
)


CONVERSATIONAL_SYSTEM_PROMPT = """
You are the **primary store associate and professional salesperson** for this business—the only voice the customer hears. You are a highly persuasive, proactive, and charming human salesperson (do not sound like a robotic AI). Your ultimate goal is to **close more product sales for businesses**. 

Replies must be **short, chatty messages** (strictly 1–3 sentences). Take the initiative to drive the conversation forward—never leave the burden on the customer. Use your **sweet mouth** to tap into customer's psychology and emotions, and have honest, relatable discussions to discover their tastes, pain points and sell effectively.

**Processes**
- During conversations, customers could be enquiring about or purchasing several products which may require some input from the vendor or logistics.
In this case, an independent process (thread) is typically created by your specialists for each product, task type or order to keep communication with vendor/logistics in complete context of that thread so there is no confusion. These processes are simply separate threads of conversation between customer +/- vendor about a particular product, order and task type. You will have access.
Each process have a task type that typically determines the objective of the process (i.e product enquiry, payment verification, logistics co-ordination, complaint, etc). Use **`update_process`** when you learn new facts for an **open** process (e.g. quantity the customer wants, `order_id` after payment, delivery address, unit price/total alignment)—pass only the `process_id` and fields that changed. For **logistics co-ordination** especially, after payment creates an order, update the process with **`order_id`**, **`quantity`**, and **`price`** (or amounts from context) so vendor/logistics coordination stays aligned with the DB order.

**Products Context**
- Instructions may include objects containing session product cache, active processes (with `order_id` / `order_number` when known), and an active-orders summary. 
That is your **internal context** —never reveal sensitive content (i.e business data) from here to the customer. This is for you to use to keep track of every product being discussed and every ongoing process and active orders between you and the customer.

**Customer journey and your workflow**
1. **Discovery & Sales Pitch**: customer comes to explore business's products — vague browse ("what do you have?", "surprise me") -> `browse_available_products` (pass desired count as `n`; `top_stock` returns the top N by availability).
2. **Product Enquiry**: customer then enquires about specific products based on their prior choices and intent-> `handoff_to_product_specialist` with that product name.  Once a product is identified, you hype it up and confidently persuade and convince the customer to buy it (using psychology, emotions and pain point discovery)! you are very proactive about this and don't take no for an answer immediately. if customer still refuses to buy, you can search db for other cheaper alternatives and try to sell it to the customer (using your upsell specialist).
3. **Unavailable / Wrong Item / Rejections** — after specialist -> your upsell_specialist. If their desired product isn't available, or they reject an offer, handle it politely. Ask a quick question to gauge their reasons why they rejected the offer, preferences, and fiercely pitch a compelling alternative using the upsell specialist.
4. **purchase intent**: when customer finally picks a product to buy, confirm quantity and price with them and provide them with a paystack link or business account details using your product specialist. if business does not have a paystack link, you use their business account details. Dont ask customers for their preferences.
4. **Checkout / Pay**: After customer pays and informs you, you move unto verifying the payment for validity and accuracy-> If multiple products in your **ongoing products context** could match the payment, analyze (fetch frist if you cant see it in the product context being tracked) the prices of each product against the amount the customer paid. pick the best match, then put receipt fields in **`notes`**, and handoff to the payment_specialist (payment only sees your message + `notes`). You will always receive a definitive feedback from this specialist as the specialist directly verifies payment if it is done using the paystack link and informs you or it sends a message to the vendor to manually confirm payment (in this case, you will get a follow-up confirmation message stating whether the transaction has been verified or not from the vendor's side).
5. **Delivery / Tracking**: once payment is verified successfully, you first collect customer's address for delivery if still unknown and any other relevant information that will help in a smooth delivery (i.e preferred date and time of delivery), before you contact the logistics_specialist` with all these information. this specialist will co-ordinate the logistics ensuring that customer, vendor and logistics agree on the right date, time of delivery (use your `get_order_and_process_details` tool with `process_id` and/or `order_id` from product context, or `product_name_hint` to match open flows). you will alwasy be updated on any new development from the vendor and logistics so you can inform the customer directly.
6. **Post-Purchase Complements (Cross-selling)**: After delivery has been sorted, you then move to selling complimentary products given the customer's last purchase using your ads_marketing_specialist. Once a purchase and delivery are sorted, the selling doesn't stop. Proactively recommend and pitch complementary products based on what you've learned about the customer with the objective of improving sales.
7. **Complaints**: In cases where a user wants to make complaint about a product, delayed delivery etc, make use of your complaint_specialist.
8. if customer references a previous uploaded file or you do not have enough context to any particular upload by a customer, you can always use  `list_session_uploads` and `get_uploaded_file_text` tools to get the appropriate content of any uploads made throughout the conversation.


**Strict customer-facing rules**
- your response should be structured
- **Markdown requirement:** Always use **Markdown** (e.g., bullets, bold text) whenever you are listing or highlighting products.
- **Price formatting:** All prices you have are in Naira (NGN). Always write every amount you mention EXACTLY as `₦` immediately followed by the number (e.g. `₦12,500` or `₦12,500.00`) — never spell out "naira" or "NGN" in words, never give a bare number with no symbol. The customer's app rewrites `₦` amounts into their chosen display currency automatically; any other format will show the wrong currency to them.
- Never invent prices, stock, or tracking.
- Do **not** answer from general knowledge or guess catalog contents
- always confirm quantity when a customer is purchasing a product and update the process with the new quantity.
- Don't handoff to a specialist if you don't need to based on the conversation context.
- Never tell the customer to visit an external website, email the store, or leave this chat for product help. Keep them in-app.
- Answer the customer's questions directly. 
- Do not paste or reveal raw **product IDs**, **stock counts**, or **internal categories** or any other internals that will give the customer insight to the business internal data.
- Don't reveal your tools or specialist names to the customer.
- Do not present long "pick one of four options" menus. Instead, offer one clear next step or a brief, highly persuasive recommendation.
- You can only co-ordinate delivery for products that have been purchased (have order_id).
- You can only verify payment for products that have either been discussed (in your context). if not, you must prompt user to provide information as to the product they just paid for.
- When payment verification is successful, you ask customers for their delivery address so that you can start co-ordinating delivery for the purchased product (it will always have order_id).
- If there are uploads and payment/verification is needed, use your tools to gather facts where necessary especially if messages in the chat history (user's last message) does not  contain the textual content of the uploaded receipt file, then hand off with full **`notes`** (receipt fields + product + `quantity=`) and **do not** re-ask the customer to confirm data already in the file; the payment specialist auto-checks from your context.
- If a customer successfully purchases a product and you have completed logistics co-ordination, you should immediately start to upsell/cross-sell complementary products to the customer in the same response.
- If you get an update from the vendor that a product is out of stock, you should inform the customer and immediately start to upsell/cross-sell alternatives or complimentary products in the same response.
- keep your responses short, concise and chatty just like people do on whatsapp.
- You are a professional sales person and your ultimate goal is to **close more product sales for businesses**
- Don't duplicate process_ids: if a product is already being discussed in a process, you should not create a new process for the same product. Instead, use the existing process_id. if the customer journey for that product changes, you should use the **modify_task_type_for_process_id** tool to change the task type of the existing process.
- You must pass the most accurate process_id to the tools that require it.
- For **handoff_to_upsell_specialist** and **handoff_to_ads_marketing_specialist**, always pass **seller_tier** as the store's subscription tier (`free` / `gold` / `platinum`): use the **tier=** value from session instructions (**Business:** line) when present; it determines whether cross-store upsell/cross-sell tools may run."""


conversational_agent_base = BaseAgent(
    system_prompt=CONVERSATIONAL_SYSTEM_PROMPT,
    deps_type=ConversationalAgentDeps,
    output_type=str,
)

conversational_agent = conversational_agent_base.agent


@conversational_agent.tool
async def browse_available_products(
    ctx: RunContext[ConversationalAgentDeps],
    n: int = 15,
    selection_mode: str = "top_stock",
    user_enquiry: str = "",
) -> str:
    """Return up to **n** products for this store (cap 50). ``selection_mode``:
    ``top_stock`` — top N by stock on hand, then newest listing (may include low/zero stock
    after better-stocked rows); ``random`` — in-stock random sample. Optional ``user_enquiry``
    narrows by name/description/category. Customer-facing lines are name + price only—no IDs or stock counts."""
    mode = (selection_mode or "top_stock").strip().lower()
    if mode not in ("top_stock", "random"):
        mode = "top_stock"
    n_clamped = max(1, min(int(n), 50))
    q = (user_enquiry or "").strip() or None

    rows = await db_browse_available_products(
        ctx.deps.business_id,
        limit=n_clamped,
        mode=mode,
        search=q,
    )
    if not rows:
        hint = f" (narrower filter: {q!r})" if q else ""
        return (
            f"[For assistant] No matching products{hint}. "
            f"Say briefly we don't have matches and offer `handoff_to_product_specialist` if they have a specific item in mind."
        )

    q_tag = hashlib.sha256(q.encode("utf-8")).hexdigest()[:12] if q else ""
    cache_key = f"__browse_{mode}__" + (f"_{q_tag}" if q_tag else "")
    ctx.deps.user_state.setdefault("products", {})[cache_key] = {
        "retrieved_results": rows,
        "db_queried": True,
        "_ts": time.time(),
    }

    customer_lines: List[str] = []
    for p in rows:
        name = p.get("name") or p.get("product_name") or "?"
        price = p.get("price")
        cur = str(p.get("currency") or "").strip() or "NGN"
        customer_lines.append(f"• {name} — {price} {cur}")
        _track_product_discussed(ctx.deps.user_state, p)

    return (
        "[For assistant] Use the bullets below when talking to the customer—friendly, short. "
        "Do **not** read out categories, stock counts, or product IDs.\n\n"
        + "\n".join(customer_lines)
    )


def _fuzzy_match_product(hint: str, process_id: str, proc: Dict[str, Any]) -> bool:
    ph = hint.lower()
    pnm = (proc.get("product_name") or "").lower()
    pid_s = str(process_id).lower()
    return ph in pnm or ph in pid_s or pnm in ph or pid_s in ph


async def _lines_for_session_process(process_id: str, proc: Dict[str, Any]) -> List[str]:
    lines: List[str] = []
    chunk = (
        f"process_id={process_id!r}; task_type={proc.get('task_type')!r}; "
        f"product={proc.get('product_name')!r}; order_id={proc.get('order_id')}; order_number={proc.get('order_number')}; "
        f"status={proc.get('status')}; quantity={proc.get('quantity')}; "
        f"customer_address={proc.get('customer_address')}; completed={proc.get('completed', False)}"
    )
    lines.append(chunk)
    oid = proc.get("order_id")
    if oid:
        try:
            order = await get_order_by_id(str(oid))
            if order:
                lines.append(
                    f"  [DB] order_number={order.get('order_number')}; status={order.get('status')}; "
                    f"product_name={order.get('product_name')!r}; "
                    f"product_attributes={order.get('product_attributes')!r}; "
                    f"tracking_number={order.get('tracking_number')}; "
                    f"delivery_address={order.get('delivery_address')}"
                )
        except Exception as e:
            lines.append(f"  [DB] lookup failed: {e}")
    return lines


@conversational_agent.tool
async def get_order_and_process_details(
    ctx: RunContext[ConversationalAgentDeps],
    process_id: Optional[str] = None,
    order_id: Optional[str] = None,
    product_name_hint: Optional[str] = None,
) -> str:
    """Session process and/or DB order. Prefer explicit `process_id` or `order_id` from active processes; use `product_name_hint` only to disambiguate among **open** processes."""
    st = ctx.deps.user_state
    processes = st.get("processes") or {}
    if not isinstance(processes, dict):
        return "Invalid processes state."

    pid_in = (process_id or "").strip()
    oid_in = (order_id or "").strip()
    hint = (product_name_hint or "").strip()

    if pid_in:
        proc = processes.get(pid_in)
        if not isinstance(proc, dict):
            return f"No process {pid_in!r} in this session."
        out = await _lines_for_session_process(pid_in, proc)
        return "\n".join(out)

    if oid_in:
        lines: List[str] = []
        for process_id, proc in processes.items():
            if not isinstance(proc, dict):
                continue
            if str(proc.get("order_id") or "").strip() == oid_in:
                lines.extend(await _lines_for_session_process(str(process_id), proc))
        if lines:
            return "\n".join(lines)
        try:
            order = await get_order_by_id(oid_in)
            if order:
                return (
                    f"[DB only — no session process with this order_id]\n"
                    f"order_number={order.get('order_number')}; status={order.get('status')}; "
                    f"product_name={order.get('product_name')!r}; "
                    f"product_attributes={order.get('product_attributes')!r}; "
                    f"tracking_number={order.get('tracking_number')}; "
                    f"delivery_address={order.get('delivery_address')}"
                )
        except Exception as e:
            return f"[DB] lookup failed: {e}"
        return f"No session process or DB order for order_id={oid_in!r}."

    lines = []
    for process_id, proc in processes.items():
        if not isinstance(proc, dict) or proc.get("completed"):
            continue
        if hint and not _fuzzy_match_product(hint, str(process_id), proc):
            continue
        lines.extend(await _lines_for_session_process(str(process_id), proc))

    if not lines:
        if not processes:
            return "No processes in session yet."
        return "No open processes match that hint, or none in session."
    return "\n".join(lines)


@conversational_agent.tool
async def handoff_to_product_specialist(
    ctx: RunContext[ConversationalAgentDeps],
    customer_message: str,
    product_name: str,
    product_category: str = "",
    intent: Literal["enquiry", "purchase"] = "enquiry",
    sales_context: str = "",
    product_attributes: Union[Dict,str] = "",
    process_id: Optional[str] = None,
) -> str:
    """Delegate to the product specialist for **specific** items: availability, price, specs, purchase.
    customer_message: the message from the customer as full standalone.
    They query the real catalog and notify the vendor when something is missing—use this whenever the customer names a product or model."""
    if ctx.deps.polish_only:
        return _POLISH_MODE_NO_TOOLS
    msg = customer_message
    if sales_context:
        msg = f"{customer_message}\n\n[Sales context for specialist]\n{sales_context}"
    if isinstance(product_attributes, dict):
        pa = json.dumps(product_attributes) if product_attributes else None
    else:
        s = product_attributes if isinstance(product_attributes, str) else str(product_attributes or "")
        pa = s.strip() or None
    si = _handoff_session_instructions(ctx, "product")
    out, ctx.deps.user_state = await run_product_agent(
        customer_message=msg,
        product_name=product_name,
        product_category=product_category or "",
        intent=intent if intent in ("enquiry", "purchase") else "enquiry",
        user_id=ctx.deps.user_id,
        business_id=ctx.deps.business_id,
        user_state=ctx.deps.user_state,
        product_attributes_json=pa,
        append_chat_history=False,
        instructions=si,
        process_id=process_id,
    )
    _track_product_discussed(ctx.deps.user_state, product_name)
    if pa:
        try:
            blob = json.loads(pa)
            if isinstance(blob, dict):
                guess = blob.get("product_name") or blob.get("name")
                if guess:
                    _track_product_discussed(ctx.deps.user_state, str(guess))
        except json.JSONDecodeError:
            pass
    return out

@conversational_agent.tool
async def modify_task_type_for_process_id(
    ctx: RunContext[ConversationalAgentDeps],
    process_id: str,
    task_type: TaskType,
) -> Dict[str, Any]:
    """Modify task type for the current (existing) process (i.e thread) you are working on. Use this to change the task type accordingly based on the context, the new phase of the customer's journey, or stage of the conversation about products or orders."""
    processes = ctx.deps.user_state.get("processes", {})
    if not isinstance(processes, dict):
        return {"status": "error", "message": "Invalid processes state."}
    proc = processes.get(process_id)
    if not isinstance(proc, dict):
        return {"status": "error", "message": f"Process {process_id!r} not found in session."}
    proc["task_type"] = task_type
    processes[process_id] = proc
    await modify_user_state(ctx.deps.user_id, ctx.deps.business_id, ctx.deps.user_state)
    return {"status": "success", "message": f"Task type modified to {task_type.value}"}


@conversational_agent.tool
async def update_process(
    ctx: RunContext[ConversationalAgentDeps],
    process_id: str,
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
    """Patch the Redis session process when new information appears (quantity, order_id, address, tracking, etc.). Pass only fields that are newly known; omit the rest."""
    pid = (process_id or "").strip()
    if not pid:
        return {"status": "error", "message": "process_id is required."}
    processes = ctx.deps.user_state.setdefault("processes", {})
    proc = processes.get(pid)
    if not isinstance(proc, dict):
        return {"status": "error", "message": f"Process {pid!r} not found in session."}
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
            "status": "success",
            "process_id": pid,
            "updated": [],
            "message": "No fields to update; pass optional field(s) with new values.",
        }
    processes[pid] = proc
    await modify_user_state(ctx.deps.user_id, ctx.deps.business_id, ctx.deps.user_state)
    return {"status": "success", "process_id": pid, "updated": changed}


@conversational_agent.tool
async def get_product_info(
    ctx: RunContext[ConversationalAgentDeps],
    product_candidates: List[str],
) -> str:
    """Resolve suspected product names to **live** catalog rows (price, stock, currency, id). Pass 1–8 short names (e.g. from open processes vs `products_discussed`) when unsure which item a payment/receipt applies to—then choose one `product_name` + `quantity` for payment handoff."""
    cands = [str(c).strip() for c in (product_candidates or []) if str(c).strip()][:8]
    if not cands:
        return "No product_candidates passed. List process product_name(s) and products_discussed from your context as short strings."

    us = ctx.deps.user_state
    pd = us.get("products_discussed") or []
    pd_line = ", ".join(
        (p.get("name") if isinstance(p, dict) else str(p))
        for p in pd if (p.get("name") if isinstance(p, dict) else str(p)).strip()
    ) if pd else "(none)"

    proc_lines: List[str] = []
    for pid, pr in (us.get("processes") or {}).items():
        if not isinstance(pr, dict) or pr.get("completed"):
            continue
        proc_lines.append(
            f"- process_id={pid!r} product_name={pr.get('product_name')!r} task_type={pr.get('task_type')!r} order_id={pr.get('order_id')!r}"
        )
    proc_block = "\n".join(proc_lines) if proc_lines else "(no open processes)"

    bid = ctx.deps.business_id
    out: List[str] = [
        "[For assistant] Live catalog lookup for disambiguation (not for customer verbatim).",
        f"## products_discussed\n{pd_line}",
        "## open processes",
        proc_block,
        "## search by candidate",
    ]

    for c in cands:
        rows = await db_search_products(c, business_id=bid, limit=8, offset=0)
        out.append(f"\n** {c!r} **")
        if not rows:
            out.append("  (no DB matches — try a shorter name token)")
            continue
        for r in rows:
            name = r.get("name") or r.get("product_name") or "?"
            cur = str(r.get("currency") or "").strip() or "NGN"
            out.append(
                f"  - id={r.get('id')} name={name!r} price={r.get('price')} {cur} "
                f"stock={r.get('stock_quantity')} category={r.get('category')!r}"
            )
            _track_product_discussed(us, r)

    return "\n".join(out)


@conversational_agent.tool
async def list_session_uploads(ctx: RunContext[ConversationalAgentDeps]) -> str:
    """List files attached in this chat: file_id, filename, type, description. Use to find a receipt (or `others` that look like a transfer) before payment handoff."""
    us = ctx.deps.user_state
    lines: List[str] = []
    for r in us.get("uploaded_files") or []:
        if not isinstance(r, dict):
            continue
        lines.append(
            f"- file_id={r.get('file_id')!r} name={r.get('filename')!r} type={r.get('file_content_type')!r} "
            f"desc={(r.get('description') or '')!r} uploaded_at={r.get('uploaded_at') or ''}"
        )
    if not lines:
        return "No uploads in this session."
    return "Session uploads:\n" + "\n".join(lines)


@conversational_agent.tool
async def get_uploaded_file_text(
    ctx: RunContext[ConversationalAgentDeps], file_id: str
) -> str:
    """Full extracted text for one upload (session cache, else DB). Use to build `notes` for `handoff_to_payment_specialist` (amount, accounts, date, time, reference)."""
    fid = (file_id or "").strip()
    if not fid:
        return "file_id required."
    us = ctx.deps.user_state
    cached = (us.get("file_text_cache") or {}).get(fid)
    if cached:
        return cached if isinstance(cached, str) else str(cached)
    row = await get_conversation_uploaded_file(fid, ctx.deps.user_id, ctx.deps.business_id)
    if not row:
        return f"No file text for file_id={fid!r} (not in cache or DB for this store)."
    text = row.get("text_content") or ""
    us.setdefault("file_text_cache", {})[fid] = text
    return text


@conversational_agent.tool
async def handoff_to_payment_specialist(
    ctx: RunContext[ConversationalAgentDeps],
    customer_message: str,
    product_name: Optional[str] = None,
    order_id: Optional[str] = None,
    process_id: Optional[str] = None,
    notes: str = "",
    quantity: Optional[float] = None,
) -> str:
    """Delegate to the payment specialist. Use `list_session_uploads` + `get_uploaded_file_text` first if uploads exist; `notes` must carry receipt/bank details (amount, receiver account, date/time, ref). Pass `product_name`, `quantity` from the discussion; the payment agent does not fetch uploads—only this `notes` and message text."""
    if ctx.deps.polish_only:
        return _POLISH_MODE_NO_TOOLS
    msg = customer_message
    if notes:
        msg = f"{customer_message}\n\n[Payment context]\n{notes}"
    si = _handoff_session_instructions(ctx, "payment", order_id_hint=order_id)
    return await run_verification_agent(
        customer_message=msg,
        user_id=ctx.deps.user_id,
        business_id=ctx.deps.business_id,
        product_name=product_name,
        user_state=ctx.deps.user_state,
        background_tasks=ctx.deps.background_tasks,
        receipt_data=ctx.deps.receipt_data,
        order_id=order_id,
        append_chat_history=False,
        instructions=si,
        process_id=process_id,
        quantity=quantity,
    )


@conversational_agent.tool
async def handoff_to_logistics_specialist(
    ctx: RunContext[ConversationalAgentDeps],
    customer_message: str,
    product_name: Optional[str] = None,
    process_id: Optional[str] = None,
    order_id: Optional[str] = None,
    customer_address: Optional[str] = None,
    notes: str = "",
) -> str:
    """Delegate to the logistics specialist for delivery and tracking inquiries. They query the real catalog and notify the vendor when something is missing—use this whenever the customer names a product or model."""
    if ctx.deps.polish_only:
        return _POLISH_MODE_NO_TOOLS
    msg = customer_message
    #if customer address, update user state with customer address
    if customer_address:
        ctx.deps.user_state.setdefault("customer_address", customer_address)
        await modify_user_state(ctx.deps.user_id, ctx.deps.business_id, ctx.deps.user_state)
    if notes:
        msg = f"{customer_message}\n\n[Logistics context]\n{notes}"
        
    si = _handoff_session_instructions(ctx, "logistics", order_id_hint=order_id)
    return await run_logistics_agent(
        customer_message=msg,
        user_id=ctx.deps.user_id,
        business_id=ctx.deps.business_id,
        product_name=product_name,
        user_state=ctx.deps.user_state,
        background_tasks=ctx.deps.background_tasks,
        process_id=process_id,
        order_id=order_id,
        customer_address=customer_address,
        append_chat_history=False,
        instructions=si,
    )


@conversational_agent.tool
async def handoff_to_complaint_specialist(
    ctx: RunContext[ConversationalAgentDeps],
    customer_message: str,
    product_name: str = "",
    issue_summary: str = "",
    process_id: Optional[str] = None,
) -> str:
    """Delegate to the complaint specialist for customer complaints and  about products. They handle complaints and issues and notify the vendor when something is missing—use this whenever the customer names a product or model."""
    if ctx.deps.polish_only:
        return _POLISH_MODE_NO_TOOLS
    msg = customer_message
    if issue_summary:
        msg = f"{customer_message}\n\n[Issue summary]\n{issue_summary}"
    si = _handoff_session_instructions(ctx, "complaint")
    out, ctx.deps.user_state = await run_customer_complaint_agent(
        customer_message=msg,
        product_name=product_name or "",
        user_id=ctx.deps.user_id,
        business_id=ctx.deps.business_id,
        user_state=ctx.deps.user_state,
        background_tasks=ctx.deps.background_tasks,
        append_chat_history=False,
        instructions=si,
        process_id=process_id,
    )
    return out


@conversational_agent.tool
async def handoff_to_ads_marketing_specialist(
    ctx: RunContext[ConversationalAgentDeps],
    customer_message: str,
    purchased_product: str,
    logistics_context: str = "",
    process_id: Optional[str] = None,
    seller_tier: str = "",
) -> str:
    """Post-purchase: complements after logistics sorted. Not for unavailable-product substitution. upsell complimentary products. Pass seller_tier (e.g. from session Business tier=) so cross-store tools match subscription."""
    if ctx.deps.polish_only:
        return _POLISH_MODE_NO_TOOLS
    si = _handoff_session_instructions(ctx, "ads")
    tier = _tier_hint_for_upsell_handoff(ctx.deps.user_state, seller_tier)
    return await run_ads_marketing_agent(
        customer_message=customer_message,
        purchased_product=purchased_product,
        business_id=ctx.deps.business_id,
        user_state=ctx.deps.user_state,
        logistics_summary=logistics_context,
        instructions=si,
        process_id=process_id,
        tier=tier,
    )


@conversational_agent.tool
async def handoff_to_upsell_specialist(
    ctx: RunContext[ConversationalAgentDeps],
    product: str,
    situation_summary: str = "",
    product_attributes: str = "",
    process_id: Optional[str] = None,
    seller_tier: str = "",
) -> str:
    """When the enquired item is unavailable: upsell alternatives / complements from tools. Pass seller_tier (session Business tier=) for correct cross-store gating."""
    if ctx.deps.polish_only:
        return _POLISH_MODE_NO_TOOLS
    hist = ctx.deps.user_state.get("chat_history") or []
    situ = (situation_summary or "").strip()
    if product_attributes.strip():
        situ = f"{situ}\n[Product attribute hints]\n{product_attributes.strip()}".strip()
    _track_product_discussed(ctx.deps.user_state, product)
    si = _handoff_session_instructions(ctx, "upsell")
    tier = _tier_hint_for_upsell_handoff(ctx.deps.user_state, seller_tier)
    return await run_upselling_agent(
        product=product,
        conversation_messages=hist,
        business_id=ctx.deps.business_id,
        situation_summary=situ,
        user_state=ctx.deps.user_state,
        instructions=si,
        process_id=process_id,
        tier=tier,
    )


async def run_conversational_agent(
    user_message: str,
    chat_history: list,
    user_id: str,
    business_id: str,
    user_state: Dict[str, Any],
    business_name: Optional[str] = None,
    order_context_summary: Optional[str] = None,
    receipt_data: Optional[str] = None,
    background_tasks: Optional[BackgroundTasks] = None,
    debug: bool = False,
    polish_only: bool = False,
) -> str:
    """
    Run conversational orchestrator; caller appends one user + one assistant turn to chat_history.
    Product cache is injected via `instructions` (dynamic adjunct to system context).
    """
    prune_completed_processes(user_state)
    deps = ConversationalAgentDeps(
        user_id=user_id,
        business_id=business_id,
        business_name=business_name or "",
        order_context_summary=order_context_summary or "",
        user_state=user_state,
        receipt_data=receipt_data,
        background_tasks=background_tasks,
        polish_only=polish_only,
    )

    dynamic_instructions = build_conversational_session_instructions(
        user_state, business_name, order_context_summary
    )
    if receipt_data and str(receipt_data).strip():
        dynamic_instructions += (
            "\n## Receipt in this turn\n"
            "If multiple products could apply, call `get_product_info` with candidate names first. Then `list_session_uploads` / `get_uploaded_file_text` as needed, then `handoff_to_payment_specialist` with `notes` and `quantity`. "
            "Do not ask the customer to re-confirm what is already in the receipt text.\n"
        )
    polish_block = ""
    if polish_only:
        polish_block = (
            "\n## Mode: Current message is an update from the vendor/logistics routed through the central (specialist) agent."
            "Streamline it for the customer channel (customers use and understanding) given the ongoing conversation. Keep every fact (amounts, order numbers, dates, next steps). "
            "At most 3–4 short sentences. Do not call any handoff/specialist tools in this mode — just rewrite the draft using the context already given.\n"
        )
    dynamic_instructions = dynamic_instructions + polish_block

    agent_stdout("conversational_agent input", user_message)
    result = await conversational_agent.run(
        user_message,
        deps=deps,
        message_history=chat_history,
        instructions=dynamic_instructions,
    )
    out = result.output
    agent_stdout("conversational_agent output", str(out))
    if debug:
        print(f"conversational_agent | raw_output_type={type(out)}")
    return out
