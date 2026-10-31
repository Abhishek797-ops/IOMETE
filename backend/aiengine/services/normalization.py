"""
TicketNormalizationService.

Turns a free-text support submission into structured features that retrieval can actually
use: error codes, key phrases, symptoms, affected components, an extracted version, and a
*hypothesised* failure category.

This is deterministic pattern extraction, not an LLM call. Three reasons:

1. Retrieval features must be stable. If the same ticket normalises differently on Tuesday,
   similarity scores move for no reason and the system becomes unexplainable.
2. It has to work offline, with no API key, for the demo path to be honest.
3. An LLM adds nothing here. `OOMKilled` is a literal string; finding it is a regex, and a
   model that paraphrases it to "out of memory condition" actively destroys the exact-match
   signal that makes the fingerprint channel the strongest one we have.

The LLM's job is downstream: *explaining* a match and *drafting* knowledge, grounded in
these features. Not producing them.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from tickets.models import FailureCategory, TicketComponent

# ---------------------------------------------------------------------------------------
# Error code extraction
#
# Patterns are ordered from most to least specific. Each produces a canonical token that
# the fingerprint service hashes, so the canonical form must be stable: `OOMKilled` always
# normalises to `OOMKilled`, never `oomkilled` or `OOM killed`.
# ---------------------------------------------------------------------------------------

_JVM_EXCEPTION = re.compile(
    r"\b((?:org|com|java|javax|scala|io|net|sun)(?:\.[A-Za-z0-9_$]+){2,}"
    r"(?:Exception|Error|Throwable|Failure))\b"
)

_BARE_EXCEPTION = re.compile(
    r"\b([A-Z][A-Za-z0-9_]{2,}(?:Exception|Error|Failure|Timeout|Denied))\b"
)

#: Kubernetes container/pod states and scheduler reasons. Exact strings, exact casing.
_K8S_REASONS = (
    "OOMKilled", "CrashLoopBackOff", "ImagePullBackOff", "ErrImagePull", "Evicted",
    "FailedScheduling", "CreateContainerConfigError", "CreateContainerError",
    "ContainerCannotRun", "FailedMount", "FailedAttachVolume", "Unschedulable",
    "NodeNotReady", "DeadlineExceeded", "BackoffLimitExceeded", "InvalidImageName",
    "FailedCreatePodSandBox", "NetworkNotReady", "Preempted",
)
_K8S_PATTERN = re.compile(r"\b(" + "|".join(_K8S_REASONS) + r")\b")

#: Spark-specific failure markers.
_SPARK_MARKERS = (
    "ExecutorLostFailure", "SparkOutOfMemoryError", "TaskSetManager",
    "FetchFailedException", "ShuffleFetchFailedException", "SparkException",
    "ExecutorDeadException", "TooLargeFrameException", "SparkUpgradeException",
    "AnalysisException", "ParseException", "StreamingQueryException",
    "ExecutorAllocationManager", "BlockManagerMasterEndpoint",
)
_SPARK_PATTERN = re.compile(r"\b(" + "|".join(_SPARK_MARKERS) + r")\b")

#: Iceberg / catalog failures.
_ICEBERG_MARKERS = (
    "NoSuchTableException", "NoSuchNamespaceException", "CommitFailedException",
    "CommitStateUnknownException", "ValidationException", "AlreadyExistsException",
    "NotFoundException", "ForbiddenException", "BadRequestException",
    "TableAlreadyExistsException", "NoSuchIcebergTableException",
)
_ICEBERG_PATTERN = re.compile(r"\b(" + "|".join(_ICEBERG_MARKERS) + r")\b")

#: Access-control failures.
_AUTHZ_MARKERS = (
    "AccessControlException", "HiveAccessControlException", "AuthorizationException",
    "AccessDenied", "PermissionDenied", "RangerAccessControlException",
)
_AUTHZ_PATTERN = re.compile(r"\b(" + "|".join(_AUTHZ_MARKERS) + r")\b")

#: Storage / object-store failures.
_STORAGE_PATTERN = re.compile(
    r"\b(NoSuchBucket|NoSuchKey|SignatureDoesNotMatch|InvalidAccessKeyId|"
    r"RequestTimeTooSkewed|SlowDown|ServiceUnavailable|AmazonS3Exception|"
    r"S3Exception|AbfsRestOperationException|StorageException|UnknownHostException|"
    r"ConnectTimeoutException|SocketTimeoutException|SSLHandshakeException)\b"
)

#: Prose spellings that mean the same error as a canonical token.
#:
#: Cloud SDKs emit `AccessDenied` while humans — and the same services' own prose messages —
#: write "Access Denied". Both must reduce to one token, or two reports of an identical
#: failure fingerprint differently and the strongest retrieval channel silently stops
#: working. Canonicalising aliases is a large part of what normalisation is *for*.
_ALIASES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?i)\baccess[\s_-]denied\b"), "AccessDenied"),
    (re.compile(r"(?i)\bpermission[\s_-]denied\b"), "PermissionDenied"),
    (re.compile(r"(?i)\bout[\s_-]of[\s_-]memory\b"), "OutOfMemoryError"),
    (re.compile(r"(?i)\boom[\s_-]killed\b"), "OOMKilled"),
    (re.compile(r"(?i)\bcrash[\s_-]loop[\s_-]back[\s_-]?off\b"), "CrashLoopBackOff"),
    (re.compile(r"(?i)\bimage[\s_-]pull[\s_-]back[\s_-]?off\b"), "ImagePullBackOff"),
    (re.compile(r"(?i)\bfailed[\s_-]scheduling\b"), "FailedScheduling"),
    (re.compile(r"(?i)\bno[\s_-]such[\s_-]table\b"), "NoSuchTableException"),
    (re.compile(r"(?i)\bno[\s_-]such[\s_-]bucket\b"), "NoSuchBucket"),
    (re.compile(r"(?i)\bconnection[\s_-]refused\b"), "ConnectionRefused"),
    (re.compile(r"(?i)\bexceeded[\s_-]quota\b"), "QuotaExceeded"),
    (re.compile(r"(?i)\binsufficient[\s_-](?:memory|cpu)\b"), "InsufficientResources"),
)

_HTTP_STATUS = re.compile(r"\b(?:HTTP\s*)?(?:status(?:\s*code)?[:= ]\s*)?\b(4\d{2}|5\d{2})\b")
_SQLSTATE = re.compile(r"\bSQLSTATE[:\[ ]*([0-9A-Z]{5})\b")
_PG_FATAL = re.compile(r"\b(FATAL|PANIC):\s*([a-z][^\n\r.]{3,80})")
_EXIT_CODE = re.compile(r"\bexit(?:ed with)?\s*(?:code|status)\s*[:= ]?\s*(\d{1,3})\b", re.I)


def extract_error_codes(text: str) -> list[str]:
    """
    Extract canonical error tokens, de-duplicated, ordered by pattern specificity.

    Specificity order matters for the fingerprint: `OOMKilled` is a much better identity
    for a ticket than the generic `137` exit code that accompanies it.
    """
    if not text:
        return []

    found: list[str] = []

    def add(value: str) -> None:
        if value and value not in found:
            found.append(value)

    for pattern in (_K8S_PATTERN, _ICEBERG_PATTERN, _SPARK_PATTERN, _AUTHZ_PATTERN,
                    _STORAGE_PATTERN):
        for match in pattern.findall(text):
            add(match)

    for match in _JVM_EXCEPTION.findall(text):
        # Keep the simple class name: `org.apache.iceberg.exceptions.NoSuchTableException`
        # and a bare `NoSuchTableException` in another ticket must fingerprint alike.
        add(match.rsplit(".", 1)[-1])
        add(match)

    for match in _BARE_EXCEPTION.findall(text):
        add(match)

    # Canonicalise prose spellings last, so an explicit SDK token already found keeps its
    # position at the front of the list.
    for pattern, canonical in _ALIASES:
        if pattern.search(text):
            add(canonical)

    for code in _SQLSTATE.findall(text):
        add(f"SQLSTATE:{code}")
    for level, message in _PG_FATAL.findall(text):
        add(f"PG_{level}:{message.strip().lower().replace(' ', '_')[:40]}")
    for code in _EXIT_CODE.findall(text):
        add(f"EXIT:{code}")
    for code in _HTTP_STATUS.findall(text):
        if code in {"400", "401", "403", "404", "409", "429", "500", "502", "503", "504"}:
            add(f"HTTP:{code}")

    return found[:25]


# ---------------------------------------------------------------------------------------
# Symptom extraction
#
# Symptoms are the human-readable observations a person would describe. They form the
# overlap signal shown as match evidence ("both tickets report executors restarting"),
# which is what lets a user judge a match instead of trusting a number.
# ---------------------------------------------------------------------------------------

_SYMPTOM_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    # "worker" and "worker process" are how non-Spark-specialists describe an executor,
    # and they appear constantly in real submissions. Without these, two reports of the
    # same incident extract different symptoms and fail to cluster together.
    ("executor_restarting", re.compile(
        r"(?i)(?:executor|worker)s?(?:\s+process(?:es)?)?\s+"
        r"(?:(?:keep|keeps|are|is)\s+)?(?:being\s+)?"
        r"(?:restart|crash|die|dying|dead|lost|terminat|evict|kill|shut\s*(?:ting)?\s*down|"
        r"disappear)")),
    ("pod_restarting", re.compile(
        r"(?i)pod[s]?\s+(?:keep[s]?\s+)?(?:restart|crash|evict|terminat|pending)")),
    ("out_of_memory", re.compile(
        r"(?i)(out of memory|oom|memory (?:exhaust|limit|pressure)|heap space)")),
    ("job_failing", re.compile(r"(?i)(job|application|pipeline)[s]?\s+(?:is |are |keeps? )?fail")),
    ("query_failing", re.compile(r"(?i)quer(?:y|ies)\s+(?:is |are |keeps? )?(?:fail|error)")),
    ("query_slow", re.compile(
        r"(?i)(quer(?:y|ies)|dashboard|report)[s]?\s+(?:is |are |)(?:very |extremely |)"
        r"(?:slow|timing out|taking (?:too )?long|hang)")),
    ("timeout", re.compile(r"(?i)(time(?:d)? ?out|timeout|exceeded.{0,20}deadline)")),
    ("permission_denied", re.compile(
        r"(?i)(permission denied|access denied|not authori[sz]ed|forbidden|403)")),
    ("authentication_failure", re.compile(
        r"(?i)(auth(?:entication)? fail|invalid credential|login fail|token (?:expired|invalid)|401)")),
    ("table_not_found", re.compile(
        r"(?i)(table .{0,40}(?:not found|does not exist)|no such table|namespace .{0,30}not found)")),
    ("metadata_error", re.compile(
        r"(?i)(metadata (?:file|json).{0,30}(?:missing|not found|corrupt)|"
        r"commit (?:failed|conflict)|snapshot .{0,20}not found)")),
    ("connection_refused", re.compile(
        r"(?i)(connection refused|could not connect|unable to connect|connection reset|"
        r"unknown host|no route to host)")),
    ("storage_unreachable", re.compile(
        r"(?i)(bucket .{0,30}(?:not (?:found|accessible))|s3.{0,20}(?:error|denied|timeout)|"
        r"object stor(?:e|age).{0,20}(?:error|unreachable|denied))")),
    ("cluster_wont_start", re.compile(
        r"(?i)(cluster .{0,30}(?:won'?t|will not|fail(?:s|ed)? to) start|stuck in (?:pending|starting))")),
    ("scheduling_failure", re.compile(
        r"(?i)(insufficient (?:cpu|memory|resources)|no nodes available|"
        r"failed ?scheduling|unschedulable|quota exceeded)")),
    ("data_missing", re.compile(
        r"(?i)(rows? (?:are )?missing|data (?:is )?missing|empty result|no (?:rows|data) returned)")),
    ("schema_mismatch", re.compile(
        r"(?i)(schema (?:mismatch|evolution|incompatib)|column .{0,30}(?:type|not found)|"
        r"cannot cast)")),
    # Intervening auxiliary words ("ingestion *has* stalled", "ingestion *is* failing") are
    # the norm in how people actually write these reports, so the gap is explicit.
    ("ingestion_stalled", re.compile(
        r"(?i)(ingest(?:ion)?\s+(?:\w+\s+){0,2}(?:stall|stopp|fail|lag|behind)|"
        r"stream\s+.{0,20}(?:behind|lag|stall)|no new (?:events|records|rows|data))")),
    ("upgrade_failure", re.compile(
        r"(?i)(upgrade (?:fail|stuck)|helm .{0,20}(?:fail|timeout)|migration (?:fail|stuck))")),
    ("notebook_failure", re.compile(
        r"(?i)(notebook|jupyter|kernel).{0,30}(?:fail|crash|disconnect|won'?t start)")),
    ("ui_unreachable", re.compile(
        r"(?i)(console|ui|web ?interface).{0,25}(?:unreachable|not loading|502|504|blank)")),
)


def extract_symptoms(text: str) -> list[str]:
    return [name for name, pattern in _SYMPTOM_RULES if pattern.search(text or "")]


SYMPTOM_LABELS = {
    "executor_restarting": "Spark executors restarting or being lost",
    "pod_restarting": "Pods restarting, pending or being evicted",
    "out_of_memory": "Memory exhaustion",
    "job_failing": "Jobs or applications failing",
    "query_failing": "Queries failing",
    "query_slow": "Queries or dashboards unusually slow",
    "timeout": "Operations timing out",
    "permission_denied": "Permission or authorization denied",
    "authentication_failure": "Authentication failing",
    "table_not_found": "Table or namespace not found",
    "metadata_error": "Iceberg metadata or commit problem",
    "connection_refused": "Connection refused or unreachable host",
    "storage_unreachable": "Object storage unreachable or rejecting requests",
    "cluster_wont_start": "Compute cluster will not start",
    "scheduling_failure": "Kubernetes cannot schedule the workload",
    "data_missing": "Expected data missing from results",
    "schema_mismatch": "Schema or column type mismatch",
    "ingestion_stalled": "Ingestion or streaming stalled",
    "upgrade_failure": "Installation or upgrade failure",
    "notebook_failure": "Notebook or kernel failure",
    "ui_unreachable": "Console or UI unreachable",
}


def symptom_label(key: str) -> str:
    return SYMPTOM_LABELS.get(key, key.replace("_", " ").capitalize())


# ---------------------------------------------------------------------------------------
# Component and category inference
# ---------------------------------------------------------------------------------------

_COMPONENT_SIGNALS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (TicketComponent.SPARK_COMPUTE, (
        "executor", "driver", "spark.executor", "compute cluster", "dynamic allocation",
        "shuffle", "spark connect", "sparkcontext", "hiveserver2")),
    (TicketComponent.SPARK_JOBS, (
        "spark job", "streaming job", "job template", "prefect", "orchestrat",
        "structured streaming", "scheduled job", "pyspark job")),
    (TicketComponent.KUBERNETES, (
        "kubernetes", "kubectl", "k8s", "node", "namespace", "pod", "helm", "quota",
        "taint", "toleration", "nodeselector", "priorityclass", "karpenter", "autoscaler")),
    (TicketComponent.ICEBERG_METADATA, (
        "iceberg", "metadata.json", "snapshot", "manifest", "partition evolution",
        "time travel", "rollback", "compaction", "copy-on-write")),
    (TicketComponent.ICEBERG_CATALOG, (
        "rest catalog", "iceberg rest", "catalog api", "namespace", "warehouse location")),
    (TicketComponent.SQL_SERVICE, (
        "sql editor", "worksheet", "query history", "explain plan", "iom-sql",
        "query monitoring", "dashboard")),
    (TicketComponent.PERMISSIONS, (
        "ranger", "policy", "row-level", "column-level", "masking", "access control",
        "tag-based", "grant", "revoke", "ras")),
    (TicketComponent.IDENTITY_SSO, (
        "ldap", "saml", "oidc", "sso", "identity service", "iom-identity", "login",
        "single sign-on", "group sync")),
    (TicketComponent.DATA_INGESTION, (
        "event stream", "papyrus", "ingest", "kafka", "kinesis", "pulsar", "http post",
        "jdbc sync")),
    (TicketComponent.OBJECT_STORAGE, (
        "s3", "s3a", "minio", "ozone", "gcs", "abfs", "wasbs", "bucket", "object storage",
        "dell ecs", "storage account", "access key")),
    (TicketComponent.CATALOG_SEARCH, (
        "data catalog", "typesense", "catalog search", "lineage", "classification tag")),
    (TicketComponent.GATEWAY_NETWORK, (
        "gateway", "ingress", "nginx", "grpc", "websocket", "tls", "certificate",
        "arrow flight", "502", "504", "network policy")),
    (TicketComponent.JUPYTER, ("jupyter", "notebook", "jupyterlab", "kernel")),
    (TicketComponent.PLATFORM_METADATA, (
        "postgres", "postgresql", "hive metastore", "metastore", "pgbouncer",
        "advisory lock", "iomete_")),
    (TicketComponent.UPGRADE, (
        "upgrade", "helm install", "data-plane-init", "migration", "release", "rollback deploy")),
)


def infer_component(text: str, declared: str | None = None) -> str:
    """
    Infer the affected component.

    A declared component from the submitter wins unless it is `OTHER` — people know their
    own system better than a keyword table does, and overriding them produces the "the
    form ignored what I said" experience.
    """
    if declared and declared != TicketComponent.OTHER:
        return declared

    lowered = (text or "").lower()
    scores: dict[str, int] = {}
    for component, signals in _COMPONENT_SIGNALS:
        hits = sum(1 for signal in signals if signal in lowered)
        if hits:
            scores[component] = hits
    if not scores:
        return declared or TicketComponent.OTHER
    return max(scores.items(), key=lambda kv: kv[1])[0]


def component_scores(text: str) -> dict[str, int]:
    """All matching components with their signal counts — the 'affected components' list."""
    lowered = (text or "").lower()
    return {
        component: hits
        for component, signals in _COMPONENT_SIGNALS
        if (hits := sum(1 for signal in signals if signal in lowered)) > 0
    }


_CATEGORY_RULES: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    # (category, error-code markers, symptom keys)
    (FailureCategory.RESOURCE_EXHAUSTION,
     ("OOMKilled", "SparkOutOfMemoryError", "OutOfMemoryError", "EXIT:137", "Evicted"),
     ("out_of_memory", "executor_restarting", "pod_restarting")),
    (FailureCategory.CAPACITY_LIMIT,
     ("FailedScheduling", "Unschedulable", "SlowDown", "HTTP:429"),
     ("scheduling_failure",)),
    (FailureCategory.PERMISSION_DENIED,
     ("AccessControlException", "HiveAccessControlException", "AccessDenied",
      "PermissionDenied", "ForbiddenException", "HTTP:403"),
     ("permission_denied",)),
    (FailureCategory.AUTHENTICATION,
     ("HTTP:401", "InvalidAccessKeyId", "SignatureDoesNotMatch"),
     ("authentication_failure",)),
    (FailureCategory.METADATA_INCONSISTENCY,
     ("NoSuchTableException", "CommitFailedException", "CommitStateUnknownException",
      "NoSuchNamespaceException", "ValidationException", "NotFoundException"),
     ("table_not_found", "metadata_error")),
    (FailureCategory.CONNECTIVITY,
     ("UnknownHostException", "ConnectTimeoutException", "SocketTimeoutException",
      "SSLHandshakeException", "NoSuchBucket", "HTTP:502", "HTTP:504", "ServiceUnavailable"),
     ("connection_refused", "storage_unreachable", "ui_unreachable")),
    (FailureCategory.CONFIGURATION_ERROR,
     ("CreateContainerConfigError", "InvalidImageName", "ErrImagePull",
      "ImagePullBackOff", "FailedMount"),
     ("cluster_wont_start",)),
    (FailureCategory.VERSION_INCOMPATIBILITY,
     ("SparkUpgradeException", "NoSuchMethodError", "ClassNotFoundException",
      "NoClassDefFoundError"),
     ("upgrade_failure",)),
    (FailureCategory.DATA_QUALITY,
     ("AnalysisException", "ParseException"),
     ("schema_mismatch", "data_missing")),
    (FailureCategory.PERFORMANCE,
     (),
     ("query_slow",)),
)


def infer_category(error_codes: list[str], symptoms: list[str]) -> str:
    """
    Hypothesise a failure category.

    Scored rather than first-match: a ticket with `OOMKilled` *and* a permission error
    should land on whichever has more supporting evidence, and `UNKNOWN` is returned
    honestly when nothing scores. Forcing a guess would poison the metadata retrieval
    channel with confident noise.
    """
    code_set = set(error_codes)
    symptom_set = set(symptoms)
    best, best_score = FailureCategory.UNKNOWN, 0
    for category, markers, symptom_keys in _CATEGORY_RULES:
        score = 2 * len(code_set & set(markers)) + len(symptom_set & set(symptom_keys))
        if score > best_score:
            best, best_score = category, score
    return best


# ---------------------------------------------------------------------------------------
# Version and key phrase extraction
# ---------------------------------------------------------------------------------------

_VERSION_PATTERNS = (
    re.compile(r"(?i)\biomete\s*(?:version\s*)?v?(\d+\.\d+(?:\.\d+)?)"),
    re.compile(r"(?i)\bversion\s*[:= ]\s*v?(\d+\.\d+(?:\.\d+)?)"),
    re.compile(r"(?i)\bv(\d+\.\d+\.\d+)\b"),
    re.compile(r"(?i)\brelease\s*[:= ]\s*v?(\d+\.\d+(?:\.\d+)?)"),
)

_SPARK_VERSION = re.compile(r"(?i)\bspark\s*(?:version\s*)?v?(\d+\.\d+(?:\.\d+)?)")


def extract_version(text: str, declared: str | None = None) -> str:
    if declared:
        return declared.strip()
    for pattern in _VERSION_PATTERNS:
        if match := pattern.search(text or ""):
            return match.group(1)
    return ""


_STOPWORDS = frozenset("""
a an the and or but if then else when while for to of in on at by with from as is are was
were be been being do does did doing have has had having i we you it they this that these
those not no so very just also can could should would may might must will shall our my me
us them there here what which who whom how why about after before again further once more
most other some such only own same than too s t don now d ll m o re ve y ain
""".split())

_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9_.\-]{2,}")


def extract_key_phrases(text: str, *, limit: int = 18) -> list[str]:
    """
    Distinctive technical terms, used as the lexical channel's query and shown as evidence.

    Weighting favours tokens that look technical (dots, underscores, camelCase, digits)
    because `spark.executor.memory` discriminates between tickets and `cluster` does not.
    """
    if not text:
        return []
    seen: dict[str, float] = {}
    for raw in _TOKEN.findall(text):
        token = raw.strip(".-_")
        lowered = token.lower()
        if len(token) < 3 or lowered in _STOPWORDS or token.startswith("[REDACTED"):
            continue
        weight = 1.0
        if "." in token or "_" in token:
            weight += 1.5
        if re.search(r"[a-z][A-Z]", token):
            weight += 1.2
        if re.search(r"\d", token):
            weight += 0.4
        if len(token) > 12:
            weight += 0.3
        seen[token] = seen.get(token, 0.0) + weight
    ranked = sorted(seen.items(), key=lambda kv: (-kv[1], kv[0]))
    return [token for token, _ in ranked[:limit]]


# ---------------------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------------------


@dataclass
class NormalizedTicket:
    error_codes: list[str] = field(default_factory=list)
    key_phrases: list[str] = field(default_factory=list)
    symptoms: list[str] = field(default_factory=list)
    symptom_labels: list[str] = field(default_factory=list)
    affected_components: dict[str, int] = field(default_factory=dict)
    component: str = TicketComponent.OTHER
    category: str = FailureCategory.UNKNOWN
    extracted_version: str = ""
    spark_version: str = ""
    environment: str = ""
    search_text: str = ""
    confidence_note: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def normalize(
    *,
    title: str,
    description: str,
    error_message: str = "",
    diagnostics: str = "",
    declared_component: str | None = None,
    declared_version: str | None = None,
    declared_environment: str | None = None,
) -> NormalizedTicket:
    """
    Normalise a ticket. Input must already be redacted.

    `search_text` weights the title and error message by repeating them: the lexical
    channel then naturally scores a title match above a passing mention buried in a 400-line
    log paste, without needing a separate field-boosted index.
    """
    combined = "\n".join(filter(None, [title, description, error_message, diagnostics]))

    error_codes = extract_error_codes("\n".join(filter(None, [error_message, diagnostics, combined])))
    symptoms = extract_symptoms(combined)
    component = infer_component(combined, declared_component)
    category = infer_category(error_codes, symptoms)
    version = extract_version(combined, declared_version)
    spark_match = _SPARK_VERSION.search(combined)

    search_text = " ".join(
        filter(
            None,
            [
                title, title, title,
                error_message, error_message,
                " ".join(error_codes), " ".join(error_codes),
                description,
                diagnostics,
                " ".join(symptom_label(s) for s in symptoms),
            ],
        )
    )

    note = ""
    if not error_codes and not symptoms:
        note = (
            "No recognised error codes or symptoms were extracted, so retrieval will rely "
            "mainly on text similarity. Adding the exact error message will materially "
            "improve the matches."
        )
    elif not error_codes:
        note = (
            "No exact error code was found. Symptom and text matching will be used; adding "
            "the verbatim error line gives the strongest signal available."
        )

    return NormalizedTicket(
        error_codes=error_codes,
        key_phrases=extract_key_phrases(combined),
        symptoms=symptoms,
        symptom_labels=[symptom_label(s) for s in symptoms],
        affected_components=component_scores(combined),
        component=component,
        category=category,
        extracted_version=version,
        spark_version=spark_match.group(1) if spark_match else "",
        environment=(declared_environment or "").strip(),
        search_text=search_text.strip(),
        confidence_note=note,
    )
