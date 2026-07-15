"""
User Chat Interface - Single entry via conversational_agent (orchestrator).
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import logfire
from fastapi import BackgroundTasks, UploadFile

from backend.chatbot.agents.conversational_agent import (
    prune_completed_processes,
    run_conversational_agent,
)
from backend.chatbot.utils.file_handler import process_uploaded_files
from backend.chatbot.utils.history_summarizer import maybe_summarize_chat_history
from backend.config import FILE_TEXT_CACHE_MAX, PRODUCTS_CACHE_TTL_HOURS
from backend.db.cache_utils import get_user_state, modify_user_state, user_state_lock
from backend.db.db_utils import get_business_info, get_chat_summary, upsert_chat_summary
from backend.struct import UserRequest
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    TextPart,
    UserPromptPart,
)

logger = logging.getLogger(__name__)


async def chat(
    user_request: UserRequest,
    background_tasks: BackgroundTasks = None,
    reset_user_state: bool = False,
    debug: bool = False,
    files: Optional[List[UploadFile]] = None,
) -> str:
    """
    Customer chat: conversational_agent is the only orchestration path; specialists are tools.
    One user turn + one assistant turn appended to chat_history here.
    """
    with logfire.span("customer_chat", user_id=user_request.user_id, vendor_id=user_request.vendor_id):
        async with user_state_lock(user_request.user_id, user_request.vendor_id):
            return await _chat_inner(user_request, background_tasks, reset_user_state, debug, files)


async def _chat_inner(
    user_request: UserRequest,
    background_tasks: BackgroundTasks = None,
    reset_user_state: bool = False,
    debug: bool = False,
    files: Optional[List[UploadFile]] = None,
) -> str:
    user_state = await get_user_state(user_request.user_id, user_request.vendor_id) or {}
    if "conversation_started_at" not in user_state:
        user_state["conversation_started_at"] = (
            datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        )

    if debug:
        print(f"User state keys: {list(user_state.keys())}")

    chat_history = user_state.get("chat_history") or []
    full_message = user_request.message

    if files:
        batch = await process_uploaded_files(
            files, user_request.vendor_id, user_request.user_id
        )
        user_state.setdefault("uploaded_files", []).extend(batch["uploaded_file_refs"])
        fcache: Dict[str, str] = user_state.setdefault("file_text_cache", {})
        for it in batch.get("items") or []:
            fid = it.get("file_id") or ""
            if fid:
                fcache[fid] = it.get("extracted_content") or ""
            attrs = it.get("product_attributes")
            if attrs is not None and attrs.product_name:
                from backend.chatbot.agents.conversational_agent import _track_product_discussed
                _track_product_discussed(user_state, str(attrs.product_name).strip())

        rd = batch.get("receipt_data")
        if rd:
            user_state["receipt_data"] = rd
            # receipt_data is a single str from file_handler; do not str.join a str (iterates by character).
            if isinstance(rd, str):
                receipt_block = rd
            else:
                receipt_block = "\n\n---\n\n".join(str(x) for x in rd)
            full_message += "\n\n[Receipt Data]\n" + receipt_block

        pl = batch.get("non_receipt_attachment_lines") or []
        if pl:
            full_message += "\n\n[Attachments — non-receipt files]\n" + "\n".join(pl)

        logger.info(
            "customer_chat full_message | user_id=%s vendor_id=%s | %s",
            user_request.user_id,
            user_request.vendor_id,
            full_message if len(full_message) < 500_000 else full_message[:100_000] + "…[truncated]",
        )

    business_name = (user_state.get("business_information") or {}).get("name")
    if not business_name:
        biz = await get_business_info(user_request.vendor_id)
        business_name = (biz or {}).get("name")
        if biz:
            user_state.setdefault("business_information", {}).update(biz)

    # --- Cap file_text_cache to last N entries (older ones live in DB) ---
    ftc: Dict[str, str] = user_state.setdefault("file_text_cache", {})
    if len(ftc) > FILE_TEXT_CACHE_MAX:
        keys = list(ftc.keys())
        for k in keys[: len(keys) - FILE_TEXT_CACHE_MAX]:
            del ftc[k]

    # --- Evict stale product cache entries (>TTL hours) ---
    products_cache = user_state.get("products", {})
    now = time.time()
    ttl_secs = PRODUCTS_CACHE_TTL_HOURS * 3600
    stale_keys = [
        k for k, v in products_cache.items()
        if isinstance(v, dict) and (now - v.get("_ts", 0)) > ttl_secs
    ]
    for k in stale_keys:
        del products_cache[k]

    # --- Summarize chat_history if it exceeds word limit ---
    existing_summary = await get_chat_summary(user_request.user_id, user_request.vendor_id)
    chat_history, new_summary, n_summarized = await maybe_summarize_chat_history(
        chat_history, existing_summary=existing_summary,
    )
    if new_summary:
        await upsert_chat_summary(user_request.user_id, user_request.vendor_id, new_summary, n_summarized)
        user_state["chat_history"] = chat_history

    prune_completed_processes(user_state)
    processes = user_state.get("processes", {})
    oc_parts: List[str] = []
    for pid, p in processes.items():
        if not isinstance(p, dict) or p.get("completed"):
            continue
        oid = str(p.get("order_id") or "").strip()
        pname = p.get("product_name") or ""
        bits = [f"process={pid}", f"product={pname}", f"price={p.get('price') or 'N/A'}"]
        if oid:
            bits.append(f"order_id={oid}")
        oc_parts.append("[" + ", ".join(bits) + "]")
    order_context = ", ".join(oc_parts) if oc_parts else ""

    logger.info(
        "session_state | user_id=%s vendor_id=%s | processes=%s | products_discussed=%s",
        user_request.user_id,
        user_request.vendor_id,
        json.dumps(dict(processes), default=str),
        json.dumps(user_state.get("products_discussed") or [], default=str),
    )

    response = await run_conversational_agent(
        user_message=full_message,
        chat_history=chat_history,
        user_id=user_request.user_id,
        business_id=user_request.vendor_id,
        user_state=user_state,
        business_name=business_name,
        order_context_summary=order_context,
        receipt_data=user_state.get("receipt_data"),
        background_tasks=background_tasks,
        debug=debug,
    )

    if debug:
        print(f"conversational_agent response length: {len(response or '')}")

    user_state.setdefault("chat_history", []).extend(
        [
            ModelRequest(parts=[UserPromptPart(content=full_message)]),
            ModelResponse(parts=[TextPart(content=response)]),
        ]
    )

    if not reset_user_state:
        await modify_user_state(user_request.user_id, user_request.vendor_id, user_state)

    return response
