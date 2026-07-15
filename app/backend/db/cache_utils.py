import asyncio
from collections import defaultdict
from contextlib import asynccontextmanager

from backend.logging_config import get_logger
from pydantic_ai.messages import (
    ModelMessagesTypeAdapter,
    ModelRequest,
    ModelResponse,
    TextPart,
    UserPromptPart,
)

from .cache import Cache
from .config import REDIS_SERVER_HOST, REDIS_SERVER_PASSWORD, REDIS_SERVER_PORT

logger = get_logger(__name__)

redis_conn = Cache(
    host=REDIS_SERVER_HOST, port=REDIS_SERVER_PORT, password=REDIS_SERVER_PASSWORD
)

# In-process locks guarding read-modify-write cycles on a given Redis state key
# (e.g. get_user_state -> mutate -> modify_user_state). Prevents two concurrent
# turns for the same customer/vendor pair (or webhook + chat turn) from clobbering
# each other's writes with a stale full-state overwrite. Single-worker-process scope
# only — fine for this demo deployment, not a substitute for a distributed lock.
_state_locks: "defaultdict[str, asyncio.Lock]" = defaultdict(asyncio.Lock)


@asynccontextmanager
async def user_state_lock(user_id: str, vendor_id: str):
    async with _state_locks[f"{user_id}:{vendor_id}"]:
        yield


@asynccontextmanager
async def party_state_lock(party_id: str):
    async with _state_locks[f"party:{party_id}"]:
        yield


async def get_user_state(user_id, vendor_id, session_id=None):
    try:
        user_state = await asyncio.to_thread(redis_conn.get, f"{user_id}:{vendor_id}")
        if user_state:
            _hydrate_chat_history_if_needed(user_state)
        return user_state
    except Exception:
        logger.error(
            "redis_get_failed | user_id=%s vendor_id=%s",
            user_id,
            vendor_id,
            exc_info=True,
        )
        return None


def _serialize_user_state(user_state: dict) -> dict:
    """Convert user_state to JSON-serializable form (chat_history may contain pydantic_ai objects)."""
    state = dict(user_state)
    chat_history = state.get("chat_history")
    if chat_history and any(not isinstance(m, dict) for m in chat_history):
        state["chat_history"] = ModelMessagesTypeAdapter.dump_python(chat_history, mode="json")
    return state


async def modify_user_state(user_id, vendor_id, user_state, session_id=None) -> bool:
    try:
        serializable = _serialize_user_state(user_state)
        await asyncio.to_thread(redis_conn.set, f"{user_id}:{vendor_id}", serializable)
        return True
    except Exception:
        logger.error(
            "redis_set_failed | user_id=%s vendor_id=%s",
            user_id,
            vendor_id,
            exc_info=True,
        )
        return False


async def delete_user_state(user_id, vendor_id):
    try:
        await asyncio.to_thread(redis_conn.delete, f"{user_id}:{vendor_id}")
    except Exception:
        logger.error(
            "redis_delete_failed | user_id=%s vendor_id=%s",
            user_id,
            vendor_id,
            exc_info=True,
        )


def _hydrate_chat_history_if_needed(user_state: dict) -> None:
    if not user_state or "chat_history" not in user_state:
        return
    raw = user_state["chat_history"]
    if raw and isinstance(raw[0], dict):
        try:
            user_state["chat_history"] = ModelMessagesTypeAdapter.validate_python(raw)
        except Exception:
            logger.warning("chat_history hydration failed; retaining raw format", exc_info=True)
            # Leave raw dicts in place — they will be re-serialized correctly on next write


async def get_party_state(party_id: str) -> dict:
    """Redis key = party_id only (vendor or logistics chat state)."""
    if not party_id:
        return {}
    try:
        user_state = await asyncio.to_thread(redis_conn.get, party_id)
        if not user_state:
            return {}
        _hydrate_chat_history_if_needed(user_state)
        return user_state
    except Exception:
        logger.error("redis_party_get_failed | party_id=%s", party_id, exc_info=True)
        return {}


async def modify_party_state(party_id: str, user_state: dict) -> None:
    if not party_id:
        return
    try:
        serializable = _serialize_user_state(user_state)
        await asyncio.to_thread(redis_conn.set, party_id, serializable)
    except Exception:
        logger.error("redis_party_set_failed | party_id=%s", party_id, exc_info=True)


async def delete_party_state(party_id: str) -> None:
    if not party_id:
        return
    try:
        await asyncio.to_thread(redis_conn.delete, party_id)
    except Exception:
        logger.error("redis_party_delete_failed | party_id=%s", party_id, exc_info=True)


async def push_to_inbox(recipient_id: str, message: dict) -> bool:
    try:
        await asyncio.to_thread(redis_conn.push_to_list, f"inbox:{recipient_id}", message)
        return True
    except Exception:
        logger.error("inbox_push_failed | recipient_id=%s", recipient_id, exc_info=True)
        return False


async def push_to_inbox_with_retry(
    recipient_id: str, message: dict, *, retries: int = 3
) -> bool:
    """Vendor/logistics inbox: transient Redis failures get a short bounded retry."""
    for attempt in range(max(1, retries)):
        if await push_to_inbox(recipient_id, message):
            return True
        await asyncio.sleep(0.12 * (attempt + 1))
    logger.error(
        "inbox_push_exhausted_retries | recipient_id=%s attempts=%s",
        recipient_id,
        retries,
    )
    return False


async def get_inbox(recipient_id: str) -> list:
    try:
        return await asyncio.to_thread(redis_conn.pop_all_from_list, f"inbox:{recipient_id}")
    except Exception:
        logger.error("inbox_get_failed | recipient_id=%s", recipient_id, exc_info=True)
        return []


async def delete_inbox_key(recipient_id: str) -> None:
    """Remove pending inbox list for a recipient (simulation reset)."""
    if not recipient_id:
        return
    try:
        await asyncio.to_thread(redis_conn.delete, f"inbox:{recipient_id}")
    except Exception:
        logger.error("inbox_delete_failed | recipient_id=%s", recipient_id, exc_info=True)


async def append_inbox_turn_to_customer_pair(
    customer_id: str,
    business_id: str,
    message_text: str,
) -> None:
    """Persist central outbound on customer–vendor Redis key user_id:vendor_id."""
    if not customer_id or not business_id or not message_text:
        return
    user_state = await get_user_state(customer_id, business_id) or {}
    history = list(user_state.get("chat_history") or [])
    history.append(ModelRequest(parts=[UserPromptPart(content="[Central agent]")]))
    history.append(ModelResponse(parts=[TextPart(content=message_text)]))
    user_state["chat_history"] = history
    await modify_user_state(customer_id, business_id, user_state)


async def append_inbox_turn_to_party_state(party_id: str, message_text: str) -> None:
    """Persist central outbound on single-key Redis state (vendor_id or logistic_id)."""
    if not party_id or not message_text:
        return
    user_state = await get_party_state(party_id) or {}
    history = list(user_state.get("chat_history") or [])
    history.append(ModelRequest(parts=[UserPromptPart(content="[Central agent]")]))
    history.append(ModelResponse(parts=[TextPart(content=message_text)]))
    user_state["chat_history"] = history
    await modify_party_state(party_id, user_state)


INV_ACTIVITY_CAP = 100


def _inventory_activity_key(business_id: str) -> str:
    return f"inv_activity:{business_id}"


async def record_inventory_activity(business_id: str, record: dict) -> None:
    """Append one catalog change event (stock/price/add) for dev UI feeds."""
    if not business_id or not isinstance(record, dict):
        return
    try:
        await asyncio.to_thread(
            redis_conn.rpush_json_capped,
            _inventory_activity_key(business_id), record, INV_ACTIVITY_CAP
        )
    except Exception:
        logger.warning(
            "inventory_activity_push_failed | business_id=%s",
            business_id,
            exc_info=True,
        )


async def get_inventory_activity(business_id: str, limit: int = 50) -> list:
    """Recent inventory events, newest first."""
    if not business_id:
        return []
    try:
        lim = max(1, min(int(limit), 100))
        rows = await asyncio.to_thread(
            redis_conn.list_tail_json, _inventory_activity_key(business_id), lim
        )
        return list(reversed(rows))
    except Exception:
        logger.warning(
            "inventory_activity_read_failed | business_id=%s",
            business_id,
            exc_info=True,
        )
        return []
