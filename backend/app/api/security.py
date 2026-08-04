"""HTTP production-security middleware without request-body logging."""

import asyncio
import logging
import time
import uuid
from collections import defaultdict, deque

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

logger = logging.getLogger("copilot.http")


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: object, production: bool) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._production = production

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        started = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), geolocation=()"
        if request.url.path.startswith("/api/admin"):
            response.headers["Cache-Control"] = "no-store"
        if self._production:
            response.headers["Content-Security-Policy"] = (
                "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"
            )
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        logger.info(
            "request_complete method=%s path=%s status=%s duration_ms=%s request_id=%s",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
            request_id,
        )
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Bound sensitive endpoints per process without logging credentials."""

    def __init__(self, app: object, login_limit: int, credential_limit: int) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._login_limit = login_limit
        self._credential_limit = credential_limit
        self._requests: dict[str, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        limit = self._limit_for(request)
        if limit is None:
            return await call_next(request)
        client = request.client.host if request.client is not None else "unknown"
        key = f"{client}:{request.method}:{request.url.path}"
        now = time.monotonic()
        async with self._lock:
            window = self._requests[key]
            while window and window[0] <= now - 60:
                window.popleft()
            if len(window) >= limit:
                return JSONResponse(
                    {"error": "rate_limit_exceeded"},
                    status_code=429,
                    headers={"Retry-After": "60", "Cache-Control": "no-store"},
                )
            window.append(now)
        return await call_next(request)

    def _limit_for(self, request: Request) -> int | None:
        if request.method == "POST" and request.url.path == "/api/auth/login":
            return self._login_limit
        if request.url.path.startswith("/api/admin/providers/") and request.method in {
            "POST",
            "PUT",
        }:
            return self._credential_limit
        return None
