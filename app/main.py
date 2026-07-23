"""
Main FastAPI application for Ottobiz
"""
import logging
import os
import sys

# Configure logging FIRST, before any other import — several modules
# (backend/whatsapp/utils.py, backend/logging_config.py) call
# logging.basicConfig() themselves at import time, and basicConfig() is a
# silent no-op once the root logger already has a handler. Whichever call
# wins that race previously left `logger.exception(...)` calls (e.g.
# customer.py's "customer_chat failed") writing only to a file inside the
# container's ephemeral filesystem — invisible to `docker logs` / any
# platform's log viewer (Dokploy, etc). `force=True` + a stdout handler here
# guarantees errors are always visible via container logs, regardless of
# import order.
LOG_FILE = os.getenv("LOG_FILE", "").strip()
_log_handlers = [logging.StreamHandler(sys.stdout)]
if LOG_FILE:
    _log_handlers.append(logging.FileHandler(LOG_FILE))
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s | %(message)s",
    handlers=_log_handlers,
    force=True,
)

import asyncio
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv

# Import routers
from backend.api.routers import customer, business, logistics, analytics, inventory, supply_chain, session, payments, demo
from backend.whatsapp.routers import router as whatsapp_router

# Import legacy endpoints for backward compatibility
from backend.chatbot.interface.user_chat_interface import chat
from backend.chatbot.interface.business_chat_interface import business_chat
from backend.struct import UserRequest, BusinessRequest

load_dotenv()

import logfire
logfire.configure(send_to_logfire="if-token-present")

# Import database connection for lifecycle management
try:
    from backend.db.connection import init_db, close_db
    from backend.db.populate import populate_db_on_startup
    DB_AVAILABLE = True
except ImportError:
    DB_AVAILABLE = False
    populate_db_on_startup = None
    print("Warning: Database connection module not available")

# Create FastAPI app
app = FastAPI(
    title="Ottobiz API",
    description="Automated Business Platform API",
    version="1.0.0"
)

logfire.instrument_fastapi(app)


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    from fastapi.responses import JSONResponse
    if isinstance(exc, HTTPException):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    logging.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error."})


# Rate limiting (applied first, before CORS)
from backend.api.middleware import RateLimitMiddleware
app.add_middleware(RateLimitMiddleware)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Database lifecycle events
@app.on_event("startup")
async def startup_event():
    """Initialize database connection pool and populate on startup"""
    if not DB_AVAILABLE:
        logging.warning("Database connection not available - running without database")
        print("⚠ Database connection not available - running without database")
        return

    for attempt in range(10):
        try:
            await init_db()
            logging.info("✓ Database connection pool initialized")
            print("✓ Database connection pool initialized")
            if populate_db_on_startup:
                await populate_db_on_startup()
                print("✓ Database populated with migrations and dummy data")
            return
        except Exception as e:
            logging.warning(f"DB init attempt {attempt + 1}/10 failed: {e}")
            if attempt < 9:
                await asyncio.sleep(3)
            else:
                logging.error(f"✗ Failed to initialize database: {e}")
                print(f"✗ Failed to initialize database: {e}")
                raise


@app.on_event("shutdown")
async def shutdown_event():
    """Close database connection pool on shutdown"""
    if DB_AVAILABLE:
        try:
            await close_db()
            logging.info("✓ Database connection pool closed")
            print("✓ Database connection pool closed")
        except Exception as e:
            logging.error(f"✗ Failed to close database: {e}")
            print(f"✗ Failed to close database: {e}")

# Include routers
app.include_router(customer.router, prefix="/api/v1")
app.include_router(business.router, prefix="/api/v1")
app.include_router(logistics.router, prefix="/api/v1")
app.include_router(analytics.router, prefix="/api/v1")
app.include_router(inventory.router, prefix="/api/v1")
app.include_router(supply_chain.router, prefix="/api/v1")
app.include_router(session.router, prefix="/api/v1")
app.include_router(payments.router, prefix="/api/v1")
app.include_router(demo.router, prefix="/api/v1")  # demo-only payment simulation; safe to remove for prod
app.include_router(whatsapp_router, prefix="/whatsapp")

# Mount static files for uploads
if os.path.exists("uploads"):
    app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

# Legacy endpoints for backward compatibility
@app.post("/chat")
async def get_chat_response(user_request: UserRequest):
    """Legacy customer chat endpoint"""
    response = await chat(user_request, None)
    return {"message": response}


@app.post("/business_chat")
async def get_business_response(business_request: BusinessRequest):
    """Legacy business chat endpoint"""
    response = await business_chat(business_request, None)
    return {"message": response}


@app.get("/")
async def root():
    """Quick liveness check — useful in browser to confirm the API is reachable."""
    from datetime import datetime, timezone
    return {
        "status": "ok",
        "service": "Ottobiz API",
        "version": "1.0.0",
        "time": datetime.now(timezone.utc).isoformat(),
        "docs": "/docs",
        "health": "/health",
    }


@app.get("/health")
async def health_check():
    """Detailed health check — probes DB and Redis so you can confirm both are live."""
    from datetime import datetime, timezone
    import redis.asyncio as aioredis

    now = datetime.now(timezone.utc).isoformat()
    checks: dict = {}

    # --- Database ---
    try:
        from backend.db.connection import get_db
        pool = await get_db()
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        checks["database"] = "ok"
    except Exception as exc:
        checks["database"] = f"error: {exc}"

    # --- Redis ---
    try:
        redis_url = os.getenv("REDIS_URL", "")
        if redis_url:
            r = aioredis.from_url(redis_url, socket_connect_timeout=2)
            await r.ping()
            await r.aclose()
            checks["redis"] = "ok"
        else:
            checks["redis"] = "no REDIS_URL"
    except Exception as exc:
        checks["redis"] = f"error: {exc}"

    overall = "healthy" if all(v == "ok" for v in checks.values()) else "degraded"

    return {
        "status": overall,
        "service": "Ottobiz API",
        "version": "1.0.0",
        "time": now,
        "checks": checks,
        "endpoints": {
            "docs": "/docs",
            "customer_chat": "/api/v1/customer/chat",
            "business_chat": "/api/v1/business/chat",
            "logistics": "/api/v1/logistics",
            "analytics": "/api/v1/analytics",
            "inventory": "/api/v1/inventory",
            "supply_chain": "/api/v1/supply-chain",
            "session_clear": "/api/v1/session/clear",
            "session_context": "/api/v1/session/agent-context",
            "payments_webhook": "/api/v1/payments/paystack/webhook",
        },
    }


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)
