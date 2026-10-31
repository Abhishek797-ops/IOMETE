"""
Runtime capability reporting.

`/api/v1/system/status/` is how the frontend knows what is real. It drives the demo-mode
banner, the "simulated integration" labels, and the retrieval-backend disclosure in the
support UI.

The contract: this endpoint tells the truth about what is configured, and it never reports
an external system as connected on the strength of configuration alone. `integrations`
reports `demo` or `configured`; only an explicit connection test
(`POST /api/v1/integrations/{id}/test-connection/`) can produce `connected`, and that
result is stored with a timestamp on the integration record.
"""

from __future__ import annotations

from django.conf import settings
from django.db import connection
from django.http import JsonResponse
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView


def health(_request) -> JsonResponse:
    """Liveness probe. Deliberately leaks nothing about configuration."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception:
        return JsonResponse({"status": "degraded", "database": "unavailable"}, status=503)
    return JsonResponse({"status": "ok"})


def _vector_backend() -> dict[str, object]:
    """
    Report which vector-search backend will actually answer a query.

    Imported lazily so that `common` does not depend on `aiengine` at import time.
    """
    from aiengine.services.retrieval import describe_vector_backend

    return describe_vector_backend()


class SystemStatusView(APIView):
    """Public runtime-capability report."""

    permission_classes = [AllowAny]
    throttle_scope = "public"

    @extend_schema(
        tags=["system"],
        summary="Runtime capability and demo-mode report",
        description=(
            "Tells the client what is real in this deployment: whether it is running on "
            "synthetic demo data, which AI provider and embedding provider are active, "
            "which vector-search backend will answer retrieval queries, and whether each "
            "external integration is simulated or configured.\n\n"
            "An integration is never reported as `connected` here on the basis of "
            "configuration alone — only a successful live connection test can do that."
        ),
        responses={
            200: inline_serializer(
                name="SystemStatus",
                fields={
                    "demo_mode": serializers.BooleanField(),
                    "ai": serializers.DictField(),
                    "retrieval": serializers.DictField(),
                    "integrations": serializers.DictField(),
                    "knowledge_base": serializers.DictField(),
                },
            )
        },
    )
    def get(self, _request) -> Response:
        from integrations.services.registry import describe_integration_modes
        from knowledge.services.product_knowledge import knowledge_meta

        llm_provider = settings.LLM_PROVIDER
        llm_live = llm_provider == "gemini" and bool(settings.GEMINI_API_KEY)
        embed_provider = settings.EMBEDDING_PROVIDER
        embed_live = embed_provider == "gemini" and bool(settings.GEMINI_API_KEY)

        payload = {
            "demo_mode": settings.COMPASS_DEMO_MODE,
            "demo_mode_notice": (
                "Tickets, issue clusters and resolution playbooks in this deployment are "
                "synthetic engineering scenarios created for demonstration. They are not "
                "IOMETE incident records."
            )
            if settings.COMPASS_DEMO_MODE
            else "",
            "ai": {
                # `effective` is what will actually run, which is the only number that
                # matters to a user reading a generated answer.
                "llm_provider": llm_provider if llm_live else "demo",
                "llm_provider_requested": llm_provider,
                "llm_model": settings.LLM_MODEL if llm_live else "deterministic-demo",
                "llm_live": llm_live,
                "embedding_provider": embed_provider if embed_live else "hashing",
                "embedding_provider_requested": embed_provider,
                "embedding_dim": settings.EMBEDDING_DIM,
                "embedding_live": embed_live,
                "notice": (
                    ""
                    if llm_live
                    else "No LLM credentials are configured. Generated explanations come "
                    "from a deterministic demo provider: they are grounded in retrieved "
                    "records but are not produced by a language model."
                ),
            },
            "retrieval": {
                "strategy": "hybrid",
                "channels": ["vector", "lexical", "error_fingerprint", "metadata"],
                "weights": settings.RETRIEVAL_WEIGHTS,
                "fusion": f"weighted reciprocal rank fusion (k={settings.RETRIEVAL_RRF_K})",
                **_vector_backend(),
            },
            "integrations": describe_integration_modes(),
            "knowledge_base": knowledge_meta(),
        }
        return Response(payload, status=status.HTTP_200_OK)
