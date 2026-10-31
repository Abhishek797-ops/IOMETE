"""
Lakehouse playground API.

Public, so a prospect can explore before signing up for anything. Two explicitly
distinguishable modes:

* **demo** — the synthetic dataset and the sandboxed SQL engine. Queries genuinely execute;
  the data is simulated and every response says so.
* **connected** — reads live catalog metadata from a real IOMETE deployment through the
  Iceberg REST Catalog specification. Reachable only when an IOMETE integration has passed
  a connection test.

`mode` in every response is derived from the adapter, never from a request parameter. A
client cannot ask to be told it is connected.
"""

from __future__ import annotations

import logging

from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_control
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiExample, OpenApiParameter, extend_schema
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from common.exceptions import IntegrationNotConfiguredError
from integrations.models import IntegrationMode
from integrations.services import registry

from .models import LakehouseQueryRun, PlaygroundMode
from .services import dataset, sql_engine

logger = logging.getLogger("compass.lakehouse")


class _PublicView(APIView):
    permission_classes = [AllowAny]
    throttle_scope = "public"


def _resolve_mode(request) -> tuple[str, object]:
    """
    Determine the playground's mode from the adapter, not from the request.

    Returns `(mode, adapter)`. The adapter is live only when an IOMETE integration exists,
    is complete, and recorded a successful connection test — acceptance test 13.
    """
    organization = None
    user = getattr(request, "user", None)
    if user is not None and getattr(user, "is_authenticated", False):
        organization = user.primary_organization

    adapter = registry.lakehouse_adapter(organization=organization)
    description = adapter.describe()
    mode = (
        PlaygroundMode.CONNECTED
        if description.mode == IntegrationMode.CONNECTED
        else PlaygroundMode.DEMO
    )
    return mode, adapter


@method_decorator(cache_control(public=True, max_age=120), name="get")
@extend_schema(
    tags=["lakehouse"],
    summary="Playground mode and capabilities",
    description=(
        "What the playground can actually do right now. `mode` is `demo` unless an IOMETE "
        "integration has passed a live connection test — it is derived from the adapter, "
        "not from anything the client sends.\n\n"
        "In connected mode, catalog metadata is read through the Iceberg REST Catalog "
        "specification. SQL execution is **not** available in connected mode, because "
        "IOMETE's documented query interfaces (HiveServer2 JDBC, Spark Connect, Arrow "
        "Flight) are driver-based rather than REST. COMPASS reports that plainly rather "
        "than returning synthetic results under a connected label."
    ),
    responses={200: OpenApiTypes.OBJECT},
)
class PlaygroundStatusView(_PublicView):
    def get(self, request) -> Response:
        mode, adapter = _resolve_mode(request)
        description = adapter.describe()
        return Response(
            {
                "mode": mode,
                "mode_label": dict(PlaygroundMode.choices)[mode],
                "is_simulated": mode == PlaygroundMode.DEMO,
                "adapter": description.to_dict(),
                "sql_execution_available": mode == PlaygroundMode.DEMO,
                "sql_execution_note": (
                    "Queries execute for real against the synthetic dataset in a read-only "
                    "sandbox."
                    if mode == PlaygroundMode.DEMO
                    else (
                        "Connected mode reads catalog metadata only. Use the IOMETE SQL "
                        "editor, or a BI tool with the Arrow Flight SQL JDBC driver, to "
                        "query your deployment."
                    )
                ),
                "limits": {
                    "max_rows": sql_engine.MAX_ROWS,
                    "max_columns": sql_engine.MAX_COLUMNS,
                    "statement_timeout_seconds": sql_engine.STATEMENT_TIMEOUT_SECONDS,
                    "read_only": True,
                },
            }
        )


@method_decorator(cache_control(public=True, max_age=300), name="get")
@extend_schema(
    tags=["lakehouse"],
    summary="Dataset schemas and the conceptual pipeline",
    description=(
        "The five Iceberg-style tables with full column schemas, illustrative Iceberg DDL, "
        "illustrative snapshot metadata, and the seven-stage conceptual pipeline from "
        "ingestion through to consumption — each stage naming the IOMETE component "
        "responsible, with source citations.\n\n"
        "The dataset is synthetic and generated deterministically, so the sample queries "
        "return the same answers in every environment."
    ),
    responses={200: OpenApiTypes.OBJECT},
)
class DatasetView(_PublicView):
    def get(self, request) -> Response:
        mode, adapter = _resolve_mode(request)
        payload = dataset.describe()

        if mode == PlaygroundMode.CONNECTED:
            # In connected mode, also offer the live catalog so the prospect can see their
            # own namespaces alongside the demo dataset.
            try:
                namespaces = adapter.list_namespaces()
                payload["connected_catalog"] = {
                    "namespaces": namespaces,
                    "notice": (
                        "Read live from your deployment's Iceberg REST Catalog. The demo "
                        "dataset above remains available for exploration."
                    ),
                }
            except IntegrationNotConfiguredError as exc:
                payload["connected_catalog"] = {"error": str(exc.detail), "namespaces": []}
            except Exception as exc:
                logger.warning("Live catalog listing failed: %s", exc)
                payload["connected_catalog"] = {
                    "error": "The live catalog could not be read; see the integration status.",
                    "namespaces": [],
                }

        payload["mode"] = mode
        return Response(payload)


@method_decorator(cache_control(public=True, max_age=300), name="get")
@extend_schema(
    tags=["lakehouse"],
    summary="Curated sample queries",
    description=(
        "Seven sample queries from starter to advanced. Each carries a `teaches` field "
        "explaining the lakehouse concept it demonstrates — partition pruning, shuffles, "
        "joins across Iceberg tables, conditional aggregation — and a `chart` hint so the "
        "client can visualise the result without guessing."
    ),
    responses={200: OpenApiTypes.OBJECT},
)
class SampleQueriesView(_PublicView):
    def get(self, _request) -> Response:
        return Response(
            {
                "dataset_id": dataset.DATASET_ID,
                "queries": sql_engine.sample_queries(),
            }
        )


class QueryRequestSerializer(serializers.Serializer):
    sql = serializers.CharField(
        required=False, allow_blank=True,
        help_text="A single SELECT (or WITH) statement. The engine is strictly read-only.",
    )
    sample_id = serializers.CharField(
        required=False, allow_blank=True,
        help_text="Run a curated sample instead of supplying SQL.",
    )
    session_key = serializers.CharField(
        max_length=64, required=False, allow_blank=True,
        help_text="Opaque client-generated id, so an anonymous visitor's query history "
        "persists within their visit without needing an account.",
    )

    def validate(self, attrs):
        if not attrs.get("sql") and not attrs.get("sample_id"):
            raise serializers.ValidationError(
                "Supply either `sql` or a `sample_id` to run."
            )
        return attrs


@extend_schema(
    tags=["lakehouse"],
    summary="Run a query",
    description=(
        "Executes a SELECT against the synthetic dataset and returns real results, plus an "
        "**illustrative** Spark execution plan showing the stages a distributed engine "
        "would go through for that query shape.\n\n"
        "Safety: a fresh in-memory SQLite database is built per request; a SQLite "
        "authorizer callback denies every non-read operation below the SQL parser; only one "
        "`SELECT`/`WITH` statement is accepted; and row, column and timeout limits apply. "
        "The application database is not reachable from this engine.\n\n"
        "In connected mode this endpoint reports that SQL execution requires a driver-based "
        "interface rather than silently returning synthetic rows."
    ),
    request=QueryRequestSerializer,
    examples=[
        OpenApiExample(
            "Revenue by month",
            value={
                "sql": "SELECT order_month, ROUND(SUM(gross_amount),2) AS revenue "
                       "FROM retail_analytics.orders WHERE status != 'cancelled' "
                       "GROUP BY order_month ORDER BY order_month"
            },
            request_only=True,
        )
    ],
    responses={200: OpenApiTypes.OBJECT},
)
class RunQueryView(_PublicView):
    def post(self, request) -> Response:
        serializer = QueryRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        sample = None
        sql = data.get("sql", "")
        if sample_id := data.get("sample_id"):
            sample = sql_engine.get_sample(sample_id)
            if sample is None:
                return Response(
                    {
                        "error": {
                            "code": "not_found",
                            "message": f"No sample query with id {sample_id!r}.",
                            "details": {
                                "available": [q["id"] for q in sql_engine.sample_queries()]
                            },
                        }
                    },
                    status=status.HTTP_404_NOT_FOUND,
                )
            sql = sample["sql"]

        mode, _adapter = _resolve_mode(request)

        organization = None
        user = getattr(request, "user", None)
        if user is not None and getattr(user, "is_authenticated", False):
            organization = user.primary_organization

        if mode == PlaygroundMode.CONNECTED:
            # Honest refusal rather than a silent fallback that would be labelled connected.
            return Response(
                {
                    "error": {
                        "code": "integration_unavailable",
                        "message": (
                            "SQL execution is not available in connected mode. IOMETE's "
                            "documented query interfaces are HiveServer2 (JDBC, port "
                            "10000), Spark Connect (15002) and Arrow Flight (33333) — all "
                            "driver-based rather than REST. Use the IOMETE SQL editor or "
                            "connect a client with the Arrow Flight SQL JDBC driver. "
                            "COMPASS will not return synthetic results under a connected "
                            "label."
                        ),
                        "details": {
                            "mode": mode,
                            "catalog_metadata_available": True,
                            "run_against_demo_dataset": (
                                "Disable the IOMETE integration, or use the demo dataset "
                                "endpoints, to run exploratory SQL."
                            ),
                        },
                    }
                },
                status=status.HTTP_409_CONFLICT,
            )

        try:
            result = sql_engine.run(sql)
        except sql_engine.SqlRejected as exc:
            LakehouseQueryRun.objects.create(
                organization=organization,
                executed_by=user if user and user.is_authenticated else None,
                session_key=(data.get("session_key") or "")[:64],
                mode=mode,
                sql=sql[:8000],
                dataset=dataset.DATASET_ID,
                sample_query_id=(sample["id"] if sample else ""),
                succeeded=False,
                error_code=exc.code,
                error_message=str(exc)[:400],
            )
            return Response(
                {
                    "error": {
                        "code": exc.code,
                        "message": str(exc),
                        "details": {
                            "mode": mode,
                            "tables": [
                                f"{dataset.DATASET_ID}.{name}" for name in dataset.tables()
                            ],
                        },
                    }
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        LakehouseQueryRun.objects.create(
            organization=organization,
            executed_by=user if user and user.is_authenticated else None,
            session_key=(data.get("session_key") or "")[:64],
            mode=mode,
            sql=result.sql[:8000],
            dataset=dataset.DATASET_ID,
            sample_query_id=(sample["id"] if sample else ""),
            succeeded=True,
            row_count=result.row_count,
            column_count=len(result.columns),
            duration_ms=result.duration_ms,
            simulated_execution_plan=result.execution_plan,
        )

        return Response(
            {
                "mode": mode,
                "is_simulated": True,
                "sql": result.sql,
                "columns": result.columns,
                "rows": result.rows,
                "row_count": result.row_count,
                "truncated": result.truncated,
                "duration_ms": result.duration_ms,
                "scanned_tables": result.scanned_tables,
                "execution_plan": result.execution_plan,
                "execution_plan_notice": (
                    "This plan is illustrative. It shows the stages a distributed engine "
                    "would go through for a query of this shape — it is not an EXPLAIN from "
                    "Spark."
                ),
                "simulation_notice": (
                    "Executed for real against the synthetic demo dataset in a read-only "
                    "sandbox. The computation is genuine; the data is simulated."
                ),
                "notice": result.notice,
                "sample": sample,
            }
        )


@extend_schema(
    tags=["lakehouse"],
    summary="Live catalog table detail (connected mode)",
    description=(
        "Reads a table's schema, partition spec and current snapshot from a live IOMETE "
        "deployment via the Iceberg REST Catalog specification. Requires a verified IOMETE "
        "integration; returns 409 in demo mode rather than substituting synthetic data."
    ),
    parameters=[
        OpenApiParameter("namespace", str, OpenApiParameter.PATH),
        OpenApiParameter("table", str, OpenApiParameter.PATH),
    ],
    responses={200: OpenApiTypes.OBJECT},
)
class CatalogTableView(_PublicView):
    def get(self, request, namespace: str, table: str) -> Response:
        mode, adapter = _resolve_mode(request)
        if mode != PlaygroundMode.CONNECTED:
            return Response(
                {
                    "error": {
                        "code": "integration_not_configured",
                        "message": (
                            "The playground is in demo mode, so there is no live catalog to "
                            "read. Use the dataset endpoint for the synthetic tables, or "
                            "configure and verify an IOMETE integration."
                        ),
                        "details": {"mode": mode},
                    }
                },
                status=status.HTTP_409_CONFLICT,
            )
        return Response({"mode": mode, **adapter.describe_table(namespace, table)})
