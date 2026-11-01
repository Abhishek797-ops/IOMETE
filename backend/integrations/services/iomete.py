"""
IOMETE connector adapter.

This is the file where it would be easiest to be dishonest, so the constraints are spelled
out up front.

**What this adapter can genuinely do in connected mode.** IOMETE ships an Iceberg REST
Catalog Service that "implements the Iceberg REST Catalog spec" (verified: IOMETE
architecture documentation, source S4). That specification is a published open standard with
defined endpoints — `GET /v1/config`, `GET /v1/namespaces`,
`GET /v1/namespaces/{namespace}/tables`, `GET /v1/namespaces/{namespace}/tables/{table}`.
Those are standard Iceberg REST endpoints, not endpoints COMPASS invented, and they are what
this adapter calls. It can therefore really list namespaces, list tables and read a table's
schema and current snapshot from a live IOMETE deployment.

**What this adapter deliberately cannot do.** Execute SQL. IOMETE's documented query
interfaces are HiveServer2 JDBC on port 10000, Spark Connect on 15002, and Arrow Flight on
33333 — all of which need a JDBC/gRPC driver rather than an HTTP call, and none of which has
a documented REST query endpoint. So `run_query` in connected mode does **not** silently
fall back to the demo dataset and label the result as live. It raises, and says exactly what
would be needed. A playground that returned synthetic numbers under a green "connected"
badge would be the single most damaging thing this product could do.

**No invented endpoints. No hard-coded credentials. No faked handshake.** Connected mode
requires a configured base URL and token *and* a successful `GET /v1/config` against it.
Everything else is demo mode, clearly labelled.
"""

from __future__ import annotations

import logging

from common.exceptions import IntegrationNotConfiguredError, IntegrationUnavailableError

from ..models import IntegrationConfiguration, IntegrationMode
from .base import AdapterDescription, ConnectionResult, http_session, request_json

logger = logging.getLogger("compass.integrations.iomete")

#: Iceberg REST Catalog specification paths. Published open standard — see
#: https://iceberg.apache.org/ (the spec) and IOMETE source S4 for the statement that
#: IOMETE implements it.
ICEBERG_REST_PREFIX = "/v1"

CONNECTED_QUERY_GUIDANCE = (
    "Connected mode can read catalog metadata over the Iceberg REST Catalog API, but it "
    "cannot execute SQL. IOMETE's documented query interfaces are HiveServer2 (JDBC, port "
    "10000), Spark Connect (port 15002) and Arrow Flight (port 33333) — all driver-based "
    "rather than REST. To run SQL against your deployment, use the IOMETE SQL editor, or "
    "connect a BI tool or notebook with the Arrow Flight SQL JDBC driver. COMPASS will not "
    "return synthetic results under a connected label."
)


class IometeAdapter:
    """
    Live IOMETE adapter, speaking the Iceberg REST Catalog specification.

    Configuration (`config`): `base_url` — the Iceberg REST Catalog endpoint of your
    deployment; `warehouse` — optional warehouse/prefix; `verify_tls`.
    Credentials: `api_token` — a bearer token your deployment accepts.
    """

    provider = "iomete"

    def __init__(self, configuration: IntegrationConfiguration):
        self.configuration = configuration
        config = configuration.config or {}
        credentials = configuration.credentials or {}
        self.base_url = str(config.get("base_url") or "").rstrip("/")
        self.warehouse = str(config.get("warehouse") or "")
        self.verify_tls = bool(config.get("verify_tls", True))
        self.api_token = str(credentials.get("api_token") or "")

    # --- state -----------------------------------------------------------------------

    @property
    def missing_configuration(self) -> list[str]:
        missing = []
        if not self.base_url:
            missing.append(
                "config.base_url — the Iceberg REST Catalog endpoint of your IOMETE "
                "deployment (ask your platform administrator; it is served through the "
                "IOMETE Gateway)"
            )
        if not self.api_token:
            missing.append("credentials.api_token — a bearer token your deployment accepts")
        return missing

    @property
    def is_configured(self) -> bool:
        return not self.missing_configuration

    def describe(self) -> AdapterDescription:
        mode = self.configuration.mode
        connected = mode == IntegrationMode.CONNECTED
        return AdapterDescription(
            provider=self.provider,
            mode=mode,
            is_simulated=not connected,
            summary=(
                "Connected to your IOMETE deployment's Iceberg REST Catalog. Namespaces, "
                "tables and schemas are read live. SQL execution is not available over "
                "REST — see limitations."
                if connected
                else (
                    "Credentials are configured but no successful connection has been "
                    "recorded. Run a connection test to enable connected mode."
                    if mode == IntegrationMode.CONFIGURED
                    else (
                        "Demo mode. The lakehouse playground runs against a synthetic "
                        "dataset with a real, sandboxed SQL engine. Nothing is read from "
                        "any IOMETE deployment."
                    )
                )
            ),
            capabilities=(
                [
                    "List namespaces in your catalog (Iceberg REST GET /v1/namespaces)",
                    "List tables in a namespace",
                    "Read a table's schema, partition spec and current snapshot",
                ]
                if connected
                else [
                    "Explore a deterministic synthetic retail dataset",
                    "Run real SELECT queries against it in a sandboxed engine",
                    "Inspect illustrative Iceberg table metadata and an illustrative Spark "
                    "execution plan",
                ]
            ),
            limitations=(
                [
                    CONNECTED_QUERY_GUIDANCE,
                    "Only operations defined by the Iceberg REST Catalog specification are "
                    "available. COMPASS does not call any undocumented IOMETE endpoint.",
                    "Access is subject to your Apache Ranger policies, enforced by the "
                    "catalog service — COMPASS sees exactly what the supplied token is "
                    "permitted to see.",
                ]
                if connected
                else [
                    "The dataset is synthetic and generated from a fixed seed; it does not "
                    "represent any real company's data.",
                    "Iceberg metadata and the Spark execution plan shown are illustrative, "
                    "not readings from a live deployment.",
                    "The SQL engine is SQLite in a read-only in-memory sandbox, so Spark- "
                    "and Iceberg-specific SQL extensions are not available.",
                ]
            ),
            missing_configuration=self.missing_configuration,
            last_tested_at=(
                self.configuration.last_connection_test_at.isoformat()
                if self.configuration.last_connection_test_at
                else None
            ),
            evidence=self.configuration.connection_detail or {},
        )

    def _session(self):
        session = http_session(verify_tls=self.verify_tls)
        session.headers["Authorization"] = f"Bearer {self.api_token}"
        return session

    def _require_configured(self) -> None:
        if not self.is_configured:
            raise IntegrationNotConfiguredError(
                detail=(
                    "The IOMETE connector is not configured, so the playground is in demo "
                    "mode. Missing: " + "; ".join(self.missing_configuration)
                )
            )

    def _require_connected(self) -> None:
        self._require_configured()
        if self.configuration.mode != IntegrationMode.CONNECTED:
            raise IntegrationNotConfiguredError(
                detail=(
                    "Credentials are present but no successful connection test has been "
                    "recorded, so connected mode is not enabled. Run a connection test "
                    "first — COMPASS will not read from a deployment it has not verified it "
                    "can reach."
                )
            )

    # --- connection ------------------------------------------------------------------

    def test_connection(self) -> ConnectionResult:
        """
        `GET /v1/config` — the Iceberg REST Catalog specification's own handshake endpoint.

        It is the correct choice because the spec defines it as the client's first call: it
        returns the catalog's defaults and overrides, so a successful response is positive
        evidence that we are talking to an Iceberg REST Catalog and are authorised.
        """
        if not self.is_configured:
            return ConnectionResult.failure(
                "Cannot test: " + "; ".join(self.missing_configuration),
                code="not_configured",
            )

        url = f"{self.base_url}{ICEBERG_REST_PREFIX}/config"
        params = {"warehouse": self.warehouse} if self.warehouse else None
        ok, payload, message = request_json(self._session(), "GET", url, params=params)
        if not ok:
            return ConnectionResult.failure(message)

        if not isinstance(payload, dict) or (
            "defaults" not in payload and "overrides" not in payload
        ):
            return ConnectionResult.failure(
                "The endpoint responded, but the payload does not look like an Iceberg REST "
                "Catalog config response. Check that base_url points at the catalog service "
                "rather than the IOMETE console.",
                code="unexpected_payload",
            )

        defaults = payload.get("defaults") or {}
        overrides = payload.get("overrides") or {}

        # Follow up with a namespace listing: config can succeed on an unauthorised token
        # on some implementations, and we want evidence of real read access.
        ok, namespaces_payload, namespaces_message = request_json(
            self._session(), "GET", f"{self.base_url}{ICEBERG_REST_PREFIX}/namespaces"
        )
        namespace_count = None
        if ok and isinstance(namespaces_payload, dict):
            namespace_count = len(namespaces_payload.get("namespaces") or [])

        evidence = {
            "catalog_endpoint": self.base_url,
            "spec": "Apache Iceberg REST Catalog",
            "warehouse": overrides.get("warehouse") or defaults.get("warehouse") or self.warehouse,
            "prefix": overrides.get("prefix") or defaults.get("prefix") or "",
            "namespaces_visible": namespace_count,
            "namespace_listing": "ok" if ok else namespaces_message,
        }
        return ConnectionResult(
            ok=True,
            message=(
                "Connected to the Iceberg REST Catalog"
                + (
                    f"; {namespace_count} namespace(s) visible to this token."
                    if namespace_count is not None
                    else "; namespace listing was not permitted for this token."
                )
            ),
            evidence=evidence,
        )

    # --- catalog reads ---------------------------------------------------------------

    def list_namespaces(self) -> list[str]:
        self._require_connected()
        ok, payload, message = request_json(
            self._session(), "GET", f"{self.base_url}{ICEBERG_REST_PREFIX}/namespaces"
        )
        if not ok:
            raise IntegrationUnavailableError(detail=f"Could not list namespaces: {message}")
        return [".".join(parts) for parts in (payload or {}).get("namespaces", [])]

    def list_tables(self, namespace: str) -> list[dict]:
        self._require_connected()
        encoded = namespace.replace(".", "%1F")  # spec: unit separator between levels
        ok, payload, message = request_json(
            self._session(),
            "GET",
            f"{self.base_url}{ICEBERG_REST_PREFIX}/namespaces/{encoded}/tables",
        )
        if not ok:
            raise IntegrationUnavailableError(
                detail=f"Could not list tables in {namespace}: {message}"
            )
        return [
            {"namespace": ".".join(entry.get("namespace", [])), "name": entry.get("name", "")}
            for entry in (payload or {}).get("identifiers", [])
        ]

    def describe_table(self, namespace: str, table: str) -> dict:
        self._require_connected()
        encoded = namespace.replace(".", "%1F")
        ok, payload, message = request_json(
            self._session(),
            "GET",
            f"{self.base_url}{ICEBERG_REST_PREFIX}/namespaces/{encoded}/tables/{table}",
        )
        if not ok:
            raise IntegrationUnavailableError(
                detail=f"Could not read {namespace}.{table}: {message}"
            )
        metadata = (payload or {}).get("metadata") or {}
        current_schema_id = metadata.get("current-schema-id")
        schema = next(
            (
                candidate
                for candidate in metadata.get("schemas", [])
                if candidate.get("schema-id") == current_schema_id
            ),
            (metadata.get("schemas") or [{}])[0] if metadata.get("schemas") else {},
        )
        return {
            "namespace": namespace,
            "name": table,
            "format_version": metadata.get("format-version"),
            "location": metadata.get("location", ""),
            "current_snapshot_id": metadata.get("current-snapshot-id"),
            "columns": [
                {
                    "name": field.get("name"),
                    "iceberg_type": str(field.get("type")),
                    "required": field.get("required", False),
                    "doc": field.get("doc", ""),
                }
                for field in (schema.get("fields") or [])
            ],
            "partition_specs": metadata.get("partition-specs", []),
            "snapshot_count": len(metadata.get("snapshots") or []),
            "properties": {
                key: value
                for key, value in (metadata.get("properties") or {}).items()
                # Never surface anything that could carry a credential from table properties.
                if not any(
                    token in key.lower()
                    for token in ("secret", "token", "key", "password", "credential")
                )
            },
            "simulated": False,
        }

    def run_query(self, sql: str) -> dict:
        """
        Deliberately unimplemented in connected mode.

        There is no documented IOMETE REST endpoint for SQL execution, and inventing one is
        explicitly forbidden. Falling back to the synthetic dataset while reporting
        `connected` would be worse still. So this raises, with guidance on the documented
        paths.
        """
        self._require_connected()
        raise IntegrationUnavailableError(detail=CONNECTED_QUERY_GUIDANCE)


class DemoLakehouseAdapter:
    """
    The demo-mode lakehouse adapter.

    Backed by the synthetic dataset and the sandboxed SQL engine. Fully functional and
    explicitly labelled: every payload it returns carries `mode: "demo"` and
    `is_simulated: True`.
    """

    provider = "iomete"

    def describe(self) -> AdapterDescription:
        return AdapterDescription(
            provider=self.provider,
            mode=IntegrationMode.DEMO,
            is_simulated=True,
            summary=(
                "Demo mode. A deterministic synthetic retail dataset with a real, sandboxed "
                "SQL engine. Queries genuinely execute; the data is simulated."
            ),
            capabilities=[
                "Explore five Iceberg-style tables with full schemas and DDL",
                "Run your own SELECT queries — real execution, real results",
                "See an illustrative Spark execution plan for your query",
                "Inspect illustrative Iceberg snapshot and manifest metadata",
            ],
            limitations=[
                "The dataset is synthetic and does not represent any real company's data.",
                "Iceberg metadata and the execution plan are illustrative teaching devices, "
                "not readings from a live deployment.",
                "SELECT only. The engine is a read-only in-memory sandbox.",
                "Spark- and Iceberg-specific SQL extensions are not available.",
            ],
            missing_configuration=[
                "Configure an IOMETE integration with config.base_url (your Iceberg REST "
                "Catalog endpoint) and credentials.api_token, then run a connection test, "
                "to read live catalog metadata."
            ],
        )

    def test_connection(self) -> ConnectionResult:
        """
        Reports `ok=False`: the demo adapter is working, but it is not connected to
        anything. Returning success here would promote a simulation to `connected`.
        """
        return ConnectionResult(
            ok=False,
            message=(
                "This is the demo lakehouse adapter; there is no IOMETE deployment to "
                "connect to. It is functioning normally."
            ),
            evidence={"simulated": True},
            error_code="simulated_provider",
        )

    def list_namespaces(self) -> list[str]:
        from lakehouse.services.dataset import DATASET_ID

        return [DATASET_ID]

    def list_tables(self, namespace: str) -> list[dict]:
        from lakehouse.services.dataset import DATASET_ID, tables

        return [{"namespace": DATASET_ID, "name": name} for name in tables()]

    def describe_table(self, namespace: str, table: str) -> dict:
        from lakehouse.services.dataset import tables

        found = tables().get(table)
        if found is None:
            raise IntegrationUnavailableError(detail=f"No table named {table!r} in the demo dataset.")
        payload = found.schema_payload()
        payload["simulated"] = True
        return payload

    def run_query(self, sql: str) -> dict:
        from lakehouse.services import sql_engine

        result = sql_engine.run(sql)
        return {
            "mode": "demo",
            "is_simulated": True,
            "columns": result.columns,
            "rows": result.rows,
            "row_count": result.row_count,
            "truncated": result.truncated,
            "duration_ms": result.duration_ms,
            "execution_plan": result.execution_plan,
            "scanned_tables": result.scanned_tables,
            "notice": result.notice,
            "simulation_notice": (
                "Executed against the synthetic demo dataset in a sandboxed read-only "
                "engine. The results are real computations over simulated data."
            ),
        }
