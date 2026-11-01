"""
Architecture recommendation.

Produces a layered graph the frontend renders with React Flow: the prospect's own systems
on the left, IOMETE's documented architecture in the middle, their consumers on the right.

The rule the brief insists on, enforced structurally: **conceptual placement must be
distinguishable from documented product behaviour.** Every node carries a `claim_status`:

| `claim_status`       | Meaning                                                          |
| -------------------- | ---------------------------------------------------------------- |
| `documented`         | A real IOMETE component, cited from the knowledge base.          |
| `customer_system`    | Something the prospect told us they run. No IOMETE claim at all.  |
| `documented_integration` | A connection IOMETE documents, with a source.                |
| `conceptual`         | A plausible placement COMPASS is proposing. Not a product claim. |
| `needs_confirmation` | Referenced officially but not documented well enough to rely on. |

The frontend renders each status differently (solid, dashed, flagged) and the legend is
served with the graph, so the distinction cannot be lost in translation.

It also deliberately does **not** imply IOMETE replaces everything. Source databases stay
where they are; BI tools keep working through the SQL endpoint. A diagram that erases a
customer's existing investment is both wrong and a bad sales artefact.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from knowledge.services import product_knowledge as pk

from ..models import DataVolume, InfrastructureLocation, UseCase

CONCEPTUAL_DISCLAIMER = (
    "This diagram combines IOMETE's documented architecture with a conceptual placement of "
    "the systems you told us about. Components marked “documented” are real IOMETE "
    "components, cited from IOMETE's own documentation. Components marked “conceptual” are "
    "COMPASS's proposal for how your estate could fit around them — they are not "
    "statements about IOMETE's capabilities. Connections marked “needs confirmation” are "
    "referenced in official material but not documented in enough detail to rely on. "
    "IOMETE does not replace your source systems or your BI tools: it sits alongside them."
)

LEGEND = [
    {
        "claim_status": "documented",
        "label": "Documented IOMETE component",
        "meaning": "A real component of the IOMETE platform, cited from official documentation.",
        "render": "solid",
    },
    {
        "claim_status": "documented_integration",
        "label": "Documented integration",
        "meaning": "A connection IOMETE documents, with a source reference.",
        "render": "solid",
    },
    {
        "claim_status": "customer_system",
        "label": "Your existing system",
        "meaning": "Something you told us you run. COMPASS makes no product claim about it.",
        "render": "neutral",
    },
    {
        "claim_status": "conceptual",
        "label": "Conceptual placement",
        "meaning": (
            "COMPASS's proposal for how this would fit. Plausible, but not a documented "
            "IOMETE capability."
        ),
        "render": "dashed",
    },
    {
        "claim_status": "needs_confirmation",
        "label": "Needs confirmation",
        "meaning": (
            "Referenced in official material but not documented well enough to rely on. "
            "Confirm with IOMETE."
        ),
        "render": "flagged",
    },
]

LAYERS = [
    {"id": "sources", "label": "Your data sources", "order": 1,
     "description": "Systems you already run. These stay where they are."},
    {"id": "ingestion", "label": "Ingestion", "order": 2,
     "description": "How data arrives in the lakehouse."},
    {"id": "storage", "label": "Storage you control", "order": 3,
     "description": "Object storage in your own account or data centre."},
    {"id": "table_format", "label": "Table format", "order": 4,
     "description": "Apache Iceberg turns files into transactional tables."},
    {"id": "platform", "label": "IOMETE platform services", "order": 5,
     "description": "Catalog, identity, SQL, orchestration — running in your Kubernetes cluster."},
    {"id": "compute", "label": "Compute", "order": 6,
     "description": "Spark clusters, jobs and notebooks, created on demand."},
    {"id": "access", "label": "Access and consumption", "order": 7,
     "description": "How people and tools reach the data."},
    {"id": "infrastructure", "label": "Infrastructure", "order": 8,
     "description": "The substrate everything runs on."},
]


@dataclass
class Node:
    id: str
    label: str
    layer: str
    kind: str
    claim_status: str
    description: str
    sources: list[str] = field(default_factory=list)
    detail: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "layer": self.layer,
            "kind": self.kind,
            "claim_status": self.claim_status,
            "description": self.description,
            "sources": pk.resolve_sources(self.sources),
            "detail": self.detail,
        }


@dataclass
class Edge:
    source: str
    target: str
    label: str
    kind: str
    claim_status: str = "documented"

    def to_dict(self) -> dict:
        return {
            "id": f"{self.source}->{self.target}",
            "source": self.source,
            "target": self.target,
            "label": self.label,
            "kind": self.kind,
            "claim_status": self.claim_status,
        }


@dataclass
class ArchitectureResult:
    title: str
    nodes: list[dict]
    edges: list[dict]
    layers: list[dict]
    legend: list[dict]
    narrative: str
    integration_notes: list[dict]
    open_questions: list[str]
    conceptual_disclaimer: str
    cited_sources: list[str]


# =======================================================================================
# Source-system mapping
# =======================================================================================

#: How a stated source system reaches the lakehouse. Keyed on lowercase substrings so
#: "PostgreSQL 15" and "postgres" both match.
#:
#: `claim_status` here is the honest part. dbt and Airflow are documented integrations.
#: A raw PostgreSQL database is reachable — but via a Spark job the customer writes, which
#: is a conceptual placement, not a product connector. Conflating the two is how a
#: diagram becomes a promise nobody made.
_SOURCE_PATTERNS: tuple[tuple[tuple[str, ...], dict], ...] = (
    (("postgres", "postgresql"), {
        "label": "PostgreSQL",
        "mechanism": "Spark JDBC read in a scheduled Spark job",
        "claim_status": "conceptual",
        "note": (
            "IOMETE documents a tutorial for syncing data from JDBC sources. The job is "
            "yours to define; there is no managed PostgreSQL connector documented."
        ),
        "sources": ["S2"],
    }),
    (("mysql", "mariadb"), {
        "label": "MySQL",
        "mechanism": "Spark JDBC read in a scheduled Spark job",
        "claim_status": "conceptual",
        "note": "Same pattern as PostgreSQL: a Spark job you define, not a managed connector.",
        "sources": ["S2"],
    }),
    (("oracle", "sql server", "mssql", "db2"), {
        "label": "Enterprise RDBMS",
        "mechanism": "Spark JDBC read in a scheduled Spark job",
        "claim_status": "conceptual",
        "note": "Driver availability and licensing need confirming for commercial databases.",
        "sources": [],
    }),
    (("kafka",), {
        "label": "Apache Kafka",
        "mechanism": "Spark Structured Streaming job, or Event Streams over HTTP",
        "claim_status": "needs_confirmation",
        "note": (
            "Kafka is named on IOMETE's homepage, but the integrations documentation does "
            "not describe a dedicated Kafka connector. Confirm whether this is a managed "
            "connector or a Spark job you maintain."
        ),
        "sources": ["S1", "S5"],
    }),
    (("kinesis",), {
        "label": "Amazon Kinesis",
        "mechanism": "Spark Structured Streaming job",
        "claim_status": "needs_confirmation",
        "note": "Named on IOMETE's homepage; no documented connector. Confirm the pattern.",
        "sources": ["S1", "S5"],
    }),
    (("pulsar",), {
        "label": "Apache Pulsar",
        "mechanism": "Spark Structured Streaming job",
        "claim_status": "needs_confirmation",
        "note": "Named on IOMETE's homepage; no documented connector. Confirm the pattern.",
        "sources": ["S1", "S5"],
    }),
    (("s3", "minio", "ozone", "ecs", "wasabi", "object storage", "gcs", "adls", "blob"), {
        "label": "Existing object storage",
        "mechanism": "Read in place — IOMETE points at your bucket",
        "claim_status": "documented",
        "note": (
            "Supported storage types are `s3_compatible`, `aws_s3`, `gcs`, `azure_gen1` and "
            "`azure_gen2`, covering AWS S3, Apache Ozone, MinIO, Dell ECS, GCS and Azure "
            "Gen1/Gen2."
        ),
        "sources": ["S3", "S4", "S8"],
    }),
    (("hdfs", "hadoop"), {
        "label": "Hadoop HDFS",
        "mechanism": "Confirm with IOMETE",
        "claim_status": "needs_confirmation",
        "note": (
            "HDFS is listed among storage technologies on the What is IOMETE page, but the "
            "deployment documentation enumerates object-storage configuration types only."
        ),
        "sources": ["S3", "S8"],
    }),
    (("csv", "json", "xml", "parquet", "avro", "orc", "files", "file"), {
        "label": "Files in object storage",
        "mechanism": "Read directly, or loaded into Iceberg tables",
        "claim_status": "documented",
        "note": (
            "Parquet, Avro, ORC, JSON, XML and CSV are all listed among the formats IOMETE "
            "works with."
        ),
        "sources": ["S3"],
    }),
    (("api", "rest", "webhook", "http"), {
        "label": "Application APIs",
        "mechanism": "Event Streams — HTTP POST into Iceberg tables",
        "claim_status": "documented",
        "note": (
            "Event Streams ingest events over HTTP and write them to Iceberg tables in near "
            "real time, via the Rust-based Papyrus engine. Optional and admin-enabled."
        ),
        "sources": ["S3", "S4", "S10"],
    }),
    (("snowflake", "bigquery", "redshift", "synapse", "databricks"), {
        "label": "Existing cloud warehouse",
        "mechanism": "Migrate, or query federation (scope to be confirmed)",
        "claim_status": "needs_confirmation",
        "note": (
            "IOMETE documents a Query Federation Engine but does not enumerate which source "
            "types it supports. For a migration, data is typically unloaded to object "
            "storage and registered as Iceberg tables."
        ),
        "sources": ["S3"],
    }),
    (("dbt",), {
        "label": "dbt",
        "mechanism": "Documented dbt integration",
        "claim_status": "documented_integration",
        "note": "dbt is a documented IOMETE integration for transformation.",
        "sources": ["S2", "S5"],
    }),
    (("airflow",), {
        "label": "Apache Airflow",
        "mechanism": "Documented Airflow integration",
        "claim_status": "documented_integration",
        "note": "Airflow is a documented IOMETE integration for orchestration.",
        "sources": ["S3", "S5"],
    }),
)

#: Consumer tools, keyed the same way.
_CONSUMER_PATTERNS: tuple[tuple[tuple[str, ...], dict], ...] = (
    (("power bi", "powerbi"), {"label": "Power BI", "claim_status": "documented_integration",
                               "sources": ["S3", "S5"]}),
    (("tableau",), {"label": "Tableau", "claim_status": "documented_integration",
                    "sources": ["S3", "S5"]}),
    (("looker",), {"label": "Looker", "claim_status": "conceptual",
                   "sources": [],
                   "note": "Not a documented IOMETE integration. Connection would be via the "
                           "HiveServer2 JDBC endpoint; confirm driver compatibility."}),
    (("metabase",), {"label": "Metabase", "claim_status": "documented_integration",
                     "sources": ["S5"]}),
    (("superset",), {"label": "Apache Superset", "claim_status": "documented_integration",
                     "sources": ["S5"]}),
    (("redash",), {"label": "Redash", "claim_status": "documented_integration",
                   "sources": ["S5"]}),
    (("thoughtspot",), {"label": "ThoughtSpot", "claim_status": "documented_integration",
                        "sources": ["S5"]}),
    (("dbeaver",), {"label": "DBeaver", "claim_status": "documented_integration",
                    "sources": ["S5"]}),
    (("dataiku",), {"label": "Dataiku", "claim_status": "documented_integration",
                    "sources": ["S5"]}),
    (("excel",), {"label": "Excel", "claim_status": "conceptual", "sources": [],
                  "note": "Via an ODBC driver against the SQL endpoint; not documented by IOMETE."}),
)


def _match(value: str, patterns) -> dict | None:
    lowered = value.lower()
    for keys, spec in patterns:
        if any(key in lowered for key in keys):
            return spec
    return None


# =======================================================================================
# Graph construction
# =======================================================================================


def _storage_node(answers: dict) -> Node:
    """Pick the storage backend that matches the prospect's cloud, from verified options."""
    clouds = [str(c).lower() for c in (answers.get("cloud_providers") or [])]
    location = answers.get("infrastructure_location", InfrastructureLocation.UNDECIDED)

    if "aws" in clouds:
        label, scheme, detail = "AWS S3", "s3a://", "Your own S3 buckets, in your account."
    elif "azure" in clouds:
        label, scheme, detail = (
            "Azure Data Lake Storage Gen2", "abfs://",
            "Your own storage account. Requires storageAccountName and storageAccountKey.",
        )
    elif "gcp" in clouds or "google" in " ".join(clouds):
        label, scheme, detail = "Google Cloud Storage", "gs://", "Your own GCS buckets."
    elif location in {InfrastructureLocation.ON_PREMISES, InfrastructureLocation.AIR_GAPPED}:
        label, scheme, detail = (
            "S3-compatible object storage", "s3a://",
            "Apache Ozone, MinIO, Dell ECS or any S3-compatible target in your data centre. "
            "Requires endpoint, accessKey and secretKey.",
        )
    else:
        label, scheme, detail = (
            "Object storage you control", "s3a:// / gs:// / abfs://",
            "Chosen once your hosting model is settled.",
        )

    return Node(
        id="storage",
        label=label,
        layer="storage",
        kind="storage",
        claim_status="documented",
        description=(
            f"{detail} All table data, Spark event logs and SQL results live here, under "
            "`data/`, `iomete-assets/spark-history/` and `iomete-assets/sql-results/`. "
            "Compute and storage are decoupled, so this is the one copy of your data."
        ),
        sources=["S3", "S4", "S8"],
        detail={"uri_scheme": scheme},
    )


def _platform_nodes() -> list[Node]:
    """
    IOMETE's documented platform services, read from the knowledge base.

    Driven by `knowledge.json` rather than hardcoded so the diagram cannot drift from the
    verified facts — if a service entry is corrected there, the playground follows.
    """
    # `pk.load()` returns the raw knowledge base, where `sources` are id strings; the
    # `pk.architecture()` helper returns them already resolved to full records. Read the
    # raw form and resolve here, so this function has one well-defined input shape.
    architecture = pk.load()["architecture"]
    wanted = {
        "iom-gateway": ("access", "gateway"),
        "identity-service": ("platform", "security"),
        "catalog-service": ("platform", "catalog"),
        "iceberg-rest-catalog": ("table_format", "catalog"),
        "sql-service": ("platform", "sql"),
        "cluster-service": ("platform", "control"),
        "core-service": ("platform", "control"),
        "prefect": ("platform", "orchestration"),
        "compute-clusters": ("compute", "compute"),
        "spark-jobs": ("compute", "compute"),
        "jupyter-containers": ("compute", "notebook"),
        "event-streams": ("ingestion", "ingestion"),
        "kubernetes": ("infrastructure", "infrastructure"),
        "postgresql": ("infrastructure", "metadata"),
    }

    nodes: list[Node] = []
    for service in architecture.get("services", []):
        mapping = wanted.get(service["id"])
        if not mapping:
            continue
        layer, kind = mapping
        nodes.append(
            Node(
                id=service["id"],
                label=service["name"],
                layer=layer,
                kind=kind,
                claim_status="documented",
                description=service.get("what_it_does", ""),
                sources=[
                    source["id"] if isinstance(source, dict) else source
                    for source in service.get("sources", [])
                ],
                detail={
                    "why_needed": service.get("why_needed", ""),
                    "customer_gain": service.get("customer_gain", ""),
                    "note": service.get("note", ""),
                },
            )
        )

    nodes.append(
        Node(
            id="iceberg-tables",
            label="Apache Iceberg tables",
            layer="table_format",
            kind="table_format",
            claim_status="documented",
            description=(
                "Iceberg turns the files in your object storage into real tables: ACID "
                "transactions, time travel and rollback, schema and partition evolution, "
                "and safe concurrent writes."
            ),
            sources=["S4", "S7"],
            detail={
                "why_needed": (
                    "Without a table format, a lake is a pile of files that two readers can "
                    "see inconsistently."
                ),
                "customer_gain": (
                    "Warehouse-grade reliability over lake-grade storage, in an open format "
                    "other engines can read."
                ),
            },
        )
    )
    return nodes


def generate(answers: dict, *, assessment=None) -> ArchitectureResult:
    """
    Build the recommended architecture graph for one prospect.

    Pure function. `answers` is the Fit Finder payload; `assessment` is optional and only
    used to colour the narrative.
    """
    nodes: list[Node] = []
    edges: list[Edge] = []
    integration_notes: list[dict] = []
    open_questions: list[str] = []

    systems = [str(s) for s in (answers.get("current_systems") or []) if str(s).strip()]
    consumers = [str(c) for c in (answers.get("bi_tools") or []) if str(c).strip()]
    use_case = answers.get("primary_use_case", UseCase.OTHER)
    volume = answers.get("data_volume", DataVolume.UNKNOWN)

    # --- 1. Source systems -----------------------------------------------------------
    seen_sources: set[str] = set()
    for index, system in enumerate(systems[:8]):
        spec = _match(system, _SOURCE_PATTERNS)
        if spec is None:
            node_id = f"source-other-{index}"
            nodes.append(
                Node(
                    id=node_id,
                    label=system[:60],
                    layer="sources",
                    kind="source",
                    claim_status="customer_system",
                    description=(
                        "You told us you run this. COMPASS has no documented IOMETE "
                        "integration for it, so how it would connect needs confirming — "
                        "most sources are reachable through a Spark job or the SQL endpoint."
                    ),
                )
            )
            edges.append(
                Edge(node_id, "iceberg-tables", "connection to be confirmed", "ingest",
                     "needs_confirmation")
            )
            open_questions.append(
                f"How would {system[:60]} connect to IOMETE — a Spark job, Event Streams, "
                "or query federation?"
            )
            continue

        node_id = f"source-{spec['label'].lower().replace(' ', '-')}"
        if node_id in seen_sources:
            continue
        seen_sources.add(node_id)

        nodes.append(
            Node(
                id=node_id,
                label=spec["label"],
                layer="sources",
                kind="source",
                claim_status="customer_system",
                description=f"You told us you run this. {spec.get('note', '')}".strip(),
                sources=spec.get("sources", []),
            )
        )
        target = "event-streams" if "Event Streams" in spec["mechanism"] else "iceberg-tables"
        if target == "event-streams" and not any(n.id == "event-streams" for n in nodes):
            target = "iceberg-tables"
        edges.append(
            Edge(node_id, target, spec["mechanism"], "ingest", spec["claim_status"])
        )
        integration_notes.append(
            {
                "system": spec["label"],
                "mechanism": spec["mechanism"],
                "claim_status": spec["claim_status"],
                "note": spec.get("note", ""),
                "sources": pk.resolve_sources(spec.get("sources", [])),
            }
        )
        if spec["claim_status"] == "needs_confirmation":
            open_questions.append(
                f"{spec['label']}: {spec.get('note', 'confirm the connection pattern with IOMETE.')}"
            )

    # --- 2. IOMETE platform ----------------------------------------------------------
    platform_nodes = _platform_nodes()
    nodes.extend(platform_nodes)
    nodes.append(_storage_node(answers))

    # Core documented data path.
    edges.extend(
        [
            Edge("storage", "iceberg-tables", "files organised as tables", "storage"),
            Edge("iceberg-tables", "iceberg-rest-catalog",
                 "table metadata, Ranger policies enforced", "catalog"),
            Edge("iceberg-rest-catalog", "compute-clusters", "governed table access", "query"),
            Edge("compute-clusters", "iom-gateway", "HiveServer2 :10000, Spark Connect :15002",
                 "serve"),
            Edge("identity-service", "iceberg-rest-catalog", "Ranger access policies", "control"),
            Edge("catalog-service", "iceberg-tables", "discovery, lineage, tags", "control"),
            Edge("sql-service", "compute-clusters", "query execution", "control"),
            Edge("cluster-service", "compute-clusters", "provisions on demand", "control"),
            Edge("cluster-service", "jupyter-containers", "provisions notebooks", "control"),
            Edge("prefect", "spark-jobs", "schedules and tracks runs", "control"),
            Edge("spark-jobs", "iceberg-tables", "batch and streaming writes", "write"),
            Edge("kubernetes", "compute-clusters", "schedules every pod", "infrastructure"),
            Edge("postgresql", "catalog-service", "platform metadata", "infrastructure"),
            Edge("jupyter-containers", "iom-gateway", "notebook access via WebSocket", "serve"),
        ]
    )
    if any(node.id == "event-streams" for node in platform_nodes):
        edges.append(
            Edge("event-streams", "iceberg-tables", "HTTP POST, near real time", "ingest")
        )

    # --- 3. Consumers ----------------------------------------------------------------
    if not consumers:
        # No tools named: show the documented access paths rather than inventing tools.
        nodes.extend(
            [
                Node(
                    id="consumer-bi",
                    label="Your BI tools",
                    layer="access",
                    kind="consumer",
                    claim_status="documented_integration",
                    description=(
                        "Connect over the SQL endpoint — HiveServer2 JDBC/ODBC on port "
                        "10000, or Arrow Flight on 33333 when enabled. Power BI, Tableau, "
                        "Metabase, Apache Superset and Redash are documented integrations."
                    ),
                    sources=["S3", "S4", "S5"],
                ),
                Node(
                    id="consumer-sql",
                    label="SQL editor (in-product)",
                    layer="access",
                    kind="consumer",
                    claim_status="documented",
                    description=(
                        "Browser-based SQL workspace with auto-completion, worksheets, "
                        "query history, visual explain plans and Git integration."
                    ),
                    sources=["S1", "S3", "S4", "S10"],
                ),
            ]
        )
        edges.extend(
            [
                Edge("iom-gateway", "consumer-bi", "JDBC / ODBC / Arrow Flight", "serve"),
                Edge("iom-gateway", "consumer-sql", "HTTPS", "serve"),
            ]
        )
    else:
        for index, consumer in enumerate(consumers[:6]):
            spec = _match(consumer, _CONSUMER_PATTERNS)
            if spec is None:
                node_id = f"consumer-other-{index}"
                nodes.append(
                    Node(
                        id=node_id,
                        label=consumer[:60],
                        layer="access",
                        kind="consumer",
                        claim_status="customer_system",
                        description=(
                            "Not a documented IOMETE integration. It would most likely "
                            "connect through the HiveServer2 JDBC endpoint — confirm driver "
                            "compatibility."
                        ),
                    )
                )
                edges.append(
                    Edge("iom-gateway", node_id, "JDBC (to be confirmed)", "serve",
                         "needs_confirmation")
                )
                open_questions.append(
                    f"Is {consumer[:60]} able to connect over the HiveServer2 JDBC endpoint "
                    "or Arrow Flight?"
                )
                continue

            node_id = f"consumer-{spec['label'].lower().replace(' ', '-')}"
            nodes.append(
                Node(
                    id=node_id,
                    label=spec["label"],
                    layer="access",
                    kind="consumer",
                    claim_status=spec["claim_status"],
                    description=spec.get(
                        "note",
                        "A documented IOMETE integration, connecting over the SQL endpoint.",
                    ),
                    sources=spec.get("sources", []),
                )
            )
            edges.append(
                Edge("iom-gateway", node_id, "JDBC / ODBC / Arrow Flight", "serve",
                     spec["claim_status"])
            )

    # --- 4. Use-case specific additions ---------------------------------------------
    if use_case in {UseCase.AI_ML, UseCase.DATA_SCIENCE}:
        nodes.append(
            Node(
                id="consumer-ml",
                label="ML workloads",
                layer="access",
                kind="consumer",
                claim_status="documented",
                description=(
                    "Jupyter containers run inside the platform with Python, R and Scala, "
                    "so models train next to governed data rather than on extracted copies."
                ),
                sources=["S1", "S4", "S6"],
            )
        )
        edges.append(Edge("jupyter-containers", "consumer-ml", "notebooks and Spark", "serve"))

    if use_case == UseCase.DATA_MESH:
        nodes.append(
            Node(
                id="domains",
                label="Domains",
                layer="platform",
                kind="governance",
                claim_status="documented",
                description=(
                    "Separate teams, projects or environments into domains with their own "
                    "resources, members and roles — the mechanism behind a data-mesh "
                    "operating model."
                ),
                sources=["S1", "S3"],
            )
        )
        edges.append(Edge("domains", "catalog-service", "organises data by subject area", "control"))

    # --- 5. Narrative ----------------------------------------------------------------
    narrative = _narrative(answers, assessment, volume)

    if answers.get("infrastructure_location") == InfrastructureLocation.UNDECIDED:
        open_questions.append(
            "Where would the Kubernetes cluster run? That decision determines the storage "
            "backend and most of the sizing."
        )
    if volume == DataVolume.UNKNOWN:
        open_questions.append(
            "What is your current total data volume and expected growth? It drives cluster "
            "sizing and the cost comparison."
        )
    open_questions.append(
        "Who will operate the Kubernetes cluster, the object storage and the PostgreSQL "
        "metadata server?"
    )

    cited: set[str] = set()
    for node in nodes:
        cited.update(node.sources)

    return ArchitectureResult(
        title=f"Proposed IOMETE architecture for {answers.get('company_name') or 'your estate'}",
        nodes=[node.to_dict() for node in nodes],
        edges=[edge.to_dict() for edge in edges],
        layers=LAYERS,
        legend=LEGEND,
        narrative=narrative,
        integration_notes=integration_notes,
        open_questions=list(dict.fromkeys(open_questions))[:8],
        conceptual_disclaimer=CONCEPTUAL_DISCLAIMER,
        cited_sources=sorted(cited),
    )


def _narrative(answers: dict, assessment, volume: str) -> str:
    location = dict(InfrastructureLocation.choices).get(
        answers.get("infrastructure_location", ""), "your chosen environment"
    )
    parts = [
        f"IOMETE would be deployed as a Helm chart into a Kubernetes cluster in "
        f"{location.lower()}. Your source systems stay exactly where they are — nothing "
        "here replaces them.",
        "Data lands in object storage you own. Apache Iceberg organises those files into "
        "transactional tables, and the Iceberg REST Catalog is the governed doorway to "
        "them: every engine that reads a table goes through it, and Apache Ranger policies "
        "are enforced there rather than in each client tool.",
        "Spark compute clusters are created on demand and scale their executors from one up "
        "to a configured maximum, back to zero when idle. Your BI tools connect through the "
        "same single Gateway over the SQL endpoint, so dashboards keep working.",
    ]
    if volume in {DataVolume.TB_10_100, DataVolume.TB_100_1PB, DataVolume.OVER_1PB}:
        parts.append(
            "At your volume, the structural benefit is that there is one copy of the data. "
            "Analytics, engineering and ML workloads all read the same governed tables "
            "instead of each requiring their own extract."
        )
    if volume == DataVolume.UNDER_1TB:
        parts.append(
            "At under a terabyte, be clear-eyed: this architecture is designed for scale you "
            "do not currently have. It is the right choice if residency rules require "
            "self-hosting or you expect rapid growth — otherwise a managed warehouse is "
            "simpler."
        )
    if assessment is not None and getattr(assessment, "band", None) in {"conditional", "limited"}:
        parts.append(
            "Note that your fit assessment flagged conditions that should be settled before "
            "treating this diagram as a plan rather than an illustration."
        )
    return "\n\n".join(parts)


def reference_architecture() -> dict:
    """
    The generic conceptual architecture for `/architecture` — no prospect input required.

    Uses an illustrative source set so the playground is explorable immediately. Every
    IOMETE component is `documented` and cited; the illustrative sources are labelled
    `customer_system`, so a visitor is never shown a fabricated integration.
    """
    result = generate(
        {
            "company_name": None,
            "current_systems": ["PostgreSQL", "MySQL", "APIs", "CSV files", "S3"],
            "bi_tools": ["Power BI", "Tableau", "Metabase"],
            "cloud_providers": [],
            "infrastructure_location": InfrastructureLocation.HYBRID,
            "data_volume": DataVolume.TB_10_100,
            "primary_use_case": UseCase.CONSOLIDATION,
        }
    )
    return {
        "title": "How IOMETE fits into an enterprise data estate",
        "nodes": result.nodes,
        "edges": result.edges,
        "layers": result.layers,
        "legend": result.legend,
        "narrative": result.narrative,
        "integration_notes": result.integration_notes,
        "open_questions": result.open_questions,
        "conceptual_disclaimer": (
            "The source systems and BI tools shown here are illustrative examples, not a "
            "claim about any particular customer. " + CONCEPTUAL_DISCLAIMER
        ),
        "cited_sources": result.cited_sources,
        "is_illustrative": True,
    }
