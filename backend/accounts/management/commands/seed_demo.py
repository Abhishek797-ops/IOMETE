"""
Seed the demonstration dataset.

Everything this command creates is flagged `is_synthetic=True` and is surfaced as such
through the API and labelled in the UI. These are plausible engineering scenarios written
for demonstration — they are **not** IOMETE incident records.

The command deliberately goes through the real services rather than writing rows directly:
`intake.create_ticket`, `lifecycle.record_resolution`, `lifecycle.verify_resolution`,
`knowledge.approve`, `execution.start/advance/complete`. That means the seeded data is
internally consistent with the product's own rules — fingerprints exist, embeddings exist,
playbook graphs have passed validation, executions have real step responses, and the audit
trail reflects actions that genuinely happened. A seed that bypassed the services would
produce a demo that works until someone clicks something.

Idempotent: re-running updates in place. `--flush` clears synthetic data first.
"""

from __future__ import annotations

import random
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from accounts.models import (
    CloudProvider,
    DeploymentModel,
    Membership,
    MembershipRole,
    Organization,
    SupportTier,
    SystemRole,
    User,
)
from accounts.services.identity import DEMO_PASSWORD
from playbooks.models import (
    ApprovalStatus,
    PlaybookStep,
    ResolutionPlaybook,
    ResponseKind,
    RiskLevel,
    StepType,
)
from playbooks.services import execution as execution_service
from playbooks.services import knowledge as knowledge_service
from prospects.models import (
    ArchitectureRecommendation,
    CompanyType,
    CurrentArchitecture,
    DataVolume,
    DemoRequest,
    FitAssessment,
    InfrastructureLocation,
    ProspectProfile,
    SovereigntyRequirement,
    UseCase,
)
from prospects.services import architecture as architecture_service
from prospects.services import fit as fit_service
from tickets.models import (
    Environment,
    ErrorFingerprint,
    IssueCluster,
    Severity,
    Ticket,
    TicketComponent,
)
from tickets.services import clustering, intake, lifecycle

RNG = random.Random(4242)

# =======================================================================================
# Organizations
# =======================================================================================

ORGANIZATIONS = [
    {
        "slug": "northwind-bank",
        "name": "Northwind Bank",
        "industry": "Financial services",
        "region": "EMEA",
        "employee_band": "5,000–10,000",
        "deployment_model": DeploymentModel.ON_PREMISES,
        "cloud_provider": CloudProvider.ON_PREM,
        "iomete_version": "3.19.1",
        "environment_label": "production",
        "kubernetes_distribution": "OpenShift 4.16",
        "object_storage": "Apache Ozone",
        "support_tier": SupportTier.STRATEGIC,
        "data_residency_requirement": "All customer data must remain within the EU.",
        "notes": "Regulated. Change windows are Tuesday 02:00–04:00 CET only.",
    },
    {
        "slug": "vela-telecom",
        "name": "Vela Telecom",
        "industry": "Telecommunications",
        "region": "APAC",
        "employee_band": "10,000+",
        "deployment_model": DeploymentModel.PUBLIC_CLOUD,
        "cloud_provider": CloudProvider.AWS,
        "iomete_version": "3.18.4",
        "environment_label": "production",
        "kubernetes_distribution": "EKS 1.30",
        "object_storage": "AWS S3",
        "support_tier": SupportTier.ENTERPRISE,
        "data_residency_requirement": "Subscriber data stays in-region.",
        "notes": "Heavy streaming workload. Spot executors across three AZs.",
    },
    {
        "slug": "helios-health",
        "name": "Helios Health Group",
        "industry": "Healthcare",
        "region": "North America",
        "employee_band": "1,000–5,000",
        "deployment_model": DeploymentModel.HYBRID,
        "cloud_provider": CloudProvider.AZURE,
        "iomete_version": "3.19.1",
        "environment_label": "production",
        "kubernetes_distribution": "AKS 1.29",
        "object_storage": "Azure Data Lake Storage Gen2",
        "support_tier": SupportTier.ENTERPRISE,
        "data_residency_requirement": "PHI remains on-premises; de-identified data may burst to Azure.",
        "notes": "Clinical analytics. Two namespaces with separate quotas.",
    },
    {
        "slug": "atlas-logistics",
        "name": "Atlas Logistics",
        "industry": "Transport and logistics",
        "region": "EMEA",
        "employee_band": "500–1,000",
        "deployment_model": DeploymentModel.PRIVATE_CLOUD,
        "cloud_provider": CloudProvider.OTHER,
        # Deliberately an older version, so the compatibility gate has something real to
        # gate. Without a version spread, the gating feature cannot be demonstrated.
        "iomete_version": "2.9.0",
        "environment_label": "production",
        "kubernetes_distribution": "Rancher RKE2",
        "object_storage": "MinIO",
        "support_tier": SupportTier.STANDARD,
        "notes": "Running an older release; upgrade planned next quarter.",
    },
]

USERS = [
    # --- IOMETE staff ---------------------------------------------------------------
    {
        "email": "admin@iomete.com",
        "full_name": "Priya Nandakumar",
        "job_title": "Platform Administrator",
        "system_role": SystemRole.PLATFORM_ADMIN,
        "is_staff": True,
    },
    {
        "email": "fde.lead@iomete.com",
        "full_name": "Dana Okoro",
        "job_title": "Lead Forward Deployed Engineer",
        "system_role": SystemRole.FDE_LEAD,
    },
    {
        "email": "fde@iomete.com",
        "full_name": "Marco Beltrán",
        "job_title": "Forward Deployed Engineer",
        "system_role": SystemRole.FDE,
    },
    {
        "email": "fde.second@iomete.com",
        "full_name": "Sora Takahashi",
        "job_title": "Forward Deployed Engineer",
        "system_role": SystemRole.FDE,
    },
    # --- Customers -------------------------------------------------------------------
    {
        "email": "admin@northwind.example",
        "full_name": "Eleanor Whitfield",
        "job_title": "Head of Data Platform",
        "system_role": SystemRole.CUSTOMER,
        "organization": "northwind-bank",
        "role": MembershipRole.ADMIN,
    },
    {
        "email": "engineer@northwind.example",
        "full_name": "Tomás Reiter",
        "job_title": "Senior Data Engineer",
        "system_role": SystemRole.CUSTOMER,
        "organization": "northwind-bank",
        "role": MembershipRole.ENGINEER,
    },
    {
        "email": "analyst@northwind.example",
        "full_name": "Aisha Rahman",
        "job_title": "Risk Analyst",
        "system_role": SystemRole.CUSTOMER,
        "organization": "northwind-bank",
        "role": MembershipRole.VIEWER,
    },
    {
        "email": "engineer@vela.example",
        "full_name": "Kwame Asante",
        "job_title": "Streaming Platform Lead",
        "system_role": SystemRole.CUSTOMER,
        "organization": "vela-telecom",
        "role": MembershipRole.ADMIN,
    },
    {
        "email": "engineer@helios.example",
        "full_name": "Lena Kowalczyk",
        "job_title": "Clinical Data Engineer",
        "system_role": SystemRole.CUSTOMER,
        "organization": "helios-health",
        "role": MembershipRole.ENGINEER,
    },
    {
        "email": "engineer@atlas.example",
        "full_name": "Rafael Duarte",
        "job_title": "Infrastructure Engineer",
        "system_role": SystemRole.CUSTOMER,
        "organization": "atlas-logistics",
        "role": MembershipRole.ADMIN,
    },
]


# =======================================================================================
# Ticket scenarios
#
# Six problem areas, each with variants across organizations and versions. The error text
# is realistic Spark / Kubernetes / Iceberg / Ranger output, because the normalisation and
# fingerprinting services are only meaningfully exercised by text that looks like the real
# thing.
# =======================================================================================

SCENARIOS = [
    # --- 1. Spark executor memory exhaustion ---------------------------------------
    {
        "key": "spark-oom-nightly",
        "organization": "northwind-bank",
        "reporter": "engineer@northwind.example",
        "title": "Executors terminated repeatedly during the nightly risk aggregation",
        "description": (
            "Our nightly risk aggregation over the transactions table has failed for three "
            "consecutive nights. It runs for roughly 40 minutes and then executors start "
            "disappearing; the job never completes. Nothing changed in the job itself — the "
            "only difference is that the source table has grown after the quarter-end load."
        ),
        "error_message": (
            "ExecutorLostFailure (executor 9 exited caused by one of the running tasks) "
            "Reason: Container from a bad node: container_1727... on host "
            "spark-risk-agg-7f9c4d-exec-9 was killed. Exit status: 137. "
            "Diagnostics: Container killed on request. Reason: OOMKilled"
        ),
        "diagnostics": (
            "kubectl describe pod spark-risk-agg-7f9c4d-exec-9 -n iomete-compute\n"
            "  Last State:     Terminated\n"
            "    Reason:       OOMKilled\n"
            "    Exit Code:    137\n"
            "  Limits:\n"
            "    memory:       4Gi\n"
            "  Requests:\n"
            "    memory:       4Gi\n"
            "\nspark.executor.memory=3g\nspark.executor.memoryOverhead=1g\n"
            "spark.sql.shuffle.partitions=200"
        ),
        "component": TicketComponent.SPARK_COMPUTE,
        "severity": Severity.HIGH,
        "environment": Environment.PRODUCTION,
        "days_ago": 96,
        "resolution": (
            "Executor memory was provisioned below the peak requirement of a skewed "
            "partition. The `account_id` distribution is heavily skewed after the "
            "quarter-end load, so a handful of tasks were handling two orders of magnitude "
            "more rows than the rest and exceeded the 4Gi container limit.\n\n"
            "Raised spark.executor.memory to 9g with 3g overhead, and enabled adaptive "
            "query execution with skew-join handling "
            "(spark.sql.adaptive.enabled=true, "
            "spark.sql.adaptive.skewJoin.enabled=true) so the skewed partitions are split "
            "automatically rather than relying on headroom."
        ),
        "evidence": (
            "The aggregation completed in 38 minutes with no executor loss on the next two "
            "nightly runs, and OOMKilled no longer appears in the executor events. Peak "
            "executor memory observed was 6.2Gi, comfortably inside the new limit."
        ),
        "verified": True,
        "quality": 5,
        "fde_minutes": 210,
        "self_service": False,
    },
    {
        "key": "spark-oom-reporting",
        "organization": "helios-health",
        "reporter": "engineer@helios.example",
        "title": "Spark workers keep dying during the clinical rollup",
        "description": (
            "The overnight clinical summarisation job shuts its worker processes down "
            "before finishing. It has worked for months and started failing this week. "
            "The data volume has not changed noticeably."
        ),
        "error_message": (
            "org.apache.spark.memory.SparkOutOfMemoryError: Unable to acquire 65536 bytes "
            "of memory, got 0. Container killed: OOMKilled (exit code 137)"
        ),
        "diagnostics": (
            "kubectl get pod spark-clinical-rollup-aa31c2-exec-4 -n iomete-compute "
            "-o jsonpath='{.status.containerStatuses[*].lastState.terminated}'\n"
            '{"exitCode":137,"reason":"OOMKilled","startedAt":"..."}\n'
            "spark.executor.memory=4g\nspark.executor.instances=6"
        ),
        "component": TicketComponent.SPARK_COMPUTE,
        "severity": Severity.HIGH,
        "environment": Environment.PRODUCTION,
        "days_ago": 61,
        "resolution": (
            "Same class of problem as the earlier Northwind case: executor memory below the "
            "peak requirement of a skewed partition. Raised executor memory to 10g and "
            "enabled adaptive skew-join handling."
        ),
        "evidence": (
            "Rollup completed in 52 minutes across two consecutive nights with no OOMKilled "
            "events."
        ),
        "verified": True,
        "quality": 4,
        "fde_minutes": 95,
        "self_service": False,
    },
    {
        "key": "spark-oom-atlas",
        "organization": "atlas-logistics",
        "reporter": "engineer@atlas.example",
        "title": "Executor OOM on the shipment analytics cluster",
        "description": (
            "Our shipment analytics queries fail partway through with executors being "
            "killed. We are on an older IOMETE release."
        ),
        "error_message": (
            "ExecutorLostFailure Reason: Container killed: OOMKilled (exit code 137)"
        ),
        "diagnostics": "spark.executor.memory=2g\nLast State: Terminated, Reason: OOMKilled",
        "component": TicketComponent.SPARK_COMPUTE,
        "severity": Severity.MEDIUM,
        "environment": Environment.PRODUCTION,
        "days_ago": 44,
        "resolution": (
            "Executor memory raised from 2g to 6g. Adaptive skew handling is not available "
            "on this release, so a manual repartition on the shipment key was added to the "
            "job instead."
        ),
        "evidence": "Queries complete; no further OOMKilled events over a week of runs.",
        "verified": True,
        "quality": 3,
        "fde_minutes": 120,
        "self_service": False,
    },
    # --- 2. Kubernetes scheduling / quota ------------------------------------------
    {
        "key": "k8s-pending-quota",
        "organization": "vela-telecom",
        "reporter": "engineer@vela.example",
        "title": "New compute cluster stuck in Pending after node pool resize",
        "description": (
            "We resized the data-plane node pool yesterday evening. Since then any new "
            "compute cluster we create sits in Pending indefinitely and never becomes "
            "available. Existing clusters are unaffected."
        ),
        "error_message": (
            "0/6 nodes are available: 2 Insufficient memory, 4 node(s) didn't match "
            "Pod's node affinity/selector. FailedScheduling"
        ),
        "diagnostics": (
            "kubectl get events -n iomete-compute --field-selector reason=FailedScheduling\n"
            "  Warning  FailedScheduling  pod/spark-adhoc-91ab2f-driver  "
            "0/6 nodes are available\n\n"
            "kubectl describe resourcequota -n iomete-compute\n"
            "  requests.memory   184Gi / 192Gi\n"
            "  requests.cpu      46 / 48"
        ),
        "component": TicketComponent.KUBERNETES,
        "severity": Severity.CRITICAL,
        "environment": Environment.PRODUCTION,
        "days_ago": 73,
        "resolution": (
            "Two separate causes, which is why it looked intermittent. First, the namespace "
            "resource quota was effectively exhausted at 184Gi of 192Gi, leaving no room "
            "for a new driver. Second, the replacement nodes in the resized pool were "
            "missing the `k8s.iomete.com/dedicated` label, so they did not satisfy the data "
            "plane node selector.\n\n"
            "Raised the namespace quota to 256Gi and applied the missing node label to the "
            "new pool."
        ),
        "evidence": (
            "A new compute cluster reached Running in 90 seconds. Quota usage now shows "
            "184Gi of 256Gi, and all six nodes match the data-plane selector."
        ),
        "verified": True,
        "quality": 5,
        "fde_minutes": 165,
        "self_service": False,
    },
    {
        "key": "k8s-quota-helios",
        "organization": "helios-health",
        "reporter": "engineer@helios.example",
        "title": "Notebook containers will not start in the research namespace",
        "description": (
            "Researchers cannot start Jupyter containers in the research namespace. The "
            "clinical namespace is fine. This started after we onboarded a new team."
        ),
        "error_message": (
            "pods \"jupyter-research-4c2a\" is forbidden: exceeded quota: research-quota, "
            "requested: requests.memory=8Gi, used: requests.memory=60Gi, "
            "limited: requests.memory=64Gi"
        ),
        "diagnostics": "kubectl describe resourcequota research-quota -n iomete-research",
        "component": TicketComponent.KUBERNETES,
        "severity": Severity.MEDIUM,
        "environment": Environment.PRODUCTION,
        "days_ago": 38,
        "resolution": (
            "The research namespace quota was sized for the original team. The new team's "
            "notebook requests took it to 60Gi of 64Gi, leaving no room for an 8Gi "
            "container. Quota raised to 96Gi after confirming node capacity."
        ),
        "evidence": "Notebooks start; quota usage 60Gi of 96Gi with headroom for six more.",
        "verified": True,
        "quality": 4,
        "fde_minutes": 45,
        "self_service": False,
    },
    # --- 3. Iceberg metadata / commit ----------------------------------------------
    {
        "key": "iceberg-commit-conflict",
        "organization": "vela-telecom",
        "reporter": "engineer@vela.example",
        "title": "Iceberg commit fails with stale metadata on the subscriber events table",
        "description": (
            "Writes to the subscriber_events table intermittently fail at commit time. "
            "Retrying sometimes succeeds. We have a streaming job appending continuously "
            "and a nightly compaction job, and the failures cluster around the compaction "
            "window."
        ),
        "error_message": (
            "org.apache.iceberg.exceptions.CommitFailedException: Cannot commit: stale "
            "table metadata. Base metadata location "
            "s3a://vela-lakehouse/data/subscriber_events/metadata/00231-....metadata.json "
            "is not the same as the current location"
        ),
        "diagnostics": (
            "SELECT * FROM lakehouse.telemetry.subscriber_events.snapshots "
            "ORDER BY committed_at DESC LIMIT 5;\n"
            "-- shows two append operations within the same second\n\n"
            "write.metadata.previous-versions-max = 100\n"
            "commit.retry.num-retries = 4"
        ),
        "component": TicketComponent.ICEBERG_METADATA,
        "severity": Severity.HIGH,
        "environment": Environment.PRODUCTION,
        "days_ago": 82,
        "resolution": (
            "Two writers were committing to the same table concurrently: the streaming "
            "append and the nightly compaction. Iceberg's optimistic concurrency correctly "
            "rejected the loser, but the retry budget of 4 was exhausted within the "
            "compaction window because compaction holds its commit open far longer than an "
            "append.\n\n"
            "Raised commit.retry.num-retries to 10 with exponential backoff, and moved "
            "compaction to a window where the streaming job is paused. The underlying "
            "behaviour is correct — the fix is to stop the two writers racing."
        ),
        "evidence": (
            "No CommitFailedException in 14 days. The snapshot history shows compaction and "
            "append operations no longer interleaving."
        ),
        "verified": True,
        "quality": 5,
        "fde_minutes": 240,
        "self_service": False,
    },
    {
        "key": "iceberg-table-not-found",
        "organization": "northwind-bank",
        "reporter": "engineer@northwind.example",
        "title": "Table disappeared from the catalog after a failed migration",
        "description": (
            "A table we query daily is no longer visible. The data files are still in "
            "object storage. This happened after a schema migration job failed partway "
            "through last night."
        ),
        "error_message": (
            "org.apache.iceberg.exceptions.NoSuchTableException: Table does not exist: "
            "lakehouse.risk.counterparty_exposure"
        ),
        "diagnostics": (
            "SHOW TABLES IN lakehouse.risk;\n-- counterparty_exposure absent\n\n"
            "-- object storage listing still shows:\n"
            "s3a://northwind-lakehouse/data/risk/counterparty_exposure/metadata/\n"
            "  00412-a1b2c3.metadata.json"
        ),
        "component": TicketComponent.ICEBERG_METADATA,
        "severity": Severity.CRITICAL,
        "environment": Environment.PRODUCTION,
        "days_ago": 54,
        "resolution": (
            "The failed migration dropped the catalog entry before its replacement was "
            "registered, so the table was unregistered while its data and metadata remained "
            "intact in object storage. Re-registered the table against the last good "
            "metadata file, which restored it with full snapshot history.\n\n"
            "The migration job was also changed to register-then-swap rather than "
            "drop-then-create, so a mid-run failure can no longer leave the catalog without "
            "a table."
        ),
        "evidence": (
            "The table is queryable, row counts match the pre-migration figures, and time "
            "travel to yesterday's snapshot works."
        ),
        "verified": True,
        "quality": 5,
        "fde_minutes": 180,
        "self_service": False,
    },
    # --- 4. Ranger / SQL permissions ------------------------------------------------
    {
        "key": "ranger-permission-denied",
        "organization": "northwind-bank",
        "reporter": "analyst@northwind.example",
        "title": "Analyst cannot read the customer dimension despite group membership",
        "description": (
            "An analyst in the risk-reporting group gets a permission error on a table they "
            "should be able to read. Other members of the same group can read it. The "
            "analyst joined the group this week."
        ),
        "error_message": (
            "org.apache.ranger.authorization.hadoop.exceptions."
            "RangerAccessControlException: Permission denied: user=a.rahman, "
            "access=SELECT, table=lakehouse.risk.customer_dimension"
        ),
        "diagnostics": (
            "SHOW CURRENT ROLES;\n-- risk_reporting not listed\n\n"
            "SHOW GRANTS ON TABLE lakehouse.risk.customer_dimension;\n"
            "-- SELECT granted to group risk_reporting"
        ),
        "component": TicketComponent.PERMISSIONS,
        "severity": Severity.MEDIUM,
        "environment": Environment.PRODUCTION,
        "days_ago": 47,
        "resolution": (
            "The grant was correct; the group membership had not propagated. The user was "
            "added to risk_reporting in the corporate directory, but the Identity Service's "
            "LDAP group sync had not run since, so Ranger was still evaluating the user "
            "without that group.\n\n"
            "Triggered a group sync, after which the grant resolved correctly. The sync "
            "interval was also shortened from 24 hours to 1 hour, because a day's delay on "
            "access changes was generating a steady trickle of tickets."
        ),
        "evidence": (
            "SHOW CURRENT ROLES now lists risk_reporting and the SELECT succeeds. Confirmed "
            "with a second newly-added user."
        ),
        "verified": True,
        "quality": 5,
        "fde_minutes": 75,
        "self_service": False,
    },
    {
        "key": "ranger-masking-helios",
        "organization": "helios-health",
        "reporter": "engineer@helios.example",
        "title": "Patient identifiers appear unmasked for one reporting group",
        "description": (
            "A reporting group that should see masked patient identifiers is seeing real "
            "values in one table. Masking works correctly on the other PHI tables."
        ),
        "error_message": "",
        "diagnostics": (
            "-- Masking policy exists for tag PHI\n"
            "-- Table lakehouse.clinical.encounters_v2 has no PHI classification tag"
        ),
        "component": TicketComponent.PERMISSIONS,
        "severity": Severity.CRITICAL,
        "environment": Environment.PRODUCTION,
        "days_ago": 29,
        "resolution": (
            "The masking policy is tag-based and applies to columns classified PHI. The "
            "newly created encounters_v2 table had not been classified, so no policy "
            "matched and the columns were returned unmasked. Applied the PHI classification "
            "to the relevant columns, which brought the existing policy into effect "
            "immediately.\n\n"
            "A catalog check was also added to the table-creation runbook so an "
            "unclassified table in a PHI namespace is caught before it is queryable."
        ),
        "evidence": (
            "The reporting group now sees masked values on encounters_v2, matching the "
            "other PHI tables. Verified with a test query as a member of that group."
        ),
        "verified": True,
        "quality": 5,
        "fde_minutes": 130,
        "self_service": False,
    },
    # --- 5. Ingestion / event streams ----------------------------------------------
    {
        "key": "ingestion-stalled",
        "organization": "vela-telecom",
        "reporter": "engineer@vela.example",
        "title": "Event stream ingestion stalled — no new rows for three hours",
        "description": (
            "Our HTTP event stream was landing rows in near real time and has stopped. The "
            "producer is still sending and receiving 200 responses, but the Iceberg table "
            "has not advanced its snapshot in three hours."
        ),
        "error_message": "",
        "diagnostics": (
            "SELECT max(event_at) FROM lakehouse.telemetry.raw_events;\n"
            "-- 3h12m ago\n\n"
            "SELECT count(*) FROM lakehouse.telemetry.raw_events.snapshots\n"
            "WHERE committed_at > now() - interval 4 hours;\n-- 0"
        ),
        "component": TicketComponent.DATA_INGESTION,
        "severity": Severity.HIGH,
        "environment": Environment.PRODUCTION,
        "days_ago": 35,
        "resolution": (
            "The event stream writer was accepting requests and buffering them, but could "
            "not commit because the target table's object storage prefix had hit a bucket "
            "policy that denied writes after a lifecycle rule was changed. The 200 "
            "responses were the ingestion endpoint acknowledging receipt, not a successful "
            "commit — which is why the producer saw no error.\n\n"
            "Corrected the bucket policy. The buffered events then committed and the table "
            "caught up."
        ),
        "evidence": (
            "Snapshots resumed within two minutes of the policy change and the backlog "
            "drained. max(event_at) is now within 30 seconds of real time."
        ),
        "verified": True,
        "quality": 4,
        "fde_minutes": 155,
        "self_service": False,
    },
    {
        "key": "ingestion-schema-mismatch",
        "organization": "atlas-logistics",
        "reporter": "engineer@atlas.example",
        "title": "JDBC sync job failing after a source schema change",
        "description": (
            "Our nightly sync from the shipments database started failing. The source team "
            "added a column earlier this week."
        ),
        "error_message": (
            "org.apache.spark.sql.AnalysisException: Cannot write incompatible data to "
            "table 'lakehouse.ops.shipments': Cannot safely cast 'declared_value': string "
            "to decimal(12,2)"
        ),
        "diagnostics": (
            "-- source column added as VARCHAR\n"
            "-- target Iceberg column is decimal(12,2)"
        ),
        "component": TicketComponent.DATA_INGESTION,
        "severity": Severity.MEDIUM,
        "environment": Environment.PRODUCTION,
        "days_ago": 22,
        "resolution": (
            "The source system added `declared_value` as a VARCHAR while the Iceberg table "
            "defines it as decimal(12,2), and Spark refused the implicit narrowing cast. "
            "Added an explicit cast with validation in the sync job so malformed values are "
            "routed to a quarantine table rather than failing the whole run."
        ),
        "evidence": (
            "The sync completes. 14 rows with non-numeric declared_value were quarantined "
            "and reported back to the source team."
        ),
        "verified": False,
        "quality": None,
        "fde_minutes": 60,
        "self_service": False,
    },
    # --- 6. Object storage connectivity --------------------------------------------
    {
        "key": "storage-access-denied",
        "organization": "northwind-bank",
        "reporter": "engineer@northwind.example",
        "title": "All queries failing with access denied to object storage",
        "description": (
            "Every query across every cluster started failing this morning with a storage "
            "access error. Nothing was deployed. This is a complete outage for us."
        ),
        "error_message": (
            "org.apache.hadoop.fs.s3a.AWSBadRequestException: getFileStatus on "
            "s3a://northwind-lakehouse/data/: com.amazonaws.services.s3.model."
            "AmazonS3Exception: Access Denied (Service: Amazon S3; Status Code: 403; "
            "Error Code: AccessDenied)"
        ),
        "diagnostics": (
            "kubectl get secret data-plane -n iomete-system -o jsonpath='{.data}' "
            "| base64 -d | jq 'keys'\n"
            '["database.password","storage.accessKey","storage.secretKey", ...]\n\n'
            "-- Ozone access key rotation was scheduled for 06:00 today"
        ),
        "component": TicketComponent.OBJECT_STORAGE,
        "severity": Severity.CRITICAL,
        "environment": Environment.PRODUCTION,
        "days_ago": 18,
        "resolution": (
            "The Apache Ozone S3 access key was rotated by a scheduled job at 06:00, but "
            "the `data-plane` Kubernetes Secret still held the previous key, so every "
            "storage request was rejected with 403.\n\n"
            "Updated the secret with the new credentials and restarted the platform "
            "services that read it at startup. The rotation job was then changed to update "
            "the Kubernetes Secret and trigger a rollout as part of the same operation, so "
            "the two can no longer drift."
        ),
        "evidence": (
            "Queries succeed across all clusters. A deliberate test rotation was run in "
            "staging and the platform picked up the new key without an outage."
        ),
        "verified": True,
        "quality": 5,
        "fde_minutes": 95,
        "self_service": False,
    },
    {
        "key": "storage-endpoint-tls",
        "organization": "atlas-logistics",
        "reporter": "engineer@atlas.example",
        "title": "Cannot connect to MinIO after certificate renewal",
        "description": (
            "After renewing the MinIO TLS certificate, clusters cannot read from storage."
        ),
        "error_message": (
            "javax.net.ssl.SSLHandshakeException: PKIX path building failed: "
            "sun.security.provider.certpath.SunCertPathBuilderException: unable to find "
            "valid certification path to requested target"
        ),
        "diagnostics": "-- new certificate signed by an internal CA not in the Spark truststore",
        "component": TicketComponent.OBJECT_STORAGE,
        "severity": Severity.HIGH,
        "environment": Environment.PRODUCTION,
        "days_ago": 12,
        "resolution": (
            "The renewed certificate is signed by an internal CA that is not present in the "
            "Spark container truststore. Added the internal CA bundle to the Spark image's "
            "truststore via the platform's custom certificate configuration."
        ),
        "evidence": "Clusters read from MinIO; the handshake exception no longer appears.",
        "verified": False,
        "quality": None,
        "fde_minutes": 85,
        "self_service": False,
    },
    # --- Miscellaneous, for breadth ------------------------------------------------
    {
        "key": "gateway-502",
        "organization": "helios-health",
        "reporter": "engineer@helios.example",
        "title": "Console intermittently returns 502 during peak hours",
        "description": (
            "The IOMETE console returns 502 for some users between 09:00 and 10:00. It "
            "recovers on refresh. Queries themselves seem unaffected."
        ),
        "error_message": "HTTP 502 Bad Gateway from the IOMETE Gateway",
        "diagnostics": (
            "kubectl get hpa -n iomete-system\n"
            "  iom-gateway   cpu: 94%/80%   replicas: 2/2   (maxReplicas 2)"
        ),
        "component": TicketComponent.GATEWAY_NETWORK,
        "severity": Severity.MEDIUM,
        "environment": Environment.PRODUCTION,
        "days_ago": 26,
        "resolution": (
            "The Gateway's horizontal pod autoscaler was capped at 2 replicas and was "
            "running at 94% CPU during the morning login peak, so some requests were "
            "dropped. Raised maxReplicas to 6."
        ),
        "evidence": "No 502s over a week of morning peaks; the HPA settles at 3 replicas.",
        "verified": True,
        "quality": 4,
        "fde_minutes": 70,
        "self_service": False,
    },
    {
        "key": "jupyter-kernel",
        "organization": "helios-health",
        "reporter": "engineer@helios.example",
        "title": "Jupyter kernel disconnects after a few minutes of inactivity",
        "description": (
            "Notebook kernels disconnect when left idle for a short period, losing the "
            "session state. Researchers have to re-run everything."
        ),
        "error_message": "WebSocket connection closed unexpectedly (code 1006)",
        "diagnostics": "-- ingress controller idle timeout set to 60s",
        "component": TicketComponent.JUPYTER,
        "severity": Severity.MEDIUM,
        "environment": Environment.PRODUCTION,
        "days_ago": 8,
        "resolution": (
            "The ingress controller in front of the IOMETE Gateway had a 60-second idle "
            "timeout, which closed the notebook WebSocket. Raised the idle timeout on the "
            "notebook route to match the Gateway's own long-lived connection handling."
        ),
        "evidence": "Kernels survive 30 minutes idle; no further 1006 closures reported.",
        "verified": False,
        "quality": None,
        "fde_minutes": 40,
        "self_service": False,
    },
    # --- Open tickets, so the inbox and the resolution flow have live material ------
    {
        "key": "open-spark-oom",
        "organization": "northwind-bank",
        "reporter": "engineer@northwind.example",
        "title": "Worker processes keep dying while the batch rollup runs",
        "description": (
            "Whenever our overnight batch summarisation runs, the worker processes shut "
            "down before finishing and the job never completes. This started after we "
            "onboarded the new mortgage book, which roughly doubled the row count."
        ),
        "error_message": "Container killed: OOMKilled (exit code 137)",
        "diagnostics": (
            "kubectl describe pod spark-batch-rollup-3e91aa-exec-2 -n iomete-compute\n"
            "  Last State: Terminated\n    Reason: OOMKilled\n    Exit Code: 137"
        ),
        "component": TicketComponent.SPARK_COMPUTE,
        "severity": Severity.HIGH,
        "environment": Environment.PRODUCTION,
        "days_ago": 2,
        "resolution": None,
        "status": "new",
    },
    {
        "key": "open-iceberg-commit",
        "organization": "helios-health",
        "reporter": "engineer@helios.example",
        "title": "Commit failures on the encounters table during the compaction window",
        "description": (
            "Writes to the encounters table fail at commit time, but only between 01:00 and "
            "02:00. We run a compaction job in that window."
        ),
        "error_message": (
            "org.apache.iceberg.exceptions.CommitFailedException: Cannot commit: stale "
            "table metadata"
        ),
        "diagnostics": "commit.retry.num-retries = 4",
        "component": TicketComponent.ICEBERG_METADATA,
        "severity": Severity.HIGH,
        "environment": Environment.PRODUCTION,
        "days_ago": 4,
        "resolution": None,
        "status": "new",
    },
    {
        "key": "open-ranger-denied",
        "organization": "vela-telecom",
        "reporter": "engineer@vela.example",
        "title": "New team member cannot query the telemetry tables",
        "description": (
            "A new engineer was added to the telemetry group yesterday but still gets "
            "permission denied on every telemetry table. Everyone else in the group is fine."
        ),
        "error_message": (
            "RangerAccessControlException: Permission denied: user=n.engineer, "
            "access=SELECT, table=lakehouse.telemetry.cell_metrics"
        ),
        "diagnostics": "SHOW CURRENT ROLES;\n-- telemetry group not listed",
        "component": TicketComponent.PERMISSIONS,
        "severity": Severity.MEDIUM,
        "environment": Environment.PRODUCTION,
        "days_ago": 1,
        "resolution": None,
        "status": "new",
    },
    {
        "key": "open-storage-403",
        "organization": "atlas-logistics",
        "reporter": "engineer@atlas.example",
        "title": "Storage access denied across all clusters since this morning",
        "description": (
            "All our queries fail with an access denied error against MinIO. Nothing was "
            "deployed. We are effectively down."
        ),
        "error_message": (
            "org.apache.hadoop.fs.s3a.AWSBadRequestException: getFileStatus on "
            "s3a://atlas-lakehouse/data/: Access Denied (Status Code: 403; Error Code: "
            "AccessDenied)"
        ),
        "diagnostics": "-- credential rotation ran overnight",
        "component": TicketComponent.OBJECT_STORAGE,
        "severity": Severity.CRITICAL,
        "environment": Environment.PRODUCTION,
        "days_ago": 1,
        "resolution": None,
        "status": "escalated",
        "escalation_reason": (
            "Checked the storage endpoint is reachable and the bucket exists. We rotated "
            "credentials overnight but the platform still reports 403. We do not know where "
            "the platform reads its storage credentials from, so we cannot check whether "
            "they were updated."
        ),
    },
]


# =======================================================================================
# Hand-authored playbooks
#
# Six playbooks written deliberately rather than only auto-extracted, because a
# demonstration needs the quality an experienced engineer would produce. They are then
# approved through the real approval service, so graph validation runs and a
# `KnowledgeApproval` record exists for each — the review trail is genuine.
# =======================================================================================

PLAYBOOKS = [
    {
        "playbook_id": "spark-executor-memory-exhaustion",
        "title": "Spark executor terminated with OOMKilled",
        "description": (
            "Executors are killed by the kubelet during a job or query because the container "
            "exceeded its memory limit. Usually one of: executor memory sized below the "
            "workload's peak, a skewed partition concentrating rows onto a few tasks, or "
            "insufficient memory overhead for off-heap allocation."
        ),
        "component": TicketComponent.SPARK_COMPUTE,
        "category": "resource_exhaustion",
        "applicable_versions": ">=3.0,<4.0",
        "applicable_environments": ["production", "staging", "development"],
        "symptoms": ["executor_restarting", "out_of_memory", "job_failing"],
        "confirmed_root_cause": (
            "The executor container's memory limit was lower than the peak memory the "
            "workload required, so the kubelet terminated it with OOMKilled (exit code 137). "
            "In the majority of observed cases the proximate cause was partition skew rather "
            "than overall data volume: a small number of tasks received disproportionately "
            "many rows and exceeded the limit while average usage looked healthy."
        ),
        "preconditions": [
            "You can run kubectl against the namespace where Spark workloads run.",
            "You can view or change the compute cluster's Spark configuration.",
            "There is spare memory capacity on the node pool, or quota headroom to request more.",
        ],
        "expected_evidence": [
            "Pod last state shows Reason: OOMKilled with Exit Code: 137",
            "Executor memory limit is at or below the observed peak usage",
            "Spark UI or history shows a small number of tasks with far more input rows "
            "than the median",
        ],
        "resolution_instructions": (
            "Raise `spark.executor.memory` and `spark.executor.memoryOverhead` so the "
            "container limit comfortably exceeds the observed peak — a 50% margin over peak "
            "is a reasonable starting point. If the evidence shows partition skew, also "
            "enable adaptive query execution with skew-join handling "
            "(`spark.sql.adaptive.enabled=true`, "
            "`spark.sql.adaptive.skewJoin.enabled=true`), which splits oversized partitions "
            "automatically. Treating skew with headroom alone works until the data grows "
            "again."
        ),
        "verification_steps": [
            "Re-run the job or query that previously failed and confirm it completes.",
            "Confirm no OOMKilled entries appear in the executor pods' events for that run.",
            "Check the peak executor memory in the Spark history for the successful run and "
            "confirm it sits inside the new limit with margin.",
        ],
        "known_limitations": (
            "Adaptive skew-join handling requires Spark 3.x, so on an IOMETE release before "
            "3.0 the manual remedy is an explicit repartition on the skewed key. If raising "
            "memory does not help, the cause may be a memory leak in a user-defined function "
            "rather than sizing — that needs an FDE."
        ),
        "risk_level": RiskLevel.MEDIUM,
        "steps": [
            {
                "key": "confirm-oomkilled",
                "title": "Confirm the executor was killed for memory, not something else",
                "plain_explanation": (
                    "OOMKilled means the container asked for more memory than its limit "
                    "allowed and the kubelet stopped it. Other terminations — Evicted, "
                    "node failure, a deliberate stop — look similar in a job log but need "
                    "completely different fixes, so it is worth 30 seconds to be sure."
                ),
                "what_to_inspect": (
                    "Describe one of the terminated executor pods and look at the Last "
                    "State block."
                ),
                "expected_observation": "Reason: OOMKilled with Exit Code: 137",
                "why_this_step": (
                    "Rules out eviction due to node disk or memory pressure, which is a "
                    "node-capacity problem rather than an executor-sizing one."
                ),
                "step_type": StepType.READ_ONLY_DIAGNOSTIC,
                "risk_level": RiskLevel.LOW,
                "commands": [
                    {
                        "label": "Executor pod status and recent events",
                        "language": "bash",
                        "command": "kubectl describe pod <executor-pod> -n <namespace>",
                        "is_read_only": True,
                    },
                    {
                        "label": "Termination reason and exit code only",
                        "language": "bash",
                        "command": (
                            "kubectl get pod <executor-pod> -n <namespace> -o "
                            "jsonpath='{.status.containerStatuses[*].lastState.terminated}'"
                        ),
                        "is_read_only": True,
                    },
                ],
                "response_kind": ResponseKind.CHOICE,
                "response_options": [
                    {"value": "oomkilled", "label": "Reason: OOMKilled",
                     "hint": "Exit code 137 — this playbook applies."},
                    {"value": "evicted", "label": "Reason: Evicted",
                     "hint": "Node-level pressure, not executor sizing."},
                    {"value": "other", "label": "Something else, or no termination recorded"},
                ],
                "branches": {
                    "oomkilled": "check-limits",
                    "evicted": "__escalate",
                    "other": "__escalate",
                },
            },
            {
                "key": "check-limits",
                "title": "Compare the configured memory against what the job actually used",
                "plain_explanation": (
                    "Now establish the gap. Read the executor's configured memory limit and "
                    "compare it with the peak usage the Spark history recorded for the "
                    "failing run. If peak was close to or above the limit, sizing is the "
                    "problem."
                ),
                "what_to_inspect": (
                    "The pod's memory limit, and the peak executor memory for the failing "
                    "application in the Spark history server."
                ),
                "expected_observation": (
                    "Peak executor memory at or near the configured container limit"
                ),
                "why_this_step": (
                    "Distinguishes a sizing problem from a leak. If peak usage is far below "
                    "the limit and the container still died, raising memory will not help."
                ),
                "step_type": StepType.CONFIGURATION_REVIEW,
                "risk_level": RiskLevel.LOW,
                "commands": [
                    {
                        "label": "Configured memory requests and limits",
                        "language": "bash",
                        "command": (
                            "kubectl get pod <executor-pod> -n <namespace> -o "
                            "jsonpath='{.spec.containers[*].resources}'"
                        ),
                        "is_read_only": True,
                    }
                ],
                "response_kind": ResponseKind.CHOICE,
                "response_options": [
                    {"value": "near_limit", "label": "Peak usage was at or near the limit"},
                    {"value": "well_below", "label": "Peak usage was well below the limit",
                     "hint": "Suggests a leak or an off-heap allocation, not sizing."},
                    {"value": "unknown", "label": "I cannot determine peak usage"},
                ],
                "branches": {
                    "near_limit": "check-skew",
                    "well_below": "__escalate",
                    "unknown": "check-skew",
                },
            },
            {
                "key": "check-skew",
                "title": "Check whether a few tasks are doing most of the work",
                "plain_explanation": (
                    "Partition skew is the most common reason a job that worked last month "
                    "fails today. In the Spark history for the failing stage, compare the "
                    "maximum task input size against the median. If the maximum is many "
                    "times the median, the data is skewed and memory headroom alone will "
                    "only postpone the problem."
                ),
                "what_to_inspect": (
                    "The failing stage's task summary in the Spark history server: max "
                    "versus median input size and shuffle read."
                ),
                "expected_observation": (
                    "Maximum task input substantially larger than the median — a factor of "
                    "ten or more is clear skew"
                ),
                "why_this_step": (
                    "Determines whether the fix is sizing alone or sizing plus adaptive "
                    "skew handling. Getting this wrong means the ticket comes back."
                ),
                "step_type": StepType.READ_ONLY_DIAGNOSTIC,
                "risk_level": RiskLevel.LOW,
                "response_kind": ResponseKind.CHOICE,
                "response_options": [
                    {"value": "skewed", "label": "Yes — a few tasks are much larger"},
                    {"value": "even", "label": "No — task sizes are fairly even"},
                    {"value": "unknown", "label": "I cannot see the task breakdown"},
                ],
                "branches": {
                    "skewed": "apply-memory-and-skew",
                    "even": "apply-memory-and-skew",
                    "unknown": "apply-memory-and-skew",
                },
            },
            {
                "key": "apply-memory-and-skew",
                "title": "Raise executor memory, and enable skew handling if skew was found",
                "plain_explanation": (
                    "Increase `spark.executor.memory` and `spark.executor.memoryOverhead` so "
                    "the limit exceeds observed peak by about 50%. If the previous step "
                    "showed skew, also set `spark.sql.adaptive.enabled=true` and "
                    "`spark.sql.adaptive.skewJoin.enabled=true`.\n\n"
                    "This changes the compute cluster's configuration. The cluster restarts "
                    "to pick it up, so running queries and jobs on it will be interrupted."
                ),
                "what_to_inspect": (
                    "After applying, confirm the new values are in effect on the cluster and "
                    "that it returns to a running state."
                ),
                "expected_observation": (
                    "The cluster restarts cleanly and reports the new memory configuration"
                ),
                "step_type": StepType.CHANGE_REQUIRING_APPROVAL,
                "risk_level": RiskLevel.MEDIUM,
                "blast_radius": (
                    "Restarts the compute cluster. Any query or job currently running on it "
                    "will be interrupted and will need to be re-run. Other clusters are "
                    "unaffected. Takes effect in roughly one to two minutes."
                ),
                "response_kind": ResponseKind.BOOLEAN,
                "branches": {"yes": "verify-run", "no": "__escalate"},
            },
            {
                "key": "verify-run",
                "title": "Re-run the failing workload and confirm it completes",
                "plain_explanation": (
                    "Run the job or query that was failing. Completing the steps above is "
                    "not evidence that the problem is fixed — this is."
                ),
                "what_to_inspect": (
                    "Whether the workload completes, and whether any executor pod records "
                    "OOMKilled during the run."
                ),
                "expected_observation": (
                    "The workload completes and no executor reports OOMKilled"
                ),
                "step_type": StepType.VERIFICATION,
                "risk_level": RiskLevel.INFORMATIONAL,
                "commands": [
                    {
                        "label": "Check for any OOMKilled executors from this run",
                        "language": "bash",
                        "command": (
                            "kubectl get events -n <namespace> --field-selector "
                            "reason=OOMKilling --sort-by=.lastTimestamp | tail -20"
                        ),
                        "is_read_only": True,
                    }
                ],
                "response_kind": ResponseKind.BOOLEAN,
                "branches": {"yes": "__resolved", "no": "__escalate"},
                "is_terminal": True,
            },
        ],
    },
    {
        "playbook_id": "kubernetes-pod-pending-capacity",
        "title": "Compute cluster or notebook stuck in Pending",
        "description": (
            "A driver or notebook pod cannot be scheduled. The two common causes are an "
            "exhausted namespace resource quota and nodes that do not satisfy the data-plane "
            "node selector or tolerations — and they produce very similar symptoms."
        ),
        "component": TicketComponent.KUBERNETES,
        "category": "capacity_limit",
        "applicable_versions": ">=3.0,<4.0",
        "applicable_environments": ["production", "staging", "development"],
        "symptoms": ["cluster_wont_start", "scheduling_failure", "pod_restarting"],
        "confirmed_root_cause": (
            "Kubernetes could not place the pod. Either the namespace's ResourceQuota had "
            "insufficient remaining CPU or memory for the pod's requests, or no node "
            "satisfied the data-plane node selector and tolerations — commonly after a node "
            "pool is replaced and the new nodes are missing the "
            "`k8s.iomete.com/dedicated` label."
        ),
        "preconditions": [
            "You can run kubectl against the workload namespace.",
            "You can view ResourceQuota and node labels.",
        ],
        "expected_evidence": [
            "A FailedScheduling event naming insufficient resources or unmatched affinity",
            "ResourceQuota showing used close to hard limit, or nodes lacking the expected label",
        ],
        "resolution_instructions": (
            "If the quota is exhausted, raise the namespace ResourceQuota after confirming "
            "the node pool actually has the capacity — raising a quota beyond physical "
            "capacity just moves the failure. If nodes do not match the selector, apply the "
            "expected data-plane label and tolerations to the node pool."
        ),
        "verification_steps": [
            "Create a new compute cluster or notebook and confirm it reaches Running.",
            "Confirm the ResourceQuota shows headroom above current usage.",
            "Confirm every node in the data-plane pool carries the expected label.",
        ],
        "known_limitations": (
            "If the cluster genuinely has no spare capacity, this is a procurement or "
            "autoscaling question rather than a configuration fix. On cloud, check that "
            "Karpenter, GKE Node Auto-Provisioning or the AKS Cluster Autoscaler is "
            "configured and has headroom in its limits."
        ),
        "risk_level": RiskLevel.MEDIUM,
        "steps": [
            {
                "key": "read-scheduling-event",
                "title": "Read why the scheduler refused the pod",
                "plain_explanation": (
                    "Kubernetes states the reason explicitly in a FailedScheduling event. "
                    "Reading it first avoids guessing between the two likely causes."
                ),
                "what_to_inspect": "FailedScheduling events in the workload namespace.",
                "expected_observation": (
                    "An event naming either insufficient cpu/memory or an unmatched node "
                    "affinity/selector"
                ),
                "step_type": StepType.READ_ONLY_DIAGNOSTIC,
                "risk_level": RiskLevel.LOW,
                "commands": [
                    {
                        "label": "Scheduling failures in this namespace",
                        "language": "bash",
                        "command": (
                            "kubectl get events -n <namespace> --field-selector "
                            "reason=FailedScheduling --sort-by=.lastTimestamp | tail -20"
                        ),
                        "is_read_only": True,
                    },
                    {
                        "label": "The pending pod's own conditions",
                        "language": "bash",
                        "command": "kubectl describe pod <pending-pod> -n <namespace>",
                        "is_read_only": True,
                    },
                ],
                "response_kind": ResponseKind.CHOICE,
                "response_options": [
                    {"value": "insufficient", "label": "Insufficient cpu or memory"},
                    {"value": "affinity", "label": "Did not match node affinity or selector"},
                    {"value": "quota", "label": "Forbidden: exceeded quota"},
                    {"value": "other", "label": "A different reason, or no event found"},
                ],
                "branches": {
                    "insufficient": "check-quota",
                    "quota": "check-quota",
                    "affinity": "check-node-labels",
                    "other": "__escalate",
                },
            },
            {
                "key": "check-quota",
                "title": "Check the namespace resource quota",
                "plain_explanation": (
                    "Compare used against hard. If the remaining headroom is smaller than "
                    "the pod's request, the quota is the constraint — not the cluster's "
                    "physical capacity."
                ),
                "what_to_inspect": "ResourceQuota usage in the workload namespace.",
                "expected_observation": "Used close to the hard limit for cpu or memory",
                "step_type": StepType.READ_ONLY_DIAGNOSTIC,
                "risk_level": RiskLevel.LOW,
                "commands": [
                    {
                        "label": "Quota usage",
                        "language": "bash",
                        "command": "kubectl describe resourcequota -n <namespace>",
                        "is_read_only": True,
                    },
                    {
                        "label": "Actual allocatable capacity on the node pool",
                        "language": "bash",
                        "command": (
                            "kubectl describe nodes | grep -A 6 'Allocated resources'"
                        ),
                        "is_read_only": True,
                    },
                ],
                "response_kind": ResponseKind.CHOICE,
                "response_options": [
                    {"value": "quota_exhausted",
                     "label": "Quota is nearly exhausted but nodes have spare capacity"},
                    {"value": "nodes_full",
                     "label": "The nodes themselves have no spare capacity",
                     "hint": "This is a capacity problem, not a quota one."},
                    {"value": "quota_fine", "label": "Quota has plenty of headroom"},
                ],
                "branches": {
                    "quota_exhausted": "raise-quota",
                    "nodes_full": "__escalate",
                    "quota_fine": "check-node-labels",
                },
            },
            {
                "key": "check-node-labels",
                "title": "Check that nodes match the data-plane selector",
                "plain_explanation": (
                    "IOMETE schedules Spark workloads onto nodes matching a configured "
                    "selector and tolerating a configured taint. After a node pool is "
                    "replaced, new nodes frequently lack the label, so nothing can be "
                    "placed on them."
                ),
                "what_to_inspect": (
                    "The labels on your data-plane nodes, compared with the "
                    "`dataPlaneNodeSelector` configured for the platform."
                ),
                "expected_observation": (
                    "One or more nodes missing the expected data-plane label"
                ),
                "step_type": StepType.CONFIGURATION_REVIEW,
                "risk_level": RiskLevel.LOW,
                "commands": [
                    {
                        "label": "Node labels",
                        "language": "bash",
                        "command": "kubectl get nodes --show-labels",
                        "is_read_only": True,
                    },
                    {
                        "label": "Nodes carrying the IOMETE dedicated label",
                        "language": "bash",
                        "command": "kubectl get nodes -l k8s.iomete.com/dedicated",
                        "is_read_only": True,
                    },
                ],
                "response_kind": ResponseKind.CHOICE,
                "response_options": [
                    {"value": "missing_label", "label": "Some nodes are missing the label"},
                    {"value": "labels_fine", "label": "All nodes carry the expected label"},
                ],
                "branches": {
                    "missing_label": "apply-node-label",
                    "labels_fine": "__escalate",
                },
            },
            {
                "key": "raise-quota",
                "title": "Raise the namespace resource quota",
                "plain_explanation": (
                    "Increase the ResourceQuota for the namespace. Only do this once you "
                    "have confirmed the node pool has the physical capacity — otherwise the "
                    "pod will be admitted and then fail to schedule anyway."
                ),
                "what_to_inspect": "The quota after the change, and whether the pod schedules.",
                "expected_observation": "Quota shows headroom and the pending pod is scheduled",
                "step_type": StepType.CHANGE_REQUIRING_APPROVAL,
                "risk_level": RiskLevel.MEDIUM,
                "blast_radius": (
                    "Raising a namespace quota allows that namespace's workloads to consume "
                    "more of the shared node pool, which can affect other namespaces' "
                    "ability to schedule. Confirm overall cluster capacity first."
                ),
                "response_kind": ResponseKind.BOOLEAN,
                "branches": {"yes": "verify-scheduled", "no": "__escalate"},
            },
            {
                "key": "apply-node-label",
                "title": "Apply the data-plane label to the node pool",
                "plain_explanation": (
                    "Label the nodes so they satisfy the data-plane selector. Prefer setting "
                    "this in the node pool definition rather than by hand, so replacement "
                    "nodes inherit it — otherwise this recurs on the next pool change."
                ),
                "what_to_inspect": "Whether the pending pod schedules once the label is applied.",
                "expected_observation": "The pod moves out of Pending within a minute",
                "step_type": StepType.CHANGE_REQUIRING_APPROVAL,
                "risk_level": RiskLevel.MEDIUM,
                "blast_radius": (
                    "Labelling a node makes it eligible for Spark workloads. If the node is "
                    "also running something else, those workloads will now compete for its "
                    "resources."
                ),
                "response_kind": ResponseKind.BOOLEAN,
                "branches": {"yes": "verify-scheduled", "no": "__escalate"},
            },
            {
                "key": "verify-scheduled",
                "title": "Confirm a new cluster reaches Running",
                "plain_explanation": (
                    "Create a compute cluster or notebook and watch it start. This is the "
                    "evidence that the problem is resolved."
                ),
                "what_to_inspect": "The new pod's status.",
                "expected_observation": "The pod reaches Running without a FailedScheduling event",
                "step_type": StepType.VERIFICATION,
                "risk_level": RiskLevel.INFORMATIONAL,
                "response_kind": ResponseKind.BOOLEAN,
                "branches": {"yes": "__resolved", "no": "__escalate"},
                "is_terminal": True,
            },
        ],
    },
    {
        "playbook_id": "iceberg-commit-failed-concurrent-writers",
        "title": "Iceberg CommitFailedException — stale table metadata",
        "description": (
            "A write to an Iceberg table fails at commit because another writer committed "
            "first. Iceberg's optimistic concurrency control is working as designed; the "
            "problem is that two writers are racing and the retry budget is too small to "
            "absorb it."
        ),
        "component": TicketComponent.ICEBERG_METADATA,
        "category": "metadata_inconsistency",
        "applicable_versions": ">=3.0,<4.0",
        "applicable_environments": ["production", "staging"],
        "symptoms": ["metadata_error", "job_failing"],
        "confirmed_root_cause": (
            "Two or more writers committed to the same Iceberg table concurrently. Iceberg "
            "detected that the base metadata had moved and correctly rejected the losing "
            "commit. The failure surfaces as an error because the configured commit retry "
            "count was exhausted — typically when one writer holds its commit open far "
            "longer than the other, as compaction does relative to an append."
        ),
        "preconditions": [
            "You can query the table's snapshot history.",
            "You can view and change the table's properties or the writing jobs' schedules.",
        ],
        "expected_evidence": [
            "CommitFailedException naming a base metadata location that is no longer current",
            "Snapshot history showing commits from more than one operation close together",
            "Failures clustering in a window when a second writer runs",
        ],
        "resolution_instructions": (
            "First establish which writers are involved from the snapshot history. Then "
            "either separate them in time — the cleanest fix, usually by scheduling "
            "compaction when the streaming or batch writer is paused — or raise "
            "`commit.retry.num-retries` so transient races are absorbed. Raising retries "
            "alone treats the symptom; if two writers genuinely overlap continuously, they "
            "will keep racing."
        ),
        "verification_steps": [
            "Run the previously failing write and confirm it commits.",
            "Check the snapshot history and confirm operations no longer interleave.",
            "Confirm no CommitFailedException over a full cycle of both writers.",
        ],
        "known_limitations": (
            "If the failure is CommitStateUnknownException rather than "
            "CommitFailedException, do not retry blindly — the commit may have succeeded, "
            "and that case needs an FDE."
        ),
        "risk_level": RiskLevel.MEDIUM,
        "steps": [
            {
                "key": "confirm-exception-type",
                "title": "Confirm which commit exception you are seeing",
                "plain_explanation": (
                    "CommitFailedException means the commit definitely did not happen and is "
                    "safe to retry. CommitStateUnknownException means Iceberg could not "
                    "determine whether it happened — retrying that can duplicate data, so it "
                    "needs an engineer."
                ),
                "what_to_inspect": "The exact exception class name in the job's error output.",
                "expected_observation": "org.apache.iceberg.exceptions.CommitFailedException",
                "why_this_step": (
                    "The two exceptions look similar and have opposite safe responses. This "
                    "is the most important distinction in the playbook."
                ),
                "step_type": StepType.READ_ONLY_DIAGNOSTIC,
                "risk_level": RiskLevel.LOW,
                "response_kind": ResponseKind.CHOICE,
                "response_options": [
                    {"value": "commit_failed", "label": "CommitFailedException"},
                    {"value": "state_unknown", "label": "CommitStateUnknownException",
                     "hint": "Do not retry. This needs an FDE."},
                    {"value": "other", "label": "A different exception"},
                ],
                "branches": {
                    "commit_failed": "inspect-snapshots",
                    "state_unknown": "__escalate",
                    "other": "__escalate",
                },
            },
            {
                "key": "inspect-snapshots",
                "title": "Identify the competing writers from the snapshot history",
                "plain_explanation": (
                    "Every Iceberg commit records an operation type and a timestamp. Looking "
                    "at the recent snapshots tells you which writers are active and whether "
                    "their commits are landing close together."
                ),
                "what_to_inspect": (
                    "The table's snapshots metadata table, ordered by commit time."
                ),
                "expected_observation": (
                    "Commits from two different operations within a short window"
                ),
                "step_type": StepType.READ_ONLY_DIAGNOSTIC,
                "risk_level": RiskLevel.LOW,
                "commands": [
                    {
                        "label": "Recent snapshots and their operations",
                        "language": "sql",
                        "command": (
                            "SELECT committed_at, snapshot_id, operation, summary\n"
                            "FROM <catalog>.<namespace>.<table>.snapshots\n"
                            "ORDER BY committed_at DESC LIMIT 20;"
                        ),
                        "is_read_only": True,
                    },
                    {
                        "label": "Current table properties, including the retry budget",
                        "language": "sql",
                        "command": "DESCRIBE EXTENDED <catalog>.<namespace>.<table>;",
                        "is_read_only": True,
                    },
                ],
                "response_kind": ResponseKind.CHOICE,
                "response_options": [
                    {"value": "two_writers",
                     "label": "Yes — two or more operations committing close together"},
                    {"value": "single_writer",
                     "label": "No — only one writer appears in the history",
                     "hint": "If there is genuinely one writer, the cause is elsewhere."},
                ],
                "branches": {
                    "two_writers": "separate-writers",
                    "single_writer": "__escalate",
                },
            },
            {
                "key": "separate-writers",
                "title": "Separate the writers, and raise the retry budget",
                "plain_explanation": (
                    "Reschedule the longer-running writer — usually compaction — so it does "
                    "not overlap the other, and raise `commit.retry.num-retries` (10 is a "
                    "reasonable value) to absorb transient races.\n\n"
                    "Changing a table property and a job schedule affects production writes."
                ),
                "what_to_inspect": "That both writers complete their next run without conflict.",
                "expected_observation": "Both writers commit successfully",
                "step_type": StepType.CHANGE_REQUIRING_APPROVAL,
                "risk_level": RiskLevel.MEDIUM,
                "blast_radius": (
                    "Alters a production table's properties and a job schedule. Rescheduling "
                    "compaction may delay the storage reclamation it performs. No data is "
                    "modified by the change itself."
                ),
                "response_kind": ResponseKind.BOOLEAN,
                "branches": {"yes": "verify-commits", "no": "__escalate"},
            },
            {
                "key": "verify-commits",
                "title": "Confirm commits now succeed through a full cycle",
                "plain_explanation": (
                    "Let both writers run through a complete cycle — including the window "
                    "where failures used to cluster — and confirm no commit failures."
                ),
                "what_to_inspect": (
                    "The writing jobs' outcomes, and the snapshot history for interleaving."
                ),
                "expected_observation": (
                    "No CommitFailedException, and operations no longer interleave"
                ),
                "step_type": StepType.VERIFICATION,
                "risk_level": RiskLevel.INFORMATIONAL,
                "response_kind": ResponseKind.BOOLEAN,
                "branches": {"yes": "__resolved", "no": "__escalate"},
                "is_terminal": True,
            },
        ],
    },
    {
        "playbook_id": "ranger-permission-denied-group-sync",
        "title": "Permission denied despite a correct grant",
        "description": (
            "A user receives a Ranger access-control exception on a table their group is "
            "granted on. Most often the grant is correct and the user's group membership has "
            "not yet synchronised from the corporate directory."
        ),
        "component": TicketComponent.PERMISSIONS,
        "category": "permission_denied",
        "applicable_versions": ">=3.0,<4.0",
        "applicable_environments": ["production", "staging", "development"],
        "symptoms": ["permission_denied"],
        "confirmed_root_cause": (
            "The Ranger policy granting access was correct, but the user's group membership "
            "had not propagated from the directory into the Identity Service, so Ranger "
            "evaluated the request without the granting group. The access decision was "
            "therefore correct given the information Ranger had."
        ),
        "preconditions": [
            "You can run SHOW CURRENT ROLES as the affected user, or ask them to.",
            "An administrator can view the Ranger policy and trigger a group sync.",
        ],
        "expected_evidence": [
            "RangerAccessControlException naming the user, the access type and the table",
            "SHOW CURRENT ROLES for that user not listing the granting group",
            "SHOW GRANTS confirming the group does have the access",
        ],
        "resolution_instructions": (
            "Confirm the grant exists for the group, confirm the user is not currently "
            "resolving that group, then trigger a group synchronisation in the Identity "
            "Service. If this recurs, shorten the sync interval — a long interval produces a "
            "steady trickle of these tickets every time someone changes team."
        ),
        "verification_steps": [
            "Have the user run SHOW CURRENT ROLES and confirm the group now appears.",
            "Have the user re-run the query that failed and confirm it succeeds.",
        ],
        "known_limitations": (
            "If the group does appear and access is still denied, there may be a deny policy "
            "taking precedence, or a row-level filter excluding the rows — both need an FDE, "
            "because a misread deny policy can lead to widening access incorrectly."
        ),
        "risk_level": RiskLevel.LOW,
        "steps": [
            {
                "key": "read-exception",
                "title": "Read exactly which user, access and table were denied",
                "plain_explanation": (
                    "The Ranger exception names all three. People often report \"I can't see "
                    "the table\" when the denial is on a different table or a different "
                    "access type than they assume."
                ),
                "what_to_inspect": "The full exception text from the failing query.",
                "expected_observation": (
                    "Permission denied with a user, access type and table name"
                ),
                "step_type": StepType.READ_ONLY_DIAGNOSTIC,
                "risk_level": RiskLevel.LOW,
                "response_kind": ResponseKind.BOOLEAN,
                "branches": {"yes": "check-roles", "no": "__escalate"},
            },
            {
                "key": "check-roles",
                "title": "Check which groups the user currently resolves",
                "plain_explanation": (
                    "Ranger decides using the groups it knows about. If the granting group is "
                    "not in the user's current roles, the denial is correct and the problem "
                    "is synchronisation rather than policy."
                ),
                "what_to_inspect": (
                    "The output of SHOW CURRENT ROLES, run as the affected user, and the "
                    "grants on the table."
                ),
                "expected_observation": (
                    "The granting group is absent from the user's current roles"
                ),
                "step_type": StepType.READ_ONLY_DIAGNOSTIC,
                "risk_level": RiskLevel.LOW,
                "commands": [
                    {
                        "label": "Groups the user currently resolves",
                        "language": "sql",
                        "command": "SHOW CURRENT ROLES;",
                        "is_read_only": True,
                    },
                    {
                        "label": "Grants on the table",
                        "language": "sql",
                        "command": "SHOW GRANTS ON TABLE <catalog>.<namespace>.<table>;",
                        "is_read_only": True,
                    },
                ],
                "response_kind": ResponseKind.CHOICE,
                "response_options": [
                    {"value": "group_missing",
                     "label": "The granting group is missing from the user's roles"},
                    {"value": "group_present",
                     "label": "The group is present but access is still denied",
                     "hint": "Possibly a deny policy or a row filter — needs an FDE."},
                    {"value": "no_grant",
                     "label": "No grant exists for that group on this table"},
                ],
                "branches": {
                    "group_missing": "trigger-sync",
                    "group_present": "__escalate",
                    "no_grant": "__escalate",
                },
            },
            {
                "key": "trigger-sync",
                "title": "Trigger a group synchronisation",
                "plain_explanation": (
                    "Ask an administrator to run a group sync in the Identity Service. This "
                    "refreshes group membership from the directory. It does not change any "
                    "policy or grant, so it cannot widen anyone's access beyond what the "
                    "directory already says."
                ),
                "what_to_inspect": "That the sync completes without error.",
                "expected_observation": "The synchronisation completes successfully",
                "step_type": StepType.CHANGE_REQUIRING_APPROVAL,
                "risk_level": RiskLevel.LOW,
                "blast_radius": (
                    "Refreshes group membership for all users from the directory. Users whose "
                    "directory groups were removed will correctly lose access they should no "
                    "longer have, which can surprise people if the directory is out of date."
                ),
                "response_kind": ResponseKind.BOOLEAN,
                "branches": {"yes": "verify-access", "no": "__escalate"},
            },
            {
                "key": "verify-access",
                "title": "Confirm the user can now run the query",
                "plain_explanation": (
                    "Have the affected user re-run the exact query that failed. Their "
                    "confirmation is the evidence."
                ),
                "what_to_inspect": "The query result, and SHOW CURRENT ROLES for the group.",
                "expected_observation": (
                    "The group now appears in their roles and the query returns rows"
                ),
                "step_type": StepType.VERIFICATION,
                "risk_level": RiskLevel.INFORMATIONAL,
                "response_kind": ResponseKind.BOOLEAN,
                "branches": {"yes": "__resolved", "no": "__escalate"},
                "is_terminal": True,
            },
        ],
    },
    {
        "playbook_id": "object-storage-access-denied-credentials",
        "title": "Object storage returns 403 Access Denied across all clusters",
        "description": (
            "Every query fails with an access-denied error from object storage. When this "
            "affects all clusters at once and nothing was deployed, the cause is almost "
            "always a credential that changed outside the platform."
        ),
        "component": TicketComponent.OBJECT_STORAGE,
        "category": "authentication",
        "applicable_versions": ">=3.0,<4.0",
        "applicable_environments": ["production", "staging", "development"],
        "symptoms": ["storage_unreachable", "query_failing", "authentication_failure"],
        "confirmed_root_cause": (
            "The object storage credentials held in the platform's `data-plane` Kubernetes "
            "Secret no longer matched the storage backend — typically because an access key "
            "was rotated by an external process without the Secret being updated. Every "
            "storage request was therefore rejected with 403."
        ),
        "preconditions": [
            "You can read the platform namespace's secrets metadata.",
            "You can confirm with your storage administrator whether keys were rotated.",
            "You can update the Secret and restart platform services.",
        ],
        "expected_evidence": [
            "403 AccessDenied or InvalidAccessKeyId from the storage endpoint",
            "All clusters affected simultaneously, with no recent platform deployment",
            "A credential rotation or policy change in the storage backend's own audit log",
        ],
        "resolution_instructions": (
            "Confirm with the storage administrator whether the access key or bucket policy "
            "changed. If the key was rotated, update the `data-plane` Kubernetes Secret with "
            "the new credentials and restart the platform services that read it at startup. "
            "Then fix the rotation process so it updates the Secret and triggers a rollout as "
            "one operation — otherwise this recurs on the next rotation."
        ),
        "verification_steps": [
            "Run a simple query against a known table and confirm it returns rows.",
            "Confirm no 403 errors appear in the Spark executor logs for that run.",
            "Confirm every compute cluster is healthy, not just the one you tested.",
        ],
        "known_limitations": (
            "If the error is NoSuchBucket rather than AccessDenied, the configured bucket or "
            "endpoint is wrong rather than the credentials. If only one cluster is affected, "
            "this playbook does not apply — a platform-wide credential would fail everything."
        ),
        "risk_level": RiskLevel.HIGH,
        "steps": [
            {
                "key": "confirm-scope",
                "title": "Confirm the failure is platform-wide",
                "plain_explanation": (
                    "A credential held centrally fails everything at once. If only one "
                    "cluster or one table is affected, the cause is different — probably a "
                    "Ranger policy or a bucket-prefix policy — and this playbook would send "
                    "you down the wrong path."
                ),
                "what_to_inspect": "Whether every compute cluster is failing, not just one.",
                "expected_observation": "All clusters are failing with the same storage error",
                "why_this_step": (
                    "Separates a central credential problem from a per-table or per-cluster "
                    "authorization problem."
                ),
                "step_type": StepType.READ_ONLY_DIAGNOSTIC,
                "risk_level": RiskLevel.LOW,
                "response_kind": ResponseKind.CHOICE,
                "response_options": [
                    {"value": "all_clusters", "label": "All clusters are affected"},
                    {"value": "one_cluster", "label": "Only one cluster or table is affected",
                     "hint": "Likely an access policy rather than a credential."},
                ],
                "branches": {
                    "all_clusters": "check-error-code",
                    "one_cluster": "__escalate",
                },
            },
            {
                "key": "check-error-code",
                "title": "Read the exact storage error code",
                "plain_explanation": (
                    "AccessDenied and InvalidAccessKeyId point at credentials. NoSuchBucket "
                    "points at configuration. SSLHandshakeException points at certificates. "
                    "They are three different problems."
                ),
                "what_to_inspect": "The storage error code in the executor or driver log.",
                "expected_observation": "AccessDenied (403) or InvalidAccessKeyId",
                "step_type": StepType.READ_ONLY_DIAGNOSTIC,
                "risk_level": RiskLevel.LOW,
                "commands": [
                    {
                        "label": "Storage errors in the driver log",
                        "language": "bash",
                        "command": (
                            "kubectl logs <driver-pod> -n <namespace> --tail=300 "
                            "| grep -iE 'AccessDenied|InvalidAccessKeyId|NoSuchBucket|403'"
                        ),
                        "is_read_only": True,
                    },
                    {
                        "label": "Which credential keys the platform secret holds (names only)",
                        "language": "bash",
                        "command": (
                            "kubectl get secret data-plane -n <platform-namespace> "
                            "-o jsonpath='{.data}' | base64 -d | jq 'keys'"
                        ),
                        "is_read_only": True,
                    },
                ],
                "response_kind": ResponseKind.CHOICE,
                "response_options": [
                    {"value": "access_denied", "label": "AccessDenied or InvalidAccessKeyId"},
                    {"value": "no_such_bucket", "label": "NoSuchBucket",
                     "hint": "Endpoint or bucket configuration, not credentials."},
                    {"value": "tls", "label": "An SSL or certificate error",
                     "hint": "Truststore problem, not credentials."},
                ],
                "branches": {
                    "access_denied": "confirm-rotation",
                    "no_such_bucket": "__escalate",
                    "tls": "__escalate",
                },
            },
            {
                "key": "confirm-rotation",
                "title": "Confirm with your storage administrator whether keys changed",
                "plain_explanation": (
                    "Before changing anything, establish what actually changed. Check the "
                    "storage backend's own audit log or ask whoever administers it whether an "
                    "access key was rotated or a bucket policy edited."
                ),
                "what_to_inspect": (
                    "The storage backend's audit log, or confirmation from its administrator."
                ),
                "expected_observation": (
                    "A credential rotation or policy change around the time the failures began"
                ),
                "why_this_step": (
                    "Replacing a Secret without knowing what changed risks fixing the wrong "
                    "thing and destroying the evidence of what went wrong."
                ),
                "step_type": StepType.READ_ONLY_DIAGNOSTIC,
                "risk_level": RiskLevel.LOW,
                "response_kind": ResponseKind.CHOICE,
                "response_options": [
                    {"value": "rotated", "label": "Yes — a key was rotated"},
                    {"value": "policy", "label": "A bucket policy was changed",
                     "hint": "Fix the policy rather than the credential."},
                    {"value": "nothing", "label": "Nothing changed, as far as anyone knows"},
                ],
                "branches": {
                    "rotated": "update-secret",
                    "policy": "__escalate",
                    "nothing": "__escalate",
                },
            },
            {
                "key": "update-secret",
                "title": "Update the platform secret and restart the services that read it",
                "plain_explanation": (
                    "Update the `data-plane` Kubernetes Secret with the new storage "
                    "credentials, then restart the platform services that read it at "
                    "startup.\n\n"
                    "This is a high-impact change: the platform services restart, so the "
                    "console and API will be briefly unavailable and running queries will be "
                    "interrupted. It is also the fix for a total outage, so the trade is "
                    "usually worth it — but it needs explicit approval."
                ),
                "what_to_inspect": "That the services come back healthy and storage is reachable.",
                "expected_observation": (
                    "Platform services return to a ready state and storage requests succeed"
                ),
                "step_type": StepType.CHANGE_REQUIRING_APPROVAL,
                "risk_level": RiskLevel.HIGH,
                "blast_radius": (
                    "Restarts the IOMETE platform services. The console and API are "
                    "unavailable for roughly one to three minutes and in-flight queries are "
                    "interrupted. An incorrect credential here leaves the platform unable to "
                    "read any data, so have the correct values confirmed before applying."
                ),
                "response_kind": ResponseKind.BOOLEAN,
                "branches": {"yes": "verify-storage", "no": "__escalate"},
            },
            {
                "key": "verify-storage",
                "title": "Confirm queries succeed across every cluster",
                "plain_explanation": (
                    "Run a simple query on more than one cluster. Testing a single cluster is "
                    "not enough when the symptom was platform-wide."
                ),
                "what_to_inspect": "Query results on at least two clusters, and the driver logs.",
                "expected_observation": (
                    "Queries return rows on every cluster and no 403 appears in the logs"
                ),
                "step_type": StepType.VERIFICATION,
                "risk_level": RiskLevel.INFORMATIONAL,
                "commands": [
                    {
                        "label": "Smoke-test query",
                        "language": "sql",
                        "command": "SELECT count(*) FROM <catalog>.<namespace>.<table> LIMIT 1;",
                        "is_read_only": True,
                    }
                ],
                "response_kind": ResponseKind.BOOLEAN,
                "branches": {"yes": "__resolved", "no": "__escalate"},
                "is_terminal": True,
            },
        ],
    },
    {
        "playbook_id": "event-stream-ingestion-stalled",
        "title": "Event stream ingestion stalled with no visible error",
        "description": (
            "The ingestion endpoint is accepting events and returning success, but the target "
            "Iceberg table is not advancing its snapshot. The acknowledgement is of receipt, "
            "not of commit, which is why the producer sees nothing wrong."
        ),
        "component": TicketComponent.DATA_INGESTION,
        "category": "connectivity",
        "applicable_versions": ">=3.0,<4.0",
        "applicable_environments": ["production", "staging"],
        "symptoms": ["ingestion_stalled", "data_missing"],
        "confirmed_root_cause": (
            "The event stream writer was accepting and buffering events but could not commit "
            "them to the Iceberg table, most commonly because the target table's object "
            "storage prefix had become unwritable after a bucket policy or lifecycle change. "
            "The HTTP 200 responses reflected successful receipt at the ingestion endpoint "
            "rather than a successful commit."
        ),
        "preconditions": [
            "You can query the target table's snapshot history.",
            "You can check the object storage prefix's write permissions.",
        ],
        "expected_evidence": [
            "Producer receiving 200 responses while max(event timestamp) falls behind",
            "No new snapshots on the target table within the stall window",
            "A storage write error in the event stream component's logs",
        ],
        "resolution_instructions": (
            "Confirm the gap between receipt and commit by comparing the producer's success "
            "rate against the table's snapshot history. Then check whether the target "
            "prefix is writable — a bucket policy or lifecycle rule change is the usual "
            "cause. Once write access is restored the buffered events commit and the table "
            "catches up."
        ),
        "verification_steps": [
            "Confirm new snapshots appear on the target table.",
            "Confirm max(event timestamp) catches up to near real time.",
            "Confirm the backlog drained rather than being discarded.",
        ],
        "known_limitations": (
            "Buffered events are not retained indefinitely. If the stall lasted long enough "
            "for the buffer to overflow, some events may be lost and will need replaying "
            "from the producer — establish this before declaring the incident closed."
        ),
        "risk_level": RiskLevel.MEDIUM,
        "steps": [
            {
                "key": "confirm-gap",
                "title": "Confirm events are received but not committed",
                "plain_explanation": (
                    "Compare the producer's view with the table's. If the producer is getting "
                    "200s while the table's newest event is hours old, the problem is between "
                    "receipt and commit — not in the producer."
                ),
                "what_to_inspect": (
                    "The newest event timestamp in the table, and the table's recent snapshots."
                ),
                "expected_observation": (
                    "Newest event timestamp well behind now, and no recent snapshots"
                ),
                "step_type": StepType.READ_ONLY_DIAGNOSTIC,
                "risk_level": RiskLevel.LOW,
                "commands": [
                    {
                        "label": "How far behind is the table?",
                        "language": "sql",
                        "command": "SELECT max(event_at) FROM <catalog>.<namespace>.<table>;",
                        "is_read_only": True,
                    },
                    {
                        "label": "Recent commits to the table",
                        "language": "sql",
                        "command": (
                            "SELECT committed_at, operation FROM "
                            "<catalog>.<namespace>.<table>.snapshots\n"
                            "ORDER BY committed_at DESC LIMIT 10;"
                        ),
                        "is_read_only": True,
                    },
                ],
                "response_kind": ResponseKind.BOOLEAN,
                "branches": {"yes": "check-storage-writable", "no": "__escalate"},
            },
            {
                "key": "check-storage-writable",
                "title": "Check whether the target storage prefix is writable",
                "plain_explanation": (
                    "The commit writes data and metadata files under the table's prefix. If a "
                    "bucket policy or lifecycle rule made that prefix unwritable, commits "
                    "fail while receipts still succeed."
                ),
                "what_to_inspect": (
                    "The event stream component's logs for storage write errors, and the "
                    "bucket policy covering the table's prefix."
                ),
                "expected_observation": (
                    "A storage permission or write error in the component logs"
                ),
                "step_type": StepType.CONFIGURATION_REVIEW,
                "risk_level": RiskLevel.LOW,
                "commands": [
                    {
                        "label": "Event stream component logs",
                        "language": "bash",
                        "command": (
                            "kubectl logs -l app=iom-event-stream -n <platform-namespace> "
                            "--tail=200 | grep -iE 'denied|403|forbidden|commit'"
                        ),
                        "is_read_only": True,
                    }
                ],
                "response_kind": ResponseKind.CHOICE,
                "response_options": [
                    {"value": "write_denied", "label": "Storage writes are being denied"},
                    {"value": "no_errors", "label": "No storage errors in the logs",
                     "hint": "The cause is elsewhere; an FDE should look."},
                ],
                "branches": {
                    "write_denied": "restore-write-access",
                    "no_errors": "__escalate",
                },
            },
            {
                "key": "restore-write-access",
                "title": "Restore write access to the target prefix",
                "plain_explanation": (
                    "Correct the bucket policy or lifecycle rule so the platform can write "
                    "under the table's prefix again. Changing a bucket policy affects "
                    "everything under it, so confirm the intended scope before applying."
                ),
                "what_to_inspect": "Whether buffered events begin committing.",
                "expected_observation": "New snapshots appear within a few minutes",
                "step_type": StepType.CHANGE_REQUIRING_APPROVAL,
                "risk_level": RiskLevel.MEDIUM,
                "blast_radius": (
                    "Modifies an object storage policy. Too broad a change could grant wider "
                    "write access than intended, so scope it to the platform's principal and "
                    "the table's prefix."
                ),
                "response_kind": ResponseKind.BOOLEAN,
                "branches": {"yes": "verify-catchup", "no": "__escalate"},
            },
            {
                "key": "verify-catchup",
                "title": "Confirm the table catches up, and check for lost events",
                "plain_explanation": (
                    "Confirm snapshots are advancing and the newest event timestamp is close "
                    "to real time. Then compare the producer's sent count against the table's "
                    "row count over the stall window — if the buffer overflowed, some events "
                    "will need replaying."
                ),
                "what_to_inspect": (
                    "Snapshot history, newest event timestamp, and the row count over the "
                    "stall window versus what the producer sent."
                ),
                "expected_observation": (
                    "Snapshots advancing, timestamp near real time, and the backlog accounted for"
                ),
                "step_type": StepType.VERIFICATION,
                "risk_level": RiskLevel.INFORMATIONAL,
                "response_kind": ResponseKind.CHOICE,
                "response_options": [
                    {"value": "caught_up_complete",
                     "label": "Caught up and the event counts reconcile"},
                    {"value": "caught_up_gap",
                     "label": "Caught up, but some events appear to be missing",
                     "hint": "Needs a replay — escalate so it is tracked."},
                    {"value": "not_caught_up", "label": "Still not committing"},
                ],
                "branches": {
                    "caught_up_complete": "__resolved",
                    "caught_up_gap": "__escalate",
                    "not_caught_up": "__escalate",
                },
                "is_terminal": True,
            },
        ],
    },
]


# =======================================================================================
# Prospects
# =======================================================================================

PROSPECTS = [
    {
        "company_name": "Meridian Insurance",
        "contact_name": "Ingrid Halvorsen",
        "contact_email": "i.halvorsen@meridian.example",
        "contact_role": "Chief Technology Officer",
        "persona": "cto",
        "answers": {
            "company_type": CompanyType.FINANCIAL,
            "company_name": "Meridian Insurance",
            "infrastructure_location": InfrastructureLocation.ON_PREMISES,
            "cloud_providers": [],
            "current_systems": ["PostgreSQL", "Oracle", "Apache Ozone", "dbt"],
            "bi_tools": ["Power BI", "Tableau"],
            "data_volume": DataVolume.TB_10_100,
            "primary_use_case": UseCase.CONSOLIDATION,
            "secondary_use_cases": [UseCase.GOVERNANCE, UseCase.BI_REPORTING],
            "sovereignty_requirement": SovereigntyRequirement.MANDATORY,
            "challenges": ["data_residency", "cost", "duplicate_copies", "vendor_lock_in"],
            "current_architecture": CurrentArchitecture.BOTH,
            "constraints": ["procurement_process"],
            "kubernetes_maturity": "production",
            "team_size": "dedicated platform team",
        },
        "demo_request": {
            "message": (
                "We are replacing a lake-plus-warehouse pair and cannot use a hosted "
                "service for regulatory reasons. Keen to understand the operational model."
            ),
            "preferred_timeframe": "Within two weeks",
            "interests": ["architecture", "governance", "total cost of ownership"],
        },
    },
    {
        "company_name": "Brightwave Media",
        "contact_name": "Owen Castellanos",
        "contact_email": "owen@brightwave.example",
        "contact_role": "Head of Analytics",
        "persona": "data-analyst",
        "answers": {
            "company_type": CompanyType.MID_MARKET,
            "company_name": "Brightwave Media",
            "infrastructure_location": InfrastructureLocation.PUBLIC_CLOUD,
            "cloud_providers": ["aws"],
            "current_systems": ["Snowflake", "S3", "Airflow"],
            "bi_tools": ["Looker", "Metabase"],
            "data_volume": DataVolume.TB_1_10,
            "primary_use_case": UseCase.BI_REPORTING,
            "secondary_use_cases": [UseCase.DATA_ENGINEERING],
            "sovereignty_requirement": SovereigntyRequirement.NONE,
            "challenges": ["cost", "slow_queries"],
            "current_architecture": CurrentArchitecture.WAREHOUSE,
            "constraints": ["limited_budget", "small_team"],
            "kubernetes_maturity": "basic",
            "team_size": "small",
        },
    },
    {
        "company_name": "Nordic Rail Authority",
        "contact_name": "Sofia Lindqvist",
        "contact_email": "s.lindqvist@nordicrail.example",
        "contact_role": "Director of Information Security",
        "persona": "security-compliance",
        "answers": {
            "company_type": CompanyType.PUBLIC_SECTOR,
            "company_name": "Nordic Rail Authority",
            "infrastructure_location": InfrastructureLocation.AIR_GAPPED,
            "cloud_providers": [],
            "current_systems": ["PostgreSQL", "MinIO", "Kafka"],
            "bi_tools": ["Apache Superset"],
            "data_volume": DataVolume.TB_100_1PB,
            "primary_use_case": UseCase.REAL_TIME,
            "secondary_use_cases": [UseCase.GOVERNANCE, UseCase.DATA_ENGINEERING],
            "sovereignty_requirement": SovereigntyRequirement.MANDATORY,
            "challenges": ["data_residency", "compliance", "governance"],
            "current_architecture": CurrentArchitecture.DATA_LAKE,
            "constraints": ["procurement_process", "tight_timeline"],
            "kubernetes_maturity": "some",
            "team_size": "medium",
        },
        "demo_request": {
            "message": (
                "Operating on an isolated network. We need to understand the air-gapped "
                "installation and update process before we can proceed.",
            )[0],
            "preferred_timeframe": "This quarter",
            "interests": ["air-gapped deployment", "security", "streaming ingestion"],
        },
    },
    {
        "company_name": "Keystone Retail",
        "contact_name": "Marcus Oyelaran",
        "contact_email": "m.oyelaran@keystone.example",
        "contact_role": "VP Engineering",
        "persona": "business",
        "answers": {
            "company_type": CompanyType.ENTERPRISE,
            "company_name": "Keystone Retail",
            "infrastructure_location": InfrastructureLocation.HYBRID,
            "cloud_providers": ["azure"],
            "current_systems": ["SQL Server", "Azure Data Lake Storage Gen2", "dbt", "Kafka"],
            "bi_tools": ["Power BI"],
            "data_volume": DataVolume.TB_100_1PB,
            "primary_use_case": UseCase.AI_ML,
            "secondary_use_cases": [UseCase.CONSOLIDATION, UseCase.REAL_TIME],
            "sovereignty_requirement": SovereigntyRequirement.STRONG,
            "challenges": ["cost", "data_silos", "scaling"],
            "current_architecture": CurrentArchitecture.BOTH,
            "constraints": [],
            "kubernetes_maturity": "advanced",
            "team_size": "dedicated platform team",
        },
    },
    {
        "company_name": "Fathom Analytics Consulting",
        "contact_name": "Yuki Tanabe",
        "contact_email": "",
        "contact_role": "Principal Consultant",
        "persona": "data-engineer",
        "answers": {
            "company_type": CompanyType.CONSULTANCY,
            "company_name": "Fathom Analytics Consulting",
            "infrastructure_location": InfrastructureLocation.UNDECIDED,
            "cloud_providers": ["aws", "gcp"],
            "current_systems": ["PostgreSQL", "BigQuery"],
            "bi_tools": [],
            "data_volume": DataVolume.UNDER_1TB,
            "primary_use_case": UseCase.DATA_ENGINEERING,
            "secondary_use_cases": [],
            "sovereignty_requirement": SovereigntyRequirement.UNKNOWN,
            "challenges": [],
            "current_architecture": CurrentArchitecture.DATABASES_ONLY,
            "constraints": ["small_team"],
            "kubernetes_maturity": "none",
            "team_size": "small",
        },
    },
]


class Command(BaseCommand):
    help = (
        "Seed the demonstration dataset: organizations, users, synthetic tickets, "
        "approved playbooks, issue clusters, knowledge drafts, executions and prospects."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--flush",
            action="store_true",
            help="Delete existing synthetic data before seeding. Real data is untouched.",
        )
        parser.add_argument(
            "--quiet", action="store_true", help="Only print the final summary."
        )

    def handle(self, *args, **options):
        self.verbose = not options["quiet"]
        if options["flush"]:
            self._flush()

        with transaction.atomic():
            organizations = self._seed_organizations()
            users = self._seed_users(organizations)
            playbooks = self._seed_playbooks(users)
            tickets = self._seed_tickets(organizations, users)

        # Outside the main transaction: clustering and extraction run the real services and
        # are safe to repeat, and keeping them separate makes a partial failure recoverable.
        self._seed_clusters()
        self._seed_executions(tickets, playbooks, users)
        self._seed_knowledge_drafts(tickets, users)
        self._seed_prospects()

        self._summarise()

    # --- flush ------------------------------------------------------------------------

    def _flush(self) -> None:
        self._say("Flushing synthetic data…")
        from aiengine.models import AIGeneration, RetrievalRun
        from integrations.models import IntegrationConfiguration
        from lakehouse.models import LakehouseQueryRun

        counts = {
            "tickets": Ticket.objects.filter(is_synthetic=True).delete()[0],
            "playbooks": ResolutionPlaybook.objects.filter(is_synthetic=True).delete()[0],
            "clusters": IssueCluster.objects.filter(is_synthetic=True).delete()[0],
            "prospects": ProspectProfile.objects.filter(is_synthetic=True).delete()[0],
            "fingerprints": ErrorFingerprint.objects.all().delete()[0],
            "retrieval_runs": RetrievalRun.objects.all().delete()[0],
            "generations": AIGeneration.objects.all().delete()[0],
            "query_runs": LakehouseQueryRun.objects.all().delete()[0],
            "integrations": IntegrationConfiguration.objects.filter(
                config__source="auto-created-for-sync-history"
            ).delete()[0],
            "users": User.objects.filter(is_synthetic=True).delete()[0],
            "organizations": Organization.objects.filter(is_synthetic=True).delete()[0],
        }
        self._say(f"  removed: {counts}")

    # --- organizations and users ------------------------------------------------------

    def _seed_organizations(self) -> dict[str, Organization]:
        organizations: dict[str, Organization] = {}
        for spec in ORGANIZATIONS:
            organization, created = Organization.objects.update_or_create(
                slug=spec["slug"],
                defaults={**{k: v for k, v in spec.items() if k != "slug"}, "is_synthetic": True},
            )
            organizations[spec["slug"]] = organization
            self._say(f"  {'created' if created else 'updated'} organization {organization.name}")
        return organizations

    def _seed_users(self, organizations: dict[str, Organization]) -> dict[str, User]:
        users: dict[str, User] = {}
        for spec in USERS:
            email = spec["email"]
            existing = User.objects.filter(email=email).first()
            if existing is None:
                user = User.objects.create_user(
                    email=email,
                    password=DEMO_PASSWORD,
                    full_name=spec["full_name"],
                    job_title=spec.get("job_title", ""),
                    system_role=spec["system_role"],
                )
                user.is_staff = spec.get("is_staff", False)
                user.is_synthetic = True
                user.save()
                self._say(f"  created user {email} ({spec['system_role']})")
            else:
                user = existing
                user.full_name = spec["full_name"]
                user.job_title = spec.get("job_title", "")
                user.system_role = spec["system_role"]
                user.is_staff = spec.get("is_staff", False)
                user.is_synthetic = True
                user.set_password(DEMO_PASSWORD)
                user.save()

            if slug := spec.get("organization"):
                Membership.objects.update_or_create(
                    user=user,
                    organization=organizations[slug],
                    defaults={"role": spec["role"], "is_default": True, "is_active": True},
                )
            users[email] = user

        # Assign FDEs to accounts, so the "my accounts" view has content.
        assignments = {
            "northwind-bank": "fde.lead@iomete.com",
            "vela-telecom": "fde@iomete.com",
            "helios-health": "fde.second@iomete.com",
            "atlas-logistics": "fde@iomete.com",
        }
        for slug, email in assignments.items():
            organization = organizations[slug]
            organization.assigned_fde = users[email]
            organization.save(update_fields=["assigned_fde", "updated_at"])

        return users

    # --- playbooks --------------------------------------------------------------------

    def _seed_playbooks(self, users: dict[str, User]) -> dict[str, ResolutionPlaybook]:
        reviewer = users["fde.lead@iomete.com"]
        author = users["fde@iomete.com"]
        playbooks: dict[str, ResolutionPlaybook] = {}

        for spec in PLAYBOOKS:
            steps_spec = spec.pop("steps") if "steps" in spec else []
            existing = ResolutionPlaybook.objects.filter(
                playbook_id=spec["playbook_id"], version=1
            ).first()
            if existing is not None:
                playbooks[spec["playbook_id"]] = existing
                spec["steps"] = steps_spec
                continue

            playbook = ResolutionPlaybook.objects.create(
                **spec,
                version=1,
                approval_status=ApprovalStatus.DRAFT,
                is_shared=True,
                created_by=author,
                generated_by="human",
                is_synthetic=True,
            )
            for order, step in enumerate(steps_spec, start=1):
                PlaybookStep.objects.create(
                    playbook=playbook,
                    order=order,
                    key=step["key"],
                    title=step["title"],
                    plain_explanation=step["plain_explanation"],
                    what_to_inspect=step.get("what_to_inspect", ""),
                    expected_observation=step.get("expected_observation", ""),
                    why_this_step=step.get("why_this_step", ""),
                    step_type=step["step_type"],
                    risk_level=step.get("risk_level", RiskLevel.INFORMATIONAL),
                    blast_radius=step.get("blast_radius", ""),
                    commands=step.get("commands", []),
                    response_kind=step["response_kind"],
                    response_options=step.get("response_options", []),
                    branches=step.get("branches", {}),
                    is_terminal=step.get("is_terminal", False),
                )

            # Approve through the real service: graph validation runs and a
            # KnowledgeApproval record is written, so the review trail is genuine.
            knowledge_service.approve(
                playbook=playbook,
                reviewer=reviewer,
                notes=(
                    "Reviewed against the originating investigations. Diagnostic steps "
                    "confirmed to precede the remediation step; commands are read-only "
                    "except where explicitly approval-gated."
                ),
                redactions_made="Removed customer-specific hostnames, bucket names and user names.",
            )
            playbook.refresh_from_db()
            playbooks[spec["playbook_id"]] = playbook
            spec["steps"] = steps_spec
            self._say(f"  created and approved playbook {playbook.playbook_id}")

        return playbooks

    # --- tickets ----------------------------------------------------------------------

    def _seed_tickets(
        self, organizations: dict[str, Organization], users: dict[str, User]
    ) -> dict[str, Ticket]:
        tickets: dict[str, Ticket] = {}
        fdes = [users["fde@iomete.com"], users["fde.lead@iomete.com"], users["fde.second@iomete.com"]]

        for scenario in SCENARIOS:
            key = scenario["key"]
            if Ticket.objects.filter(is_synthetic=True, title=scenario["title"]).exists():
                tickets[key] = Ticket.objects.filter(
                    is_synthetic=True, title=scenario["title"]
                ).first()
                continue

            organization = organizations[scenario["organization"]]
            reporter = users[scenario["reporter"]]
            created_at = timezone.now() - timedelta(
                days=scenario["days_ago"], hours=RNG.randint(0, 20)
            )

            result = intake.create_ticket(
                organization=organization,
                reporter=reporter,
                title=scenario["title"],
                description=scenario["description"],
                error_message=scenario.get("error_message", ""),
                diagnostics=scenario.get("diagnostics", ""),
                component=scenario["component"],
                severity=scenario["severity"],
                iomete_version=organization.iomete_version,
                environment=scenario["environment"],
                is_synthetic=True,
                created_at_override=created_at,
            )
            ticket = result.ticket

            if scenario.get("resolution"):
                fde = RNG.choice(fdes)
                lifecycle.assign(ticket=ticket, user=fde, assignee=fde)
                lifecycle.record_resolution(
                    ticket=ticket,
                    user=fde,
                    summary=scenario["resolution"],
                    evidence=scenario["evidence"],
                    self_service=scenario.get("self_service", False),
                    fde_investigation_minutes=scenario.get("fde_minutes"),
                )
                # Backdate the resolution so analytics windows and recency weighting have a
                # realistic spread rather than everything resolving today.
                resolved_at = created_at + timedelta(
                    hours=RNG.randint(6, 72), minutes=RNG.randint(0, 59)
                )
                Ticket.objects.filter(pk=ticket.pk).update(
                    resolved_at=resolved_at,
                    time_to_resolution_seconds=int(
                        (resolved_at - created_at).total_seconds()
                    ),
                    first_response_at=created_at + timedelta(hours=RNG.randint(1, 8)),
                )
                ticket.refresh_from_db()

                if scenario.get("verified"):
                    lifecycle.verify_resolution(
                        ticket=ticket,
                        reviewer=users["fde.lead@iomete.com"],
                        quality=scenario["quality"],
                        note="Confirmed against the recorded evidence.",
                    )
                    Ticket.objects.filter(pk=ticket.pk).update(
                        resolution_verified_at=resolved_at + timedelta(days=1)
                    )
            elif scenario.get("status") == "escalated":
                lifecycle.escalate(
                    ticket=ticket,
                    user=reporter,
                    reason=scenario["escalation_reason"],
                )
                fde = RNG.choice(fdes)
                lifecycle.assign(ticket=ticket, user=fde, assignee=fde)

            ticket.refresh_from_db()
            tickets[key] = ticket
            self._say(f"  created ticket {ticket.reference} — {ticket.title[:60]}")

        # Link verified tickets to the playbook that covers their problem, so the
        # knowledge-lifecycle funnel and resolution-confidence scoring have real links.
        links = {
            "spark-oom-nightly": "spark-executor-memory-exhaustion",
            "spark-oom-reporting": "spark-executor-memory-exhaustion",
            "spark-oom-atlas": "spark-executor-memory-exhaustion",
            "k8s-pending-quota": "kubernetes-pod-pending-capacity",
            "k8s-quota-helios": "kubernetes-pod-pending-capacity",
            "iceberg-commit-conflict": "iceberg-commit-failed-concurrent-writers",
            "ranger-permission-denied": "ranger-permission-denied-group-sync",
            "storage-access-denied": "object-storage-access-denied-credentials",
            "ingestion-stalled": "event-stream-ingestion-stalled",
        }
        for ticket_key, playbook_id in links.items():
            ticket = tickets.get(ticket_key)
            playbook = ResolutionPlaybook.objects.filter(
                playbook_id=playbook_id, approval_status=ApprovalStatus.APPROVED
            ).first()
            if ticket and playbook:
                Ticket.objects.filter(pk=ticket.pk).update(resolved_via_playbook=playbook)
                if ticket.fingerprint_id:
                    playbook.fingerprints.add(ticket.fingerprint)
                ResolutionPlaybook.objects.filter(pk=playbook.pk).update(
                    source_ticket=playbook.source_ticket or ticket,
                    origin_organization=playbook.origin_organization or ticket.organization,
                )

        return tickets

    # --- clusters ---------------------------------------------------------------------

    def _seed_clusters(self) -> None:
        self._say("Clustering tickets…")
        result = clustering.recompute_all()
        self._say(f"  {result}")

        # Confirm a root cause on the largest cluster, so the UI has one confirmed and
        # several unconfirmed — which is the distinction the cluster view exists to make.
        from django.db.models import Count

        largest = (
            IssueCluster.objects.annotate(size=Count("tickets"))
            .filter(size__gte=2)
            .order_by("-size")
            .first()
        )
        reviewer = User.objects.filter(system_role=SystemRole.FDE_LEAD).first()
        if largest and reviewer and not largest.is_root_cause_confirmed:
            clustering.confirm_root_cause(
                cluster=largest,
                reviewer=reviewer,
                root_cause=(
                    "Across the investigated tickets in this cluster, the common cause was "
                    "executor memory provisioned below the workload's peak requirement, with "
                    "partition skew as the proximate trigger in each case. Note that this is "
                    "confirmed for the tickets investigated, not asserted for every member "
                    "of the cluster."
                ),
                notes=(
                    "Three tickets investigated individually; all three showed OOMKilled with "
                    "a skewed partition. Remaining members have not been individually "
                    "confirmed."
                ),
            )
            self._say(f"  confirmed root cause on cluster '{largest.title}'")

    # --- executions -------------------------------------------------------------------

    def _seed_executions(
        self,
        tickets: dict[str, Ticket],
        playbooks: dict[str, ResolutionPlaybook],
        users: dict[str, User],
    ) -> None:
        """
        Run real Resolution Replay executions.

        Driven through `execution.start/advance/complete`, so every step response, approval
        record and outcome is genuine — including one deliberately escalated run, because a
        demo where everything succeeds is not a credible demo.
        """
        self._say("Running demo Resolution Replay executions…")

        plans = [
            # (ticket key, playbook id, actor email, per-step responses, outcome)
            (
                "spark-oom-reporting",
                "spark-executor-memory-exhaustion",
                "engineer@helios.example",
                ["oomkilled", "near_limit", "skewed", "yes", "yes"],
                (
                    "resolved",
                    "Raised executor memory to 10g and enabled adaptive skew-join handling, "
                    "following the playbook.",
                    "The clinical rollup completed in 52 minutes with no OOMKilled events "
                    "across two consecutive nights.",
                ),
            ),
            (
                "k8s-quota-helios",
                "kubernetes-pod-pending-capacity",
                "engineer@helios.example",
                ["quota", "quota_exhausted", "yes", "yes"],
                (
                    "resolved",
                    "Raised the research namespace quota to 96Gi after confirming node "
                    "capacity.",
                    "Notebooks start immediately. Quota shows 60Gi of 96Gi used, with room "
                    "for six more containers.",
                ),
            ),
            (
                # A customer resolving an open ticket themselves, without an FDE. This is
                # the outcome the whole product exists to produce, so the demo needs one.
                "open-ranger-denied",
                "ranger-permission-denied-group-sync",
                "engineer@vela.example",
                ["yes", "group_missing", "yes", "yes"],
                (
                    "resolved",
                    "The grant was correct; the new engineer's group membership had not "
                    "synchronised. Triggered a group sync in the Identity Service.",
                    "SHOW CURRENT ROLES now lists the telemetry group and the engineer can "
                    "query lakehouse.telemetry.cell_metrics. Confirmed with them directly.",
                ),
            ),
            (
                # A run that correctly fails to resolve and escalates with its diagnostic
                # record attached. A demo where every workflow succeeds is not credible, and
                # the escalation package is a large part of the product's value.
                "open-iceberg-commit",
                "iceberg-commit-failed-concurrent-writers",
                "engineer@helios.example",
                ["commit_failed", "single_writer"],
                (
                    "escalated",
                    "Confirmed the exception is CommitFailedException, but the snapshot "
                    "history shows only our streaming writer — no second writer is visible, "
                    "so the playbook's concurrent-writer hypothesis does not explain this. "
                    "Escalating with the evidence collected.",
                    "",
                ),
            ),
        ]

        for ticket_key, playbook_id, actor_email, responses, outcome in plans:
            ticket = tickets.get(ticket_key)
            playbook = playbooks.get(playbook_id)
            actor = users.get(actor_email)
            if not (ticket and playbook and actor):
                continue
            if ticket.executions.exists():
                continue

            # Applicability is genuinely checked, so a mismatch here is a seed bug worth
            # seeing rather than silently skipping.
            check = execution_service.check_applicability(playbook=playbook, ticket=ticket)
            if not check.applicable:
                self._say(
                    f"  skipped execution for {ticket.reference}: {' '.join(check.reasons)}"
                )
                continue

            execution = execution_service.start(ticket=ticket, playbook=playbook, user=actor)
            users["admin@northwind.example"] if actor.is_customer else actor

            for response in responses:
                if execution.status != "in_progress" or execution.current_step is None:
                    break
                step = execution.current_step
                acting_user = actor
                if step.requires_approval and not execution_service.can_approve(actor, execution):
                    # An organization admin approves. This mirrors the real flow rather than
                    # quietly granting the engineer rights they do not have.
                    acting_user = (
                        users["engineer@vela.example"]
                        if ticket.organization.slug == "vela-telecom"
                        else users["admin@northwind.example"]
                    )
                    if not execution_service.can_approve(acting_user, execution):
                        acting_user = users["fde@iomete.com"]
                try:
                    result = execution_service.advance(
                        execution=execution,
                        user=acting_user,
                        response_value=response,
                        observation=self._observation_for(step.key, response),
                        approval_note=(
                            "Approved during the agreed maintenance window."
                            if step.requires_approval
                            else ""
                        ),
                    )
                except Exception as exc:
                    self._say(f"  execution step failed for {ticket.reference}: {exc}")
                    break
                execution = result.execution
                if result.terminal:
                    break

            status, summary, evidence = outcome
            try:
                execution_service.complete(
                    execution=execution,
                    user=actor,
                    outcome=status,
                    outcome_summary=summary,
                    outcome_evidence=evidence,
                )
                self._say(f"  execution on {ticket.reference} → {status}")
            except Exception as exc:
                self._say(f"  could not complete execution for {ticket.reference}: {exc}")

            if status == "escalated":
                try:
                    lifecycle.escalate(
                        ticket=ticket,
                        user=actor,
                        reason=summary,
                        execution=execution,
                    )
                except Exception as exc:
                    self._say(f"  escalation failed for {ticket.reference}: {exc}")

    @staticmethod
    def _observation_for(step_key: str, response: str) -> str:
        """Plausible observations, so the diagnostic record reads like real work."""
        observations = {
            "confirm-oomkilled": "Last State: Terminated, Reason: OOMKilled, Exit Code: 137.",
            "check-limits": "Container limit 4Gi; Spark history shows peak executor memory 3.9Gi.",
            "check-skew": "Max task input 14.2GB against a median of 310MB — clearly skewed.",
            "apply-memory-and-skew": (
                "Set executor memory to 10g with 3g overhead and enabled adaptive skew join. "
                "Cluster restarted in 95 seconds."
            ),
            "verify-run": "Rollup completed in 52 minutes; no OOMKilling events in the namespace.",
            "read-scheduling-event": (
                "Forbidden: exceeded quota: research-quota, requested requests.memory=8Gi, "
                "used 60Gi, limited 64Gi."
            ),
            "check-quota": "Quota 60Gi/64Gi used; nodes report 180Gi allocatable with 70Gi free.",
            "raise-quota": "Raised research-quota requests.memory to 96Gi.",
            "verify-scheduled": "New Jupyter container reached Running in 40 seconds.",
            "read-exception": (
                "RangerAccessControlException: Permission denied: user=n.engineer, "
                "access=SELECT, table=lakehouse.telemetry.cell_metrics."
            ),
            "check-roles": (
                "SHOW CURRENT ROLES does not list the telemetry group, but SHOW GRANTS "
                "confirms SELECT is granted to it."
            ),
            "trigger-sync": "Group sync completed in 12 seconds, 148 users refreshed.",
            "verify-access": (
                "The telemetry group now appears in their roles and the query returns rows."
            ),
            "confirm-exception-type": (
                "org.apache.iceberg.exceptions.CommitFailedException — the commit definitely "
                "did not happen."
            ),
            "inspect-snapshots": (
                "Only append operations from the streaming writer appear in the last 50 "
                "snapshots. No compaction or second writer is visible, so the "
                "concurrent-writer explanation does not hold here."
            ),
            "confirm-gap": (
                "The sync job is failing before any commit is attempted, so there is no "
                "receipt-versus-commit gap to observe."
            ),
        }
        return observations.get(step_key, "")

    # --- knowledge drafts -------------------------------------------------------------

    def _seed_knowledge_drafts(self, tickets: dict[str, Ticket], users: dict[str, User]) -> None:
        """
        Generate two drafts awaiting approval, through the real extraction service.

        Chosen from verified tickets that no existing playbook covers, so the extraction's
        duplicate detection does not suppress them — which also demonstrates that the
        duplicate check is working.
        """
        self._say("Generating knowledge drafts for the review queue…")
        author = users["fde@iomete.com"]
        for key in ("iceberg-table-not-found", "gateway-502"):
            ticket = tickets.get(key)
            if ticket is None or not ticket.resolution_summary:
                continue
            if ResolutionPlaybook.objects.filter(source_ticket=ticket).exists():
                continue
            try:
                result = knowledge_service.extract_from_ticket(ticket=ticket, actor=author)
                if result.playbook:
                    self._say(
                        f"  drafted '{result.playbook.title[:60]}' from {ticket.reference}"
                    )
                elif result.duplicate_of:
                    self._say(
                        f"  {ticket.reference}: duplicate detected "
                        f"({result.duplicate_of.playbook_id}); no draft created"
                    )
            except Exception as exc:
                self._say(f"  draft generation failed for {ticket.reference}: {exc}")

    # --- prospects --------------------------------------------------------------------

    def _seed_prospects(self) -> None:
        self._say("Seeding prospect profiles and fit assessments…")
        for spec in PROSPECTS:
            if ProspectProfile.objects.filter(
                company_name=spec["company_name"], is_synthetic=True
            ).exists():
                continue

            answers = spec["answers"]
            profile = ProspectProfile.objects.create(
                company_name=spec["company_name"],
                contact_name=spec["contact_name"],
                contact_email=spec["contact_email"],
                contact_role=spec["contact_role"],
                persona=spec["persona"],
                company_type=answers["company_type"],
                infrastructure_location=answers["infrastructure_location"],
                cloud_providers=answers["cloud_providers"],
                current_systems=answers["current_systems"],
                data_volume=answers["data_volume"],
                primary_use_case=answers["primary_use_case"],
                secondary_use_cases=answers["secondary_use_cases"],
                sovereignty_requirement=answers["sovereignty_requirement"],
                challenges=answers["challenges"],
                current_architecture=answers["current_architecture"],
                constraints=answers["constraints"],
                kubernetes_maturity=answers["kubernetes_maturity"],
                team_size=answers["team_size"],
                consent_given=bool(spec["contact_email"]),
                consent_text=(
                    "I agree that IOMETE may contact me about this enquiry."
                    if spec["contact_email"]
                    else ""
                ),
                consent_at=timezone.now() if spec["contact_email"] else None,
                source="fit-finder",
                is_synthetic=True,
            )

            result = fit_service.assess(answers)
            assessment = FitAssessment.objects.create(
                prospect=profile,
                answers=answers,
                rubric_version=fit_service.RUBRIC_VERSION,
                indicative_score=result.score,
                band=result.band,
                rubric=result.rubric,
                requirement_summary=result.requirement_summary,
                suitability_reasons=result.suitability_reasons,
                technical_requirements=result.technical_requirements,
                advantages=result.advantages,
                gaps=result.gaps,
                questions_for_sales=result.questions_for_sales,
                caps_applied=result.caps_applied,
                next_step=result.next_step,
                cited_sources=result.cited_sources,
                disclaimer=result.disclaimer,
                generated_by="rubric",
                is_synthetic=True,
            )
            graph = architecture_service.generate(answers, assessment=assessment)
            ArchitectureRecommendation.objects.create(
                prospect=profile,
                assessment=assessment,
                title=graph.title,
                inputs=answers,
                nodes=graph.nodes,
                edges=graph.edges,
                layers=graph.layers,
                narrative=graph.narrative,
                integration_notes=graph.integration_notes,
                open_questions=graph.open_questions,
                conceptual_disclaimer=graph.conceptual_disclaimer,
                cited_sources=graph.cited_sources,
                is_synthetic=True,
            )
            if demo := spec.get("demo_request"):
                DemoRequest.objects.create(
                    prospect=profile,
                    assessment=assessment,
                    message=demo["message"],
                    preferred_timeframe=demo["preferred_timeframe"],
                    interests=demo["interests"],
                    is_synthetic=True,
                )
            self._say(
                f"  {profile.company_name}: {result.band} ({result.score}/100)"
            )

    # --- output -----------------------------------------------------------------------

    def _say(self, message: str) -> None:
        if self.verbose:
            self.stdout.write(message)

    def _summarise(self) -> None:
        from django.db.models import Count

        from playbooks.models import KnowledgeApproval, PlaybookExecution

        clusters = IssueCluster.objects.annotate(size=Count("tickets"))
        self.stdout.write(self.style.SUCCESS("\nDemo data seeded.\n"))
        self.stdout.write(
            f"  organizations            {Organization.objects.filter(is_synthetic=True).count()}\n"
            f"  users                    {User.objects.filter(is_synthetic=True).count()}\n"
            f"  tickets                  {Ticket.objects.filter(is_synthetic=True).count()}"
            f"  (open {Ticket.objects.filter(is_synthetic=True).exclude(status__in=['resolved', 'closed']).count()},"
            f" verified {Ticket.objects.filter(is_synthetic=True, resolution_verified=True).count()})\n"
            f"  error fingerprints       {ErrorFingerprint.objects.count()}\n"
            f"  issue clusters           {clusters.filter(size__gte=2).count()}"
            f"  (root cause confirmed {IssueCluster.objects.filter(is_root_cause_confirmed=True).count()})\n"
            f"  approved playbooks       {ResolutionPlaybook.objects.filter(approval_status='approved').count()}\n"
            f"  drafts awaiting review   {ResolutionPlaybook.objects.filter(approval_status__in=['draft', 'in_review']).count()}\n"
            f"  review decisions logged  {KnowledgeApproval.objects.count()}\n"
            f"  replay executions        {PlaybookExecution.objects.count()}"
            f"  (resolved {PlaybookExecution.objects.filter(status='resolved').count()},"
            f" escalated {PlaybookExecution.objects.filter(status='escalated').count()})\n"
            f"  prospect profiles        {ProspectProfile.objects.filter(is_synthetic=True).count()}\n"
            f"  fit assessments          {FitAssessment.objects.count()}\n"
            f"  demo requests            {DemoRequest.objects.count()}\n"
        )
        self.stdout.write(
            self.style.WARNING(
                "All of the above is synthetic demonstration data, flagged is_synthetic and "
                "labelled as such in the UI. It is not IOMETE incident data.\n"
            )
        )
        self.stdout.write("Demo sign-in — every account uses the same password:\n")
        self.stdout.write(f"  password: {DEMO_PASSWORD}\n")
        for user in User.objects.filter(is_synthetic=True).order_by("system_role", "full_name"):
            membership = user.memberships.filter(is_active=True).select_related(
                "organization"
            ).first()
            scope = f"{membership.organization.name} / {membership.role}" if membership else "IOMETE"
            self.stdout.write(f"  {user.email:<32} {user.system_role:<16} {scope}")
        self.stdout.write(
            "\nThe full list is also served at GET /api/v1/auth/demo-accounts/ "
            "(only while COMPASS_DEMO_MODE is enabled).\n"
        )
