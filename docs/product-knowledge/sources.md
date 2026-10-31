# Verification Log

Every source below was fetched directly on the date shown. Source ids (`S1`…`S10`) are
referenced from `knowledge.json`.

| id | Title | URL | Fetched | What was read from it |
| --- | --- | --- | --- | --- |
| S1 | IOMETE homepage | https://iomete.com/ | 2026-10-31 | Taglines ("The sovereign data platform.", "the data platform for the ai era"), one-liner, feature list (multiple lakehouses, Spark Connect, Jupyter, SQL editor, query history, Spark applications, real-time streaming, data catalog, database explorer, data security, domains, BI connectivity, FDEs), named technologies (Spark, Iceberg, Kafka, Pulsar, Kinesis, Jupyter, Spark Connect), deployment models incl. "Hybrid first", compliance statements (SOC 2 / HIPAA / GDPR) and trust-center link, 2-5x cost-saving claim. |
| S2 | Documentation hub | https://iomete.com/resources | 2026-10-31 | Documentation information architecture and the URLs for S3, S4, S5, S8, S9, S10; integration section names (dbt, Airflow, BI tools, DBeaver, Dataiku, Git). |
| S3 | What is IOMETE? | https://iomete.com/resources/getting-started/what-is-iomete | 2026-10-31 | "Data Lakehouse Platform for AI and Analytics"; capability list (Query Federation Engine, Data Catalog, Central Data Access Control, Event Streams, Spark Connect & Arrow Flight, Git Integration, Multi-Domain Support, Collaborative SQL Editor, External Tool Integration, Multi-Region Support (Enterprise Edition)); full technology and storage-backend lists; sovereignty statements "The platform operates entirely within your infrastructure" and "no data is sent outside of your organization". |
| S4 | Architecture | https://iomete.com/resources/getting-started/architecture | 2026-10-31 | **The most load-bearing source.** "built on Apache Spark, Apache Iceberg, and Kubernetes"; Helm chart deployment; three-tier model (infrastructure / platform services / workloads); every platform service and its responsibility (Gateway, Core, Cluster, Identity, SQL, Catalog, Iceberg REST Catalog, Health Check, Socket, Collaboration); Spark Operator components; compute-cluster ports (HiveServer2 10000, Spark Connect 15002, Arrow Flight 33333); Papyrus event-stream engine; three-level authorization (platform / data / resource RAS with VIEW, UPDATE, MANAGE); auth methods (local, LDAP, SAML, OIDC); storage URI schemes (`s3a://`, `gs://`, `wasbs://`, `abfs://`); shared PostgreSQL metadata model; Prefect orchestration; Typesense catalog search; NATS JetStream; networking via single Gateway. |
| S5 | Integrations overview | https://iomete.com/resources/integrations/overview | 2026-10-31 | Integration catalogue by category: Ataccama, Monte Carlo, OpenMetadata, Collate, ThoughtSpot, Wasabi, Stardog, dbt, Airflow, Metabase, Superset, Power BI, Tableau, Redash, DBeaver, Dataiku, Git. Also the **absence** of a documented streaming-ingestion connector category, which is why `streaming-sources` is `needs_confirmation`. |
| S6 | Platform overview | https://iomete.com/product/data-platform/platform-overview | 2026-10-31 | Platform modules (data lakehouses, SQL editor, Spark jobs, Spark Connect, data catalog, data access controls, ML notebooks); "combines the flexibility of data lakes with the performance of data warehouses"; 2-3x cost-saving claim (note: differs from the homepage's 2-5x). |
| S7 | Open source architecture | https://iomete.com/product/architecture/open-source | 2026-10-31 | Iceberg described as "the table format trusted by industry leaders to manage massive-scale data lakes" with ACID, time travel/rollback, schema and partition evolution, concurrent writes; Spark quote "Apache Spark delivers lightning-fast data processing through advanced optimization and in-memory computing." Notably does **not** mention Kubernetes, Ranger or Nessie. |
| S8 | Deployment architecture | https://iomete.com/resources/deployment/architecture-deployment | 2026-10-31 | Helm chart name `iomete-data-plane-enterprise`; `iomete-data-plane-init` pre-install hook; `data-plane` Kubernetes Secret; `/health` probes; `RollingUpdate` with `maxUnavailable: 0, maxSurge: 1`; node selectors/tolerations; stateful components (NATS 3 replicas, iom-event-stream 2 replicas, Typesense 20Gi PVC); `iom-sql` fixed at 1 replica; ingress expectations and 24h gRPC read timeout; object-storage config types (`s3_compatible`, `aws_s3`, `gcs`, `azure_gen1`, `azure_gen2`; `minio` and `dell_ecs` deprecated); key paths `data/`, `iomete-assets/spark-history/`, `iomete-assets/sql-results/`; shared PostgreSQL with `iomete_` prefix; PgBouncer `directHost` guidance; per-cloud scratch dirs (`/local1`, `/mnt`, `/mnt/stateful_partition`); AWS-only zone-aware scheduling. |
| S9 | Scalability | https://iomete.com/resources/getting-started/scalability | 2026-10-31 | Node autoscalers (Karpenter, GKE Node Auto-Provisioning, AKS Cluster Autoscaler); HPA defaults per service; Spark dynamic allocation behaviour (one executor → configured max → zero when idle); single-node mode; admin-defined node types; per-team namespace quotas; priority classes; three multi-cluster patterns; cost levers incl. "up to 3x cost reduction" for spot executors. |
| S10 | Platform tour | https://iomete.com/resources/getting-started/platform-tour | 2026-10-31 | Console information architecture: Home, Engine (Compute, Jupyter Containers, Event Streams), Workspace (SQL Editor, Query Monitoring), Applications (Spark Applications, Streaming Jobs, Job Templates), Governance (Data Catalog across five tabs), Resource Bundles, Settings, Admin Portal. |

## Pages checked and found unusable

| URL | Result |
| --- | --- |
| `https://iomete.com/resources/getting-started/` | HTTP 404. The documentation hub is at `https://iomete.com/resources` (S2). The URL given in the original brief does not resolve — recorded here so it is not retried as authoritative. |

## Deliberate gaps

These were looked for and **not** found on the pages above, so COMPASS does not assert them:

- Kubernetes version requirements, node sizing, CPU/memory minimums.
- PostgreSQL version and sizing requirements.
- Air-gapped / offline installation support (third-party reviews mention it; official pages reviewed do not).
- Concurrency limits, maximum executor counts, per-region limits.
- Any pricing information.
- The federated source types behind the Query Federation Engine.
- Which external Iceberg-compatible engines are formally tested against the Iceberg REST Catalog.

Each of these is represented in the product as an explicit "question for your IOMETE sales
engineer" rather than as a COMPASS answer.
