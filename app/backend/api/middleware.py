"""
Rate-limiting middleware using Redis sliding-window counters.
Falls back to in-memory tracking when Redis is unavailable.
"""
import asyncio
import time
from collections import defaultdict

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from backend.config import (
    RATE_LIMIT_ENABLED,
    RATE_LIMIT_REQUESTS,
    RATE_LIMIT_WINDOW_SECONDS,
)

SKIP_PATHS = frozenset(("/", "/health", "/docs", "/openapi.json", "/redoc"))


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, max_requests: int = RATE_LIMIT_REQUESTS, window: int = RATE_LIMIT_WINDOW_SECONDS):
        super().__init__(app)
        self.max_requests = max_requests
        self.window = window
        self._fallback: dict[str, list[float]] = defaultdict(list)

    async def dispatch(self, request: Request, call_next):
        if not RATE_LIMIT_ENABLED:
            return await call_next(request)
        path = request.url.path
        if path in SKIP_PATHS or path.startswith("/api/v1/payments/paystack/webhook"):
            return await call_next(request)

        client_ip = request.client.host if request.client else "unknown"
        allowed = await asyncio.to_thread(self._check_redis, client_ip)
        if allowed is None:
            allowed = self._check_memory(client_ip)

        if not allowed:
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded. Try again later."},
                headers={"Retry-After": str(self.window)},
            )

        return await call_next(request)

    def _check_redis(self, client_ip: str) -> bool | None:
        try:
            from backend.db.cache_utils import redis_conn
            r = redis_conn._client
            key = f"rate_limit:{client_ip}"
            now = time.time()
            pipe = r.pipeline()
            pipe.zremrangebyscore(key, 0, now - self.window)
            pipe.zadd(key, {str(now): now})
            pipe.zcard(key)
            pipe.expire(key, self.window)
            results = pipe.execute()
            return results[2] <= self.max_requests
        except Exception:
            return None

    def _check_memory(self, client_ip: str) -> bool:
        now = time.time()
        cutoff = now - self.window
        timestamps = self._fallback[client_ip]
        self._fallback[client_ip] = [t for t in timestamps if t > cutoff]
        self._fallback[client_ip].append(now)
        return len(self._fallback[client_ip]) <= self.max_requests
