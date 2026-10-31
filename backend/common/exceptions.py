"""
Consistent API error envelope.

Every error the API returns has the shape::

    {"error": {"code": "validation_error", "message": "...", "details": {...}}}

`code` is a stable machine-readable slug. The frontend switches on it (see
`frontend/src/lib/api.ts`), so changing one is a breaking API change; adding one is not.
"""

from __future__ import annotations

import logging
import uuid

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError
from django.http import Http404
from rest_framework import status
from rest_framework.exceptions import APIException
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

logger = logging.getLogger("compass.api")


class CompassError(APIException):
    """Base class for domain errors raised by service functions."""

    status_code = status.HTTP_400_BAD_REQUEST
    default_code = "compass_error"
    default_detail = "The request could not be completed."


class DomainValidationError(CompassError):
    status_code = status.HTTP_400_BAD_REQUEST
    default_code = "domain_validation_error"
    default_detail = "The request was rejected by a business rule."


class ConflictError(CompassError):
    status_code = status.HTTP_409_CONFLICT
    default_code = "conflict"
    default_detail = "The resource is in a state that conflicts with this request."


class ApprovalRequiredError(CompassError):
    """
    Raised when a workflow step that can change a system is attempted without approval.

    This is a 403 rather than a 400 because the request is well-formed; the caller simply
    is not authorised to take this specific action yet.
    """

    status_code = status.HTTP_403_FORBIDDEN
    default_code = "approval_required"
    default_detail = (
        "This step can change a running system and requires explicit approval from an "
        "authorised FDE or organization administrator before it can be completed."
    )


class IntegrationNotConfiguredError(CompassError):
    status_code = status.HTTP_409_CONFLICT
    default_code = "integration_not_configured"
    default_detail = (
        "This integration has no verified credentials configured, so it is operating in "
        "demo mode. Configure and verify credentials to enable connected mode."
    )


class IntegrationUnavailableError(CompassError):
    status_code = status.HTTP_502_BAD_GATEWAY
    default_code = "integration_unavailable"
    default_detail = "The external system could not be reached."


class ProviderUnavailableError(CompassError):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_code = "provider_unavailable"
    default_detail = "The configured AI provider is unavailable."


_CODE_BY_STATUS = {
    400: "bad_request",
    401: "not_authenticated",
    403: "permission_denied",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    415: "unsupported_media_type",
    429: "throttled",
    500: "internal_error",
    502: "integration_unavailable",
    503: "service_unavailable",
}


def _flatten_message(detail) -> str:
    """Produce one human-readable sentence from DRF's nested detail structures."""
    if isinstance(detail, str):
        return detail
    if isinstance(detail, dict):
        for key, value in detail.items():
            inner = _flatten_message(value)
            if key in {"detail", "non_field_errors"}:
                return inner
            return f"{key}: {inner}"
        return "Invalid request."
    if isinstance(detail, (list, tuple)):
        return _flatten_message(detail[0]) if detail else "Invalid request."
    return str(detail)


def compass_exception_handler(exc, context):
    """DRF exception handler producing the COMPASS error envelope."""
    # Translate Django-level exceptions into their DRF equivalents first.
    if isinstance(exc, DjangoValidationError):
        exc = DomainValidationError(detail=getattr(exc, "message_dict", None) or exc.messages)
    elif isinstance(exc, DjangoPermissionDenied):
        exc = APIException(detail=str(exc) or "Permission denied.")
        exc.status_code = status.HTTP_403_FORBIDDEN
    elif isinstance(exc, Http404):
        exc = APIException(detail="Not found.")
        exc.status_code = status.HTTP_404_NOT_FOUND
    elif isinstance(exc, IntegrityError):
        exc = ConflictError(detail="That change conflicts with an existing record.")

    response = drf_exception_handler(exc, context)

    if response is None:
        # Genuinely unexpected. Log with a correlation id and return an opaque 500 — the
        # traceback must not reach the client.
        incident_id = str(uuid.uuid4())
        view = context.get("view").__class__.__name__ if context.get("view") else "unknown"
        logger.exception("Unhandled exception in %s (incident %s)", view, incident_id)
        return Response(
            {
                "error": {
                    "code": "internal_error",
                    "message": "An unexpected error occurred. Please try again.",
                    "details": {"incident_id": incident_id},
                }
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    code = getattr(exc, "default_code", None)
    if isinstance(exc, APIException) and getattr(exc, "detail", None) is not None:
        detail_code = getattr(exc.detail, "code", None)
        if isinstance(detail_code, str):
            code = detail_code
    if not code or code == "error":
        code = _CODE_BY_STATUS.get(response.status_code, "error")

    details: dict = {}
    if isinstance(response.data, dict) and set(response.data) - {"detail"}:
        details = dict(response.data)
    elif isinstance(response.data, list):
        details = {"errors": response.data}

    message = _flatten_message(getattr(exc, "detail", response.data))

    if retry_after := response.headers.get("Retry-After"):
        details["retry_after_seconds"] = retry_after

    response.data = {"error": {"code": code, "message": message, "details": details}}
    return response
