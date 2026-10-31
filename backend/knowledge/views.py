"""
Product knowledge endpoints.

Public and unauthenticated: this is the material the explainer, architecture playground and
fit finder render for prospects who have not signed up for anything.
"""

from __future__ import annotations

from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_control
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .services import product_knowledge as pk


class _PublicKnowledgeView(APIView):
    permission_classes = [AllowAny]
    throttle_scope = "public"


@method_decorator(cache_control(public=True, max_age=300), name="get")
@extend_schema(
    tags=["knowledge"],
    summary="Full IOMETE product knowledge base",
    description=(
        "Everything COMPASS is permitted to say about IOMETE, with every claim carrying "
        "its `status` and resolved source citations.\n\n"
        "`status_legend` describes how each status must be rendered, and `do_not_claim` "
        "lists the assertions COMPASS will not make (pricing, named customers, "
        "benchmarks, SLAs, quantified savings for a specific prospect). Clients are "
        "expected to honour both."
    ),
    responses={200: OpenApiTypes.OBJECT},
)
class ProductKnowledgeView(_PublicKnowledgeView):
    def get(self, _request) -> Response:
        return Response(pk.full_knowledge())


@extend_schema(
    tags=["knowledge"],
    summary="Explainer questions and answers",
    description="The eleven plain-language questions behind the /explore experience.",
    responses={200: OpenApiTypes.OBJECT},
)
class ExplainerView(_PublicKnowledgeView):
    def get(self, _request) -> Response:
        data = pk.full_knowledge()
        return Response(
            {
                "positioning": data["positioning"],
                "concepts": data["concepts"],
                "questions": data["explainer_questions"],
                "technologies": data["technologies"],
                "personas": pk.personas(),
                "status_legend": data["status_legend"],
            }
        )


class PersonaView(_PublicKnowledgeView):
    @extend_schema(
        tags=["knowledge"],
        summary="Role-tailored explanation",
        operation_id="knowledge_persona_retrieve",
        description=(
            "A persona-specific explanation of IOMETE: what this role cares about, the key "
            "points with citations, and the questions they should put to an IOMETE sales "
            "engineer. Points flagged `caveat` are deliberate honest trade-offs and must be "
            "rendered, not filtered out."
        ),
        parameters=[
            OpenApiParameter(
                "persona_id", str, OpenApiParameter.PATH,
                description="cto | data-engineer | data-analyst | security-compliance | business",
            )
        ],
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(self, _request, persona_id: str) -> Response:
        persona = pk.get_persona(persona_id)
        if persona is None:
            return Response(
                {
                    "error": {
                        "code": "not_found",
                        "message": f"No persona with id {persona_id!r}.",
                        "details": {"available": [p["id"] for p in pk.personas()]},
                    }
                },
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(persona)


class PersonaListView(_PublicKnowledgeView):
    @extend_schema(
        tags=["knowledge"],
        summary="List personas",
        operation_id="knowledge_personas_list",
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(self, _request) -> Response:
        return Response(pk.personas())


@method_decorator(cache_control(public=True, max_age=300), name="get")
@extend_schema(
    tags=["knowledge"],
    summary="IOMETE architecture reference",
    description=(
        "The three-tier architecture and every documented platform service, each with "
        "what it does, why it is needed and what the customer gains. Drives the "
        "architecture playground.\n\n"
        "This describes IOMETE's own documented architecture. The playground additionally "
        "composes a *conceptual* customer architecture around it, which is labelled as "
        "conceptual rather than as a confirmed integration."
    ),
    responses={200: OpenApiTypes.OBJECT},
)
class ArchitectureView(_PublicKnowledgeView):
    def get(self, _request) -> Response:
        return Response(
            {
                "architecture": pk.architecture(),
                "technologies": pk.full_knowledge()["technologies"],
                "storage_backends": pk.storage_backends(),
                "integrations": pk.integrations(),
                "deployment_models": pk.deployment_models(),
                "status_legend": pk.status_legend(),
            }
        )


@extend_schema(
    tags=["knowledge"],
    summary="Capabilities",
    parameters=[
        OpenApiParameter("status", str, OpenApiParameter.QUERY,
                         description="verified | vendor_claim | needs_confirmation"),
        OpenApiParameter("category", str, OpenApiParameter.QUERY),
    ],
    responses={200: OpenApiTypes.OBJECT},
)
class CapabilityListView(_PublicKnowledgeView):
    def get(self, request) -> Response:
        return Response(
            {
                "categories": pk.capability_categories(),
                "capabilities": pk.capabilities(
                    status=request.query_params.get("status"),
                    category=request.query_params.get("category"),
                ),
                "status_legend": pk.status_legend(),
            }
        )


@extend_schema(
    tags=["knowledge"],
    summary="Search the product knowledge base",
    description=(
        "Transparent lexical search over capabilities, technologies, concepts, "
        "architecture components, documented integrations and explainer answers.\n\n"
        "Lexical rather than semantic by design: this is a small curated corpus where "
        "exact-term matching is both more accurate and explainable. Semantic retrieval is "
        "used where it earns its place — historical ticket search."
    ),
    parameters=[
        OpenApiParameter("q", str, OpenApiParameter.QUERY, required=True),
        OpenApiParameter("limit", int, OpenApiParameter.QUERY),
    ],
    responses={200: OpenApiTypes.OBJECT},
)
class KnowledgeSearchView(_PublicKnowledgeView):
    def get(self, request) -> Response:
        query = request.query_params.get("q", "")
        try:
            limit = min(int(request.query_params.get("limit", 20)), 50)
        except (TypeError, ValueError):
            limit = 20
        results = pk.search(query, limit=limit)
        return Response({"query": query, "count": len(results), "results": results})


@extend_schema(
    tags=["knowledge"],
    summary="Claims COMPASS will not make",
    description=(
        "The guardrail list. Published so the restriction is inspectable rather than "
        "buried in a prompt, and consumed by the AI grounding layer."
    ),
    responses={200: OpenApiTypes.OBJECT},
)
class DoNotClaimView(_PublicKnowledgeView):
    def get(self, _request) -> Response:
        return Response(
            {
                "do_not_claim": pk.do_not_claim(),
                "note": (
                    "COMPASS is an independent enablement tool. Product facts are "
                    "transcribed from official IOMETE documentation and carry source "
                    "citations. Anything that could not be verified is labelled rather "
                    "than asserted."
                ),
            }
        )
