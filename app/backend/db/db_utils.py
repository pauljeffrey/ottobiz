"""
Database utility functions using asyncpg for async PostgreSQL operations.

Migrated from SQLAlchemy to asyncpg for better async performance and simpler queries.
"""

from datetime import datetime, timezone
import uuid
from typing import Any, Dict, List, Optional

from backend.db.connection import get_db
from backend.logging_config import get_logger

logger = get_logger(__name__)


async def _maybe_log_inventory_activity(business_id: str, record: dict) -> None:
    """Best-effort feed for simulation UI; never raises."""
    if not business_id:
        return
    try:
        from backend.db.cache_utils import record_inventory_activity

        await record_inventory_activity(business_id, record)
    except Exception:
        logger.debug(
            "inventory_activity_log_failed | business_id=%s", business_id, exc_info=True
        )


# Effective ISO 4217 code: product override, else business default.
_EFF_CURRENCY = "COALESCE(NULLIF(TRIM(p.currency), ''), b.currency, 'NGN')"


## PRODUCT FUNCTIONS


async def get_products(
    business_id: str = None,
    name: str = None,
    category: str = None,
    min_price: float = None,
    max_price: float = None,
    exclude_business_id: str = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """
    Search products with optional filters.

    Args:
        business_id: Filter by business ID
        name: Search in product name, description, or tags (case-insensitive)
        category: Filter by category
        min_price: Minimum price filter
        max_price: Maximum price filter
        exclude_business_id: Exclude products from this business (for cross-sell)
        limit: Max results

    Returns:
        List of product dictionaries
    """
    pool = await get_db()

    query = f"""
        SELECT p.id, p.business_id, p.name, p.description, p.price, p.stock_quantity,
               p.sku, p.category, p.attributes, p.is_active, p.created_at, p.updated_at,
               {_EFF_CURRENCY} AS currency
        FROM products p
        INNER JOIN businesses b ON b.id = p.business_id
        WHERE p.is_active = true
    """
    params = []
    param_count = 1

    if business_id:
        query += f" AND p.business_id = ${param_count}::uuid"
        params.append(business_id)
        param_count += 1

    if exclude_business_id:
        query += f" AND p.business_id != ${param_count}::uuid"
        params.append(exclude_business_id)
        param_count += 1

    if name:
        query += f" AND (p.name ILIKE ${param_count} OR p.description ILIKE ${param_count} OR p.category ILIKE ${param_count})"
        params.append(f"%{name}%")
        param_count += 1

    if category:
        query += f" AND p.category ILIKE ${param_count}"
        params.append(f"%{category}%")
        param_count += 1

    if min_price is not None:
        query += f" AND p.price >= ${param_count}"
        params.append(min_price)
        param_count += 1

    if max_price is not None:
        query += f" AND p.price <= ${param_count}"
        params.append(max_price)
        param_count += 1

    query += f" ORDER BY p.created_at DESC LIMIT ${param_count}"
    params.append(limit)

    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
            return [dict(row) for row in rows]
    except Exception:
        logger.error(
            "get_products_failed | business_id=%s name=%s",
            business_id,
            name,
            exc_info=True,
        )
        return []


async def browse_available_products(
    business_id: str,
    *,
    limit: int = 8,
    mode: str = "top_stock",
    search: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Products for conversational browse.

    * ``top_stock``: up to ``limit`` **active** rows for the vendor, ranked by
      ``stock_quantity`` (highest first), then ``created_at`` (newest first),
      then ``name``—so callers get the true **top N** catalog slice. May include
      zero-stock items only after higher-stock rows are exhausted.
    * ``random``: in-stock-only random sample (up to ``limit``).

    Args:
        business_id: Vendor UUID
        limit: Max rows (capped at 50)
        mode: "top_stock" | "random"
        search: Optional ILIKE filter on name, description, category (user enquiry)
    """
    if mode not in ("top_stock", "random"):
        mode = "top_stock"
    lim = max(1, min(int(limit), 50))
    pool = await get_db()
    if mode == "random":
        stock_filter = "AND COALESCE(p.stock_quantity, 0) > 0"
        order_sql = "ORDER BY RANDOM()"
    else:
        stock_filter = ""
        order_sql = (
            "ORDER BY p.stock_quantity DESC NULLS LAST, "
            "p.created_at DESC NULLS LAST, p.name ASC NULLS LAST"
        )
    base = f"""
        SELECT p.id, p.business_id, p.name, p.description, p.price, p.stock_quantity,
               p.sku, p.category, p.attributes, p.is_active, p.created_at, p.updated_at,
               {_EFF_CURRENCY} AS currency
        FROM products p
        INNER JOIN businesses b ON b.id = p.business_id
        WHERE p.is_active = true
          AND p.business_id = $1::uuid
          {stock_filter}
    """
    try:
        async with pool.acquire() as conn:
            if search and search.strip():
                q = (
                    base
                    + " AND (p.name ILIKE $3 OR p.description ILIKE $3 OR p.category ILIKE $3) "
                    + order_sql
                    + " LIMIT $2"
                )
                rows = await conn.fetch(
                    q, business_id, lim, f"%{search.strip()}%"
                )
            else:
                q = base + " " + order_sql + " LIMIT $2"
                rows = await conn.fetch(q, business_id, lim)
            return [dict(row) for row in rows]
    except Exception:
        logger.error(
            "browse_available_products_failed | business_id=%s mode=%s",
            business_id,
            mode,
            exc_info=True,
        )
        return []


async def search_products(
    query: str, business_id: str = None, limit: int = 10, offset: int = 0
) -> List[Dict[str, Any]]:
    """
    Search products by query string (case-insensitive pattern matching).

    Args:
        query: Search query string
        business_id: Optional business ID filter
        limit: Maximum results to return
        offset: Pagination offset

    Returns:
        List of product dictionaries ranked by relevance
    """
    pool = await get_db()

    sql_query = f"""
        SELECT p.id, p.business_id, p.name, p.description, p.price, p.stock_quantity,
               p.sku, p.category, p.attributes, p.is_active, p.created_at, p.updated_at,
               {_EFF_CURRENCY} AS currency
        FROM products p
        INNER JOIN businesses b ON b.id = p.business_id
        WHERE p.is_active = true
          AND (p.name ILIKE $1 OR p.description ILIKE $1 OR p.category ILIKE $1)
    """

    params = [f"%{query}%"]
    param_count = 2

    if business_id:
        sql_query += f" AND p.business_id = ${param_count}::uuid"
        params.append(business_id)
        param_count += 1

    sql_query += (
        f" ORDER BY p.created_at DESC LIMIT ${param_count} OFFSET ${param_count + 1}"
    )
    params.extend([limit, offset])

    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql_query, *params)
            return [dict(row) for row in rows]
    except Exception:
        logger.error(
            "search_products_failed | query=%s business_id=%s",
            query,
            business_id,
            exc_info=True,
        )
        return []


async def get_product_by_id(product_id: str) -> Optional[Dict[str, Any]]:
    """Get a product by ID."""
    pool = await get_db()

    query = f"""
        SELECT p.id, p.business_id, p.name, p.description, p.price, p.stock_quantity,
               p.sku, p.category, p.attributes, p.is_active, p.created_at, p.updated_at,
               {_EFF_CURRENCY} AS currency
        FROM products p
        INNER JOIN businesses b ON b.id = p.business_id
        WHERE p.id = $1::uuid
    """

    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(query, product_id)
            return dict(row) if row else None
    except Exception:
        return None


## BUSINESS FUNCTIONS


def _is_uuid_str(s: str) -> bool:
    try:
        uuid.UUID(str(s).strip())
        return True
    except (ValueError, TypeError, AttributeError):
        return False


async def get_business_info(business_id: str) -> Optional[Dict[str, Any]]:
    """
    Get business information by ID.

    Args:
        business_id: Business UUID or social media handle

    Returns:
        Business dictionary or None
    """
    pool = await get_db()
    if not business_id or not str(business_id).strip():
        return None

    bid = str(business_id).strip()

    if _is_uuid_str(bid):
        query = """
            SELECT id, name, business_type, tier, phone_number, email,
                   ig_page, facebook_page, twitter_page, tiktok,
                   bank_name, bank_account_number, bank_account_name,
                   paystack_public_key, paystack_secret_key,
                   human_agent_phone, human_agent_email,
                   product_schema, currency, partner_logistic_id, created_at, updated_at
            FROM businesses
            WHERE id = $1::uuid
               OR ig_page ILIKE $2
               OR facebook_page ILIKE $2
               OR twitter_page ILIKE $2
               OR tiktok ILIKE $2
               OR phone_number ILIKE $2
               OR email ILIKE $2
            LIMIT 1
        """
        params = (bid, bid)
    else:
        query = """
            SELECT id, name, business_type, tier, phone_number, email,
                   ig_page, facebook_page, twitter_page, tiktok,
                   bank_name, bank_account_number, bank_account_name,
                   paystack_public_key, paystack_secret_key,
                   human_agent_phone, human_agent_email,
                   product_schema, currency, partner_logistic_id, created_at, updated_at
            FROM businesses
            WHERE ig_page ILIKE $1
               OR facebook_page ILIKE $1
               OR twitter_page ILIKE $1
               OR tiktok ILIKE $1
               OR phone_number ILIKE $1
               OR email ILIKE $1
            LIMIT 1
        """
        params = (bid,)

    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(query, *params)
            return dict(row) if row else None
    except Exception:
        logger.error(
            "get_business_info_failed | business_id=%s", business_id, exc_info=True
        )
        return None


async def get_business_by_handle(handle: str) -> Optional[Dict[str, Any]]:
    """
    Search for business by social media handle or contact info.

    Args:
        handle: Social media handle, phone, or email

    Returns:
        Business dictionary or None
    """
    pool = await get_db()

    query = """
        SELECT id, name, business_type, tier, phone_number, email,
               ig_page, facebook_page, twitter_page, tiktok,
               bank_name, bank_account_number, bank_account_name,
               paystack_public_key, paystack_secret_key,
               human_agent_phone, human_agent_email,
               product_schema, currency, partner_logistic_id, created_at, updated_at
        FROM businesses
        WHERE ig_page ILIKE $1
           OR facebook_page ILIKE $1
           OR twitter_page ILIKE $1
           OR tiktok ILIKE $1
           OR phone_number ILIKE $1
           OR email ILIKE $1
        LIMIT 1
    """

    async with pool.acquire() as conn:
        row = await conn.fetchrow(query, handle)
        return dict(row) if row else None


async def get_logistics_companies(limit: int = 10) -> List[Dict[str, Any]]:
    """Get logistics companies (business_type='logistics')."""
    pool = await get_db()
    query = """
        SELECT id, name, phone_number, email
        FROM businesses
        WHERE business_type = 'logistics'
        LIMIT $1
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(query, limit)
        return [dict(row) for row in rows]


async def pick_random_logistics_company_id(limit: int = 20) -> Optional[str]:
    """Return a random registered logistics business id, or None."""
    rows = await get_logistics_companies(limit=limit)
    if not rows:
        return None
    import random

    return str(random.choice(rows)["id"])


## USER FUNCTIONS


async def get_user_by_phone(phone_number: str) -> Optional[Dict[str, Any]]:
    """Get user by phone number."""
    pool = await get_db()

    query = """
        SELECT id, phone_number, full_name, delivery_address, city, state,
               created_at, updated_at
        FROM users
        WHERE phone_number = $1
    """

    async with pool.acquire() as conn:
        row = await conn.fetchrow(query, phone_number)
        return dict(row) if row else None


async def get_user_by_id(user_id: str) -> Optional[Dict[str, Any]]:
    """Get user by ID."""
    pool = await get_db()

    query = """
        SELECT id, phone_number, full_name, delivery_address, city, state,
               created_at, updated_at
        FROM users
        WHERE id = $1::uuid
    """

    async with pool.acquire() as conn:
        row = await conn.fetchrow(query, user_id)
        return dict(row) if row else None


async def create_or_update_user(
    phone_number: str,
    full_name: str = None,
    delivery_address: str = None,
    city: str = None,
    state: str = None,
) -> Dict[str, Any] | None:
    """
    Create a new user or update existing user information.

    Args:
        phone_number: User's phone number (required, unique)
        full_name: User's full name
        delivery_address: Delivery address
        city: City
        state: State

    Returns:
        Created or updated user dictionary
    """
    pool = await get_db()

    query = """
        INSERT INTO users (phone_number, full_name, delivery_address, city, state)
        VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT (phone_number) DO UPDATE SET
            full_name = COALESCE(EXCLUDED.full_name, users.full_name),
            delivery_address = COALESCE(EXCLUDED.delivery_address, users.delivery_address),
            city = COALESCE(EXCLUDED.city, users.city),
            state = COALESCE(EXCLUDED.state, users.state),
            updated_at = NOW()
        RETURNING id, phone_number, full_name, delivery_address, city, state,
                  created_at, updated_at
    """

    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                query, phone_number, full_name, delivery_address, city, state
            )
            return dict(row)
    except Exception:
        logger.error(
            "create_or_update_user_failed | phone=%s", phone_number, exc_info=True
        )
        return None


## ORDER FUNCTIONS


async def create_order(
    user_id: str,
    business_id: str,
    total_amount: float,
    quantity: int = 1,
    delivery_address: str = None,
    delivery_city: str = None,
    delivery_state: str = None,
    metadata: dict = None,
    product_name: Optional[str] = None,
    product_attributes: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Create a new order.

    Args:
        user_id: Customer UUID
        business_id: Vendor UUID
        total_amount: Order total
        quantity: Quantity ordered (default 1)
        delivery_address: Delivery address (optional)
        delivery_city: Delivery city
        delivery_state: Delivery state
        metadata: JSONB metadata (extra keys; quantity still mirrored here for compatibility)
        product_name: Purchased product display name
        product_attributes: JSON-serializable dict (size, color, product_id, etc.)

    Returns:
        Created order dictionary
    """
    pool = await get_db()
    import secrets
    from datetime import datetime

    order_number = (
        f"ORD-{datetime.now().strftime('%Y%m%d')}-{secrets.token_hex(4).upper()}"
    )
    meta = dict(metadata) if metadata else {}
    meta.setdefault("quantity", quantity)
    if product_name:
        meta.setdefault("product_name", product_name)

    pattr: Dict[str, Any] = {}
    if isinstance(product_attributes, dict):
        pattr = dict(product_attributes)

    query = """
        INSERT INTO orders (
            order_number, user_id, business_id, total_amount,
            delivery_address, delivery_city, delivery_state,
            product_name, product_attributes,
            status, metadata
        )
        VALUES ($1, $2::uuid, $3::uuid, $4, $5, $6, $7, $8, $9, 'pending', $10)
        RETURNING id, order_number, user_id, business_id, logistic_id,
                  status, total_amount, delivery_address, delivery_city,
                  delivery_state, tracking_number, product_name, product_attributes,
                  metadata,
                  created_at, updated_at
    """

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            query,
            order_number,
            user_id,
            business_id,
            total_amount,
            delivery_address,
            delivery_city,
            delivery_state,
            product_name,
            pattr,
            meta,
        )
        return dict(row)


async def update_order_status(
    order_id: str,
    status: str,
    tracking_number: str = "",
    logistic_id: str = "",
) -> Dict[str, Any] | None:
    """
    Update order status and optionally assign logistics.

    Args:
        order_id: Order UUID
        status: New status (pending, payment_verified, shipped, delivered, cancelled)
        tracking_number: Optional tracking number
        logistic_id: Optional logistics company UUID

    Returns:
        Updated order dictionary
    """
    pool = await get_db()

    query = """
        UPDATE orders
        SET status = $2,
            tracking_number = COALESCE($3, tracking_number),
            logistic_id = COALESCE($4::uuid, logistic_id),
            updated_at = NOW()
        WHERE id = $1::uuid
        RETURNING id, order_number, user_id, business_id, logistic_id,
                  status, total_amount, delivery_address, delivery_city,
                  delivery_state, tracking_number, product_name, product_attributes,
                  metadata,
                  created_at, updated_at
    """

    async with pool.acquire() as conn:
        row = await conn.fetchrow(query, order_id, status, tracking_number, logistic_id)
        return dict(row) if row else None


async def record_paystack_webhook_event(
    reference: str,
    user_id: str,
    business_id: str,
    amount_kobo: Optional[int] = None,
    currency: Optional[str] = None,
) -> bool:
    """
    Idempotent insert for Paystack charge.success. Returns True if a new row was stored.
    """
    if not reference or not user_id or not business_id:
        return False
    pool = await get_db()
    query = """
        INSERT INTO paystack_webhook_events (reference, user_id, business_id, amount_kobo, currency)
        VALUES ($1, $2::uuid, $3::uuid, $4, $5)
        ON CONFLICT (reference) DO NOTHING
        RETURNING reference
    """
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                query, reference, user_id, business_id, amount_kobo, currency
            )
            return row is not None
    except Exception:
        logger.exception("record_paystack_webhook_event_failed | ref=%s", reference)
        return False


def _valid_uuid(s: str) -> bool:
    try:
        uuid.UUID(str(s).strip())
        return True
    except (ValueError, TypeError):
        return False


async def upsert_order_process_link(
    order_id: str,
    process_id: str,
    user_id: str,
    business_id: str,
) -> None:
    """Persist order ↔ chat process_id for reconciliation and cross-system sync."""
    if not _valid_uuid(order_id) or not _valid_uuid(process_id):
        logger.warning(
            "upsert_order_process_link_skip_invalid_uuid | order_id=%s process_id=%s",
            order_id,
            process_id,
        )
        return
    pool = await get_db()
    query = """
        INSERT INTO order_process_links (order_id, process_id, user_id, business_id, updated_at)
        VALUES ($1::uuid, $2::uuid, $3::uuid, $4::uuid, NOW())
        ON CONFLICT (order_id) DO UPDATE SET
            process_id = EXCLUDED.process_id,
            user_id = EXCLUDED.user_id,
            business_id = EXCLUDED.business_id,
            updated_at = NOW()
    """
    try:
        async with pool.acquire() as conn:
            await conn.execute(query, order_id, process_id, user_id, business_id)
    except Exception:
        logger.exception(
            "upsert_order_process_link_failed | order_id=%s process_id=%s",
            order_id,
            process_id,
        )


async def mark_order_process_link_completed(order_id: str) -> None:
    if not order_id or not _valid_uuid(order_id):
        return
    pool = await get_db()
    query = """
        UPDATE order_process_links
        SET process_completed_at = COALESCE(process_completed_at, NOW()),
            updated_at = NOW()
        WHERE order_id = $1::uuid
    """
    try:
        async with pool.acquire() as conn:
            await conn.execute(query, order_id)
    except Exception:
        logger.exception("mark_order_process_link_completed_failed | order_id=%s", order_id)


async def touch_order_process_link(order_id: str) -> None:
    """Bump link row when the order row changes (status, tracking, etc.)."""
    if not order_id or not _valid_uuid(order_id):
        return
    pool = await get_db()
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE order_process_links SET updated_at = NOW()
                WHERE order_id = $1::uuid
                """,
                order_id,
            )
    except Exception:
        logger.exception("touch_order_process_link_failed | order_id=%s", order_id)


async def list_paystack_webhooks_missing_recent_order(
    lookback_days: int = 7,
) -> List[Dict[str, Any]]:
    """
    Heuristic: webhook recorded but no order for same user+business in the 14 days after the event.
    Use for manual reconciliation / alerts (not a guarantee of payment-without-order).
    """
    pool = await get_db()
    days = max(1, min(int(lookback_days), 365))
    query = """
        SELECT w.reference, w.user_id, w.business_id, w.amount_kobo, w.currency, w.created_at
        FROM paystack_webhook_events w
        WHERE w.created_at > NOW() - ($1::int * interval '1 day')
        AND NOT EXISTS (
            SELECT 1 FROM orders o
            WHERE o.user_id = w.user_id
              AND o.business_id = w.business_id
              AND o.created_at >= w.created_at
              AND o.created_at <= w.created_at + interval '14 days'
        )
        ORDER BY w.created_at DESC
        LIMIT 500
    """
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(query, days)
            return [dict(r) for r in rows]
    except Exception:
        logger.exception("list_paystack_webhooks_missing_recent_order_failed")
        return []


async def get_order_by_id(order_id: str) -> Optional[Dict[str, Any]]:
    """Get order by ID."""
    pool = await get_db()

    query = """
        SELECT id, order_number, user_id, business_id, logistic_id,
               status, total_amount, delivery_address, delivery_city,
               delivery_state, tracking_number, product_name, product_attributes,
               metadata,
               created_at, updated_at
        FROM orders
        WHERE id = $1::uuid
    """

    async with pool.acquire() as conn:
        row = await conn.fetchrow(query, order_id)
        return dict(row) if row else None


async def get_order_by_number(order_number: str) -> Optional[Dict[str, Any]]:
    """Get order by order number."""
    pool = await get_db()

    query = """
        SELECT id, order_number, user_id, business_id, logistic_id,
               status, total_amount, delivery_address, delivery_city,
               delivery_state, tracking_number, product_name, product_attributes,
               metadata,
               created_at, updated_at
        FROM orders
        WHERE order_number = $1
    """

    async with pool.acquire() as conn:
        row = await conn.fetchrow(query, order_number)
        return dict(row) if row else None


async def get_orders_by_user(user_id: str, limit: int = 10) -> List[Dict[str, Any]]:
    """Get orders for a user."""
    pool = await get_db()

    query = """
        SELECT id, order_number, user_id, business_id, logistic_id,
               status, total_amount, delivery_address, delivery_city,
               delivery_state, tracking_number, product_name, product_attributes,
               metadata,
               created_at, updated_at
        FROM orders
        WHERE user_id = $1::uuid
        ORDER BY created_at DESC
        LIMIT $2
    """

    async with pool.acquire() as conn:
        rows = await conn.fetch(query, user_id, limit)
        return [dict(row) for row in rows]


async def list_orders_for_customer_store(
    user_id: str,
    business_id: str,
    *,
    limit: int = 50,
    offset: int = 0,
    on_date: Optional[str] = None,
    created_after_iso: Optional[str] = None,
    created_before_iso: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Orders for one customer at one vendor. Optional filters: calendar day (YYYY-MM-DD UTC), ISO time window."""
    if not _valid_uuid(user_id) or not _valid_uuid(business_id):
        return []

    from datetime import date, datetime, timedelta, timezone

    def _parse_iso(s: Optional[str]):
        if not s or not str(s).strip():
            return None
        try:
            t = str(s).strip().replace("Z", "+00:00")
            dt = datetime.fromisoformat(t)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            return None

    parts = ["user_id = $1::uuid", "business_id = $2::uuid"]
    params: List[Any] = [user_id, business_id]
    i = 3

    if on_date:
        try:
            d = date.fromisoformat(str(on_date).strip()[:10])
            start = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
            end = start + timedelta(days=1)
            parts.append(f"created_at >= ${i} AND created_at < ${i + 1}")
            params.extend([start, end])
            i += 2
        except ValueError:
            pass

    aft = _parse_iso(created_after_iso)
    if aft:
        parts.append(f"created_at >= ${i}")
        params.append(aft)
        i += 1

    bfr = _parse_iso(created_before_iso)
    if bfr:
        parts.append(f"created_at <= ${i}")
        params.append(bfr)
        i += 1

    query = f"""
        SELECT id, order_number, user_id, business_id, logistic_id,
               status, total_amount, delivery_address, delivery_city,
               delivery_state, tracking_number, product_name, product_attributes,
               metadata,
               created_at, updated_at
        FROM orders
        WHERE {" AND ".join(parts)}
        ORDER BY created_at DESC
        LIMIT ${i} OFFSET ${i + 1}
    """
    params.extend([limit, offset])

    pool = await get_db()
    async with pool.acquire() as conn:
        rows = await conn.fetch(query, *params)
        return [dict(row) for row in rows]


async def get_orders_by_business(
    business_id: str, status: str = None, limit: int = 50
) -> List[Dict[str, Any]]:
    """Get orders for a business, optionally filtered by status."""
    pool = await get_db()

    query = """
        SELECT id, order_number, user_id, business_id, logistic_id,
               status, total_amount, delivery_address, delivery_city,
               delivery_state, tracking_number, product_name, product_attributes,
               metadata,
               created_at, updated_at
        FROM orders
        WHERE business_id = $1::uuid
    """

    params = [business_id]
    param_count = 2

    if status:
        query += f" AND status = ${param_count}"
        params.append(status)
        param_count += 1

    query += f" ORDER BY created_at DESC LIMIT ${param_count}"
    params.append(limit)

    async with pool.acquire() as conn:
        rows = await conn.fetch(query, *params)
        return [dict(row) for row in rows]


## TRANSACTION FUNCTIONS


async def create_transaction(
    user_id: str,
    business_id: str,
    amount: float,
    payment_method: str = None,
    order_id: str = None,
    receipt_image_url: str = None,
    transaction_reference: str = None,
    bank_name: str = None,
    account_number: str = None,
    metadata: dict = None,
) -> Dict[str, Any]:
    """
    Create a new transaction record.

    Args:
        user_id: Customer UUID
        business_id: Vendor UUID
        amount: Transaction amount
        payment_method: Payment method (bank_transfer, paystack, cash)
        order_id: Optional order UUID
        receipt_image_url: Optional receipt image URL
        transaction_reference: Optional transaction reference
        bank_name: Optional bank name
        account_number: Optional account number
        metadata: JSONB metadata

    Returns:
        Created transaction dictionary
    """
    pool = await get_db()

    query = """
        INSERT INTO transactions (
            user_id, business_id, amount, payment_method, order_id,
            receipt_image_url, transaction_reference, bank_name,
            account_number, status, metadata
        )
        VALUES (
            $1::uuid, $2::uuid, $3, $4, $5::uuid,
            $6, $7, $8, $9, 'pending', $10
        )
        RETURNING id, order_id, user_id, business_id, status, amount,
                  payment_method, receipt_image_url, transaction_reference,
                  bank_name, account_number, metadata,
                  created_at, verified_at
    """

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            query,
            user_id,
            business_id,
            amount,
            payment_method,
            order_id,
            receipt_image_url,
            transaction_reference,
            bank_name,
            account_number,
            metadata or {},
        )
        return dict(row)


async def verify_transaction(transaction_id: str) -> Dict[str, Any]:
    """
    Mark a transaction as verified.

    Args:
        transaction_id: Transaction UUID

    Returns:
        Updated transaction dictionary
    """
    pool = await get_db()

    query = """
        UPDATE transactions
        SET status = 'verified',
            verified_at = NOW()
        WHERE id = $1::uuid
        RETURNING id, order_id, user_id, business_id, status, amount,
                  payment_method, receipt_image_url, transaction_reference,
                  bank_name, account_number, metadata,
                  created_at, verified_at
    """

    async with pool.acquire() as conn:
        row = await conn.fetchrow(query, transaction_id)
        return dict(row) if row else None


async def get_pending_transactions(business_id: str) -> List[Dict[str, Any]]:
    """Get all pending transactions for a business."""
    pool = await get_db()

    query = """
        SELECT id, order_id, user_id, business_id, status, amount,
               payment_method, receipt_image_url, transaction_reference,
               bank_name, account_number, metadata,
               created_at, verified_at
        FROM transactions
        WHERE business_id = $1::uuid AND status = 'pending'
        ORDER BY created_at DESC
    """

    async with pool.acquire() as conn:
        rows = await conn.fetch(query, business_id)
        return [dict(row) for row in rows]


async def get_transaction_by_id(transaction_id: str) -> Optional[Dict[str, Any]]:
    """Get transaction by ID."""
    pool = await get_db()

    query = """
        SELECT id, order_id, user_id, business_id, status, amount,
               payment_method, receipt_image_url, transaction_reference,
               bank_name, account_number, metadata,
               created_at, verified_at
        FROM transactions
        WHERE id = $1::uuid
    """

    async with pool.acquire() as conn:
        row = await conn.fetchrow(query, transaction_id)
        return dict(row) if row else None


async def get_transaction_by_reference(
    transaction_reference: str,
) -> Optional[Dict[str, Any]]:
    """Get transaction by reference number."""
    pool = await get_db()

    query = """
        SELECT id, order_id, user_id, business_id, status, amount,
               payment_method, receipt_image_url, transaction_reference,
               bank_name, account_number, metadata,
               created_at, verified_at
        FROM transactions
        WHERE transaction_reference = $1
    """

    async with pool.acquire() as conn:
        row = await conn.fetchrow(query, transaction_reference)
        return dict(row) if row else None


## BUSINESS ANALYTICS FUNCTIONS


async def get_business_analytics(
    business_id: str, start_date: str = None, end_date: str = None
) -> Dict[str, Any]:
    """
    Get business analytics including sales, orders, and revenue.

    Args:
        business_id: Business UUID
        start_date: Optional start date (ISO format)
        end_date: Optional end date (ISO format)

    Returns:
        Dictionary with analytics data
    """
    pool = await get_db()

    # Base query filters
    date_filter = ""
    params = [business_id]
    param_count = 2

    if start_date:
        date_filter += f" AND t.created_at >= ${param_count}::timestamp"
        params.append(start_date)
        param_count += 1

    if end_date:
        date_filter += f" AND t.created_at <= ${param_count}::timestamp"
        params.append(end_date)
        param_count += 1

    # Total sales and transactions
    sales_query = f"""
        SELECT
            COALESCE(SUM(t.amount), 0) as total_sales,
            COUNT(t.id) as total_transactions,
            COALESCE(AVG(t.amount), 0) as avg_transaction_value
        FROM transactions t
        WHERE t.business_id = $1::uuid
          AND t.status = 'verified'
          {date_filter}
    """

    # Order statistics
    orders_query = f"""
        SELECT
            COUNT(o.id) as total_orders,
            COALESCE(SUM(o.total_amount), 0) as total_revenue,
            COUNT(CASE WHEN o.status = 'delivered' THEN 1 END) as delivered_orders,
            COUNT(CASE WHEN o.status = 'pending' THEN 1 END) as pending_orders
        FROM orders o
        WHERE o.business_id = $1::uuid
          {date_filter.replace("t.created_at", "o.created_at")}
    """

    # Product performance
    products_query = f"""
        SELECT
            p.name,
            p.id,
            COUNT(DISTINCT o.id) as order_count,
            COALESCE(SUM(o.total_amount), 0) as revenue
        FROM products p
        LEFT JOIN orders o ON o.business_id = p.business_id
          AND o.metadata->>'product_id' = p.id::text
          {date_filter.replace("t.created_at", "o.created_at") if date_filter else ""}
        WHERE p.business_id = $1::uuid AND p.is_active = true
        GROUP BY p.id, p.name
        ORDER BY revenue DESC
        LIMIT 10
    """

    async with pool.acquire() as conn:
        sales_row = await conn.fetchrow(sales_query, *params)
        orders_row = await conn.fetchrow(orders_query, *params)
        products_rows = await conn.fetch(products_query, *params)

        return {
            "business_id": business_id,
            "sales": {
                "total_sales": float(sales_row["total_sales"]),
                "total_transactions": sales_row["total_transactions"],
                "average_transaction_value": float(sales_row["avg_transaction_value"]),
            },
            "orders": {
                "total_orders": orders_row["total_orders"],
                "total_revenue": float(orders_row["total_revenue"]),
                "delivered_orders": orders_row["delivered_orders"],
                "pending_orders": orders_row["pending_orders"],
            },
            "top_products": [dict(row) for row in products_rows],
        }


## INVENTORY FUNCTIONS


async def get_inventory(business_id: str) -> List[Dict[str, Any]]:
    """
    Get inventory information for a business.

    Args:
        business_id: Business UUID

    Returns:
        List of inventory items with stock levels
    """
    pool = await get_db()

    query = f"""
        SELECT
            p.id, p.name, p.description, p.price, p.stock_quantity,
            p.sku, p.category, p.is_active,
            {_EFF_CURRENCY} AS currency,
            CASE
                WHEN p.stock_quantity <= 0 THEN 'out_of_stock'
                WHEN p.stock_quantity <= 10 THEN 'low_stock'
                ELSE 'in_stock'
            END as stock_status
        FROM products p
        INNER JOIN businesses b ON b.id = p.business_id
        WHERE p.business_id = $1::uuid AND p.is_active = true
        ORDER BY p.stock_quantity ASC, p.name ASC
    """

    async with pool.acquire() as conn:
        rows = await conn.fetch(query, business_id)
        return [dict(row) for row in rows]


async def update_product_stock(
    product_id: str, stock_quantity: int
) -> Optional[Dict[str, Any]]:
    """
    Update product stock quantity.

    Args:
        product_id: Product UUID
        stock_quantity: New stock quantity

    Returns:
        Updated product dictionary or None if not found
    """
    pool = await get_db()

    query = """
        UPDATE products
        SET stock_quantity = $2,
            updated_at = NOW()
        WHERE id = $1::uuid
        RETURNING id, name, stock_quantity, sku, category, updated_at
    """

    async with pool.acquire() as conn:
        row = await conn.fetchrow(query, product_id, stock_quantity)
        return dict(row) if row else None


async def update_product_stock_for_business(
    business_id: str,
    product_id: str,
    stock_quantity: int,
) -> Optional[Dict[str, Any]]:
    """Scoped stock update: row must belong to business_id."""
    pool = await get_db()
    query = """
        UPDATE products
        SET stock_quantity = $3,
            updated_at = NOW()
        WHERE id = $2::uuid AND business_id = $1::uuid
        RETURNING id, name, stock_quantity, sku, category, price, updated_at
    """
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                query, business_id, product_id, int(stock_quantity)
            )
            if not row:
                return None
            row_dict = dict(row)
            await _maybe_log_inventory_activity(
                business_id,
                {
                    "at": datetime.now(timezone.utc).isoformat(),
                    "kind": "stock",
                    "product_id": str(row_dict.get("id", "")),
                    "name": row_dict.get("name"),
                    "stock_quantity": int(row_dict.get("stock_quantity") or 0),
                    "price": float(row_dict.get("price") or 0),
                    "currency": row_dict.get("currency"),
                },
            )
            return row_dict
    except Exception:
        logger.exception(
            "update_product_stock_for_business_failed | business_id=%s product_id=%s",
            business_id,
            product_id,
        )
        return None


async def update_product_price_for_business(
    business_id: str,
    product_id: str,
    price: float,
) -> Optional[Dict[str, Any]]:
    """Scoped price update: row must belong to business_id."""
    pool = await get_db()
    query = """
        UPDATE products
        SET price = $3,
            updated_at = NOW()
        WHERE id = $2::uuid AND business_id = $1::uuid
        RETURNING id, name, price, stock_quantity, sku, category, updated_at
    """
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                query, business_id, product_id, float(price)
            )
            if not row:
                return None
            row_dict = dict(row)
            await _maybe_log_inventory_activity(
                business_id,
                {
                    "at": datetime.now(timezone.utc).isoformat(),
                    "kind": "price",
                    "product_id": str(row_dict.get("id", "")),
                    "name": row_dict.get("name"),
                    "stock_quantity": int(row_dict.get("stock_quantity") or 0),
                    "price": float(row_dict.get("price") or 0),
                    "currency": row_dict.get("currency"),
                },
            )
            return row_dict
    except Exception:
        logger.exception(
            "update_product_price_for_business_failed | business_id=%s product_id=%s",
            business_id,
            product_id,
        )
        return None


async def get_low_stock_products(
    business_id: str, threshold: int = 10
) -> List[Dict[str, Any]]:
    """
    Get products with low stock levels.

    Args:
        business_id: Business UUID
        threshold: Stock threshold (default 10)

    Returns:
        List of products with stock below threshold
    """
    pool = await get_db()

    query = f"""
        SELECT p.id, p.name, p.stock_quantity, p.sku, p.category,
               {_EFF_CURRENCY} AS currency
        FROM products p
        INNER JOIN businesses b ON b.id = p.business_id
        WHERE p.business_id = $1::uuid
          AND p.stock_quantity <= $2
          AND p.is_active = true
        ORDER BY p.stock_quantity ASC
    """

    async with pool.acquire() as conn:
        rows = await conn.fetch(query, business_id, threshold)
        return [dict(row) for row in rows]


async def add_product(
    business_id: str,
    name: str,
    price: float,
    stock_quantity: int = 0,
    description: str = "",
    category: str = "",
    sku: str = "",
    attributes: Optional[dict] = None,
    currency: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Insert a new product into the catalog. Returns the created product row."""
    pool = await get_db()
    import json as _json
    cur = (currency or "").strip() or None
    query = """
        INSERT INTO products AS p (business_id, name, description, price, stock_quantity, sku, category, attributes, currency)
        VALUES ($1::uuid, $2, $3, $4, $5, $6, $7, $8::jsonb, $9)
        RETURNING p.id, p.business_id, p.name, p.description, p.price, p.stock_quantity,
                  p.sku, p.category, p.attributes, p.is_active, p.created_at, p.updated_at,
                  COALESCE(p.currency, (SELECT b.currency FROM businesses b WHERE b.id = p.business_id), 'NGN') AS currency
    """
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                query,
                business_id, name, description, price, stock_quantity,
                sku or None, category or None,
                _json.dumps(attributes) if attributes else "{}",
                cur,
            )
            if not row:
                return None
            row_dict = dict(row)
            await _maybe_log_inventory_activity(
                business_id,
                {
                    "at": datetime.now(timezone.utc).isoformat(),
                    "kind": "add",
                    "product_id": str(row_dict.get("id", "")),
                    "name": row_dict.get("name"),
                    "stock_quantity": int(row_dict.get("stock_quantity") or 0),
                    "price": float(row_dict.get("price") or 0),
                    "currency": row_dict.get("currency"),
                },
            )
            return row_dict
    except Exception:
        logger.error("add_product_failed | business_id=%s name=%s", business_id, name, exc_info=True)
        return None


async def upsert_chat_summary(
    user_id: str,
    business_id: str,
    summary: str,
    messages_summarized: int,
) -> None:
    """Insert or update the running chat summary for a user-vendor pair."""
    pool = await get_db()
    query = """
        INSERT INTO chat_history_summaries (user_id, business_id, summary, messages_summarized)
        VALUES ($1::uuid, $2::uuid, $3, $4)
        ON CONFLICT (user_id, business_id) DO UPDATE SET
            summary = EXCLUDED.summary,
            messages_summarized = chat_history_summaries.messages_summarized + EXCLUDED.messages_summarized,
            updated_at = NOW()
    """
    try:
        async with pool.acquire() as conn:
            await conn.execute(query, user_id, business_id, summary, messages_summarized)
    except Exception:
        logger.error("upsert_chat_summary_failed | user=%s biz=%s", user_id, business_id, exc_info=True)


async def get_chat_summary(user_id: str, business_id: str) -> Optional[str]:
    """Retrieve the stored chat summary for a user-vendor pair."""
    pool = await get_db()
    query = """
        SELECT summary FROM chat_history_summaries
        WHERE user_id = $1::uuid AND business_id = $2::uuid
        LIMIT 1
    """
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(query, user_id, business_id)
            return row["summary"] if row else None
    except Exception:
        logger.error("get_chat_summary_failed | user=%s biz=%s", user_id, business_id, exc_info=True)
        return None


async def insert_conversation_uploaded_file(
    user_id: str,
    business_id: str,
    *,
    file_url: Optional[str],
    file_content_type: str,
    description: str,
    text_content: str,
) -> str:
    """Insert row; returns new file id as str."""
    pool = await get_db()
    q = """
        INSERT INTO conversation_uploaded_files
            (user_id, business_id, file_url, file_content_type, description, text_content)
        VALUES ($1::uuid, $2::uuid, $3, $4, $5, $6)
        RETURNING id::text
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            q, user_id, business_id, file_url, file_content_type, description, text_content
        )
        return row["id"] if row else ""


async def get_conversation_uploaded_file(
    file_id: str, user_id: str, business_id: str
) -> Optional[Dict[str, Any]]:
    pool = await get_db()
    q = """
        SELECT id::text AS id, file_url, file_content_type, description, text_content, created_at
        FROM conversation_uploaded_files
        WHERE id = $1::uuid AND user_id = $2::uuid AND business_id = $3::uuid
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow(q, file_id, user_id, business_id)
        return dict(row) if row else None
