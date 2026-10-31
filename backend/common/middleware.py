"""
Request-scoped context.

Audit logging needs the actor's IP and user agent, but a service function must not receive
`request` (see the architecture skill). A thread-local set here lets
`common.audit.record_audit()` capture request metadata without threading `request` through
five layers of service calls.
"""

from __future__ import annotations

import threading
import uuid
from typing import Any

_local = threading.local()


def get_request_context() -> dict[str, Any]:
    return getattr(_local, "context", {}) or {}


def _client_ip(request) -> str:
    """
    Best-effort client IP.

    Only trusts `X-Forwarded-For` when the deployment sits behind a proxy that sets it.
    The left-most entry is used, which is correct behind a single trusted reverse proxy
    (nginx in `docker-compose.yml`). Behind a chain of untrusted proxies this value is
    client-controlled, so it is recorded as advisory audit metadata and is never used for
    an authorization decision.
    """
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()[:45]
    return (request.META.get("REMOTE_ADDR") or "")[:45]


class RequestContextMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        _local.context = {
            "request_id": request_id,
            "ip_address": _client_ip(request),
            "user_agent": (request.META.get("HTTP_USER_AGENT") or "")[:400],
            "path": request.path[:400],
            "method": request.method,
        }
        try:
            response = self.get_response(request)
        finally:
            _local.context = {}
        response["X-Request-ID"] = request_id
        return response
