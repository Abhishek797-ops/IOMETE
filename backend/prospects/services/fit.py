"""
Fit assessment.

The brief is explicit: **do not generate misleading compatibility percentages.** So this
service is built around a published rubric rather than a model's opinion.

How it works and why:

* Seven weighted dimensions summing to 100. Each awards points with a written reason.
* The full breakdown (`rubric`) is returned with every assessment and rendered in the UI
  and the downloadable report. A score whose derivation is inspectable is a defensible
  conversation starter; a bare "87% compatible" is a number people quote at each other in
  a procurement meeting without knowing what it means.
* The headline output is a **band**, not a percentage. `indicative_score` exists to order
  and explain, and every payload carries a disclaimer stating it is indicative and not an
  official IOMETE compatibility determination.
* **Hard caps** override the arithmetic. A prospect with no Kubernetes capability and no
  appetite to acquire it cannot score "strong fit" however well they do elsewhere, because
  self-hosting is the product's central requirement. Scores that ignore a disqualifying
  constraint are how a sales pipeline fills with deals that fail at implementation.
* `gaps` is never empty. An assessment with no limitations is marketing.

Every product claim cites a source id from `docs/product-knowledge/knowledge.json`. Nothing
here asserts pricing, savings, benchmarks or named customers — see `do_not_claim`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from knowledge.services import product_knowledge as pk

from ..models import (
    CompanyType,
    CurrentArchitecture,
    DataVolume,
    FitBand,
    InfrastructureLocation,
    SovereigntyRequirement,
    UseCase,
)

RUBRIC_VERSION = "1.0"

DISCLAIMER = (
    "This is an indicative assessment produced by IOMETE COMPASS from the answers you "
    "supplied, scored against the published rubric shown alongside it. It is not an "
    "official IOMETE compatibility determination, a quotation, or a commitment that any "
    "capability will meet your requirements. Product statements cite IOMETE's own "
    "documentation; anything that could not be verified is labelled rather than asserted. "
    "Confirm the open questions with an IOMETE sales engineer before making a decision."
)


@dataclass
class Dimension:
    key: str
    label: str
    weight: int
    awarded: float
    reasoning: str
    #: What would raise this score. Shown to the prospect, because an assessment that only
    #: grades is less useful than one that tells you what to change.
    improves_with: str = ""

    def to_dict(self) -> dict:
        return {
            "dimension": self.key,
            "label": self.label,
            "weight": self.weight,
            "awarded": round(self.awarded, 1),
            "max": self.weight,
            "reasoning": self.reasoning,
            "improves_with": self.improves_with,
        }


@dataclass
class FitResult:
    score: int
    band: str
    rubric: list[dict]
    requirement_summary: str
    suitability_reasons: list[str]
    technical_requirements: list[dict]
    advantages: list[dict]
    gaps: list[dict]
    questions_for_sales: list[str]
    next_step: str
    cited_sources: list[str]
    disclaimer: str = DISCLAIMER
    caps_applied: list[str] = field(default_factory=list)


# =======================================================================================
# Dimension scoring
# =======================================================================================


def _score_sovereignty(answers: dict) -> Dimension:
    """
    Weight 20 — the strongest single signal.

    A mandatory data-residency requirement is the clearest reason to prefer a self-hosted
    lakehouse, and IOMETE documents that the platform "operates entirely within your
    infrastructure".
    """
    requirement = answers.get("sovereignty_requirement", SovereigntyRequirement.UNKNOWN)
    mapping = {
        SovereigntyRequirement.MANDATORY: (
            20,
            "You stated data cannot leave your control. This is the requirement IOMETE's "
            "architecture is built around: it is deployed into your own Kubernetes cluster "
            "and IOMETE documents that no data is sent outside your organisation.",
        ),
        SovereigntyRequirement.STRONG: (
            17,
            "You have a strong preference for keeping data under your control, which maps "
            "directly onto a self-hosted deployment model.",
        ),
        SovereigntyRequirement.SOME: (
            12,
            "Some workloads have residency constraints. A self-hosted lakehouse covers "
            "those without forcing a second platform for the rest.",
        ),
        SovereigntyRequirement.NONE: (
            6,
            "You have no specific residency requirement, so sovereignty is not a driver "
            "for you. IOMETE can still fit on cost and openness grounds, but a managed "
            "SaaS lakehouse would be a fair comparison to run.",
        ),
        SovereigntyRequirement.UNKNOWN: (
            9,
            "Residency requirements were not stated. This is worth establishing early — it "
            "is usually the deciding factor between self-hosted and SaaS.",
        ),
    }
    awarded, reasoning = mapping.get(requirement, mapping[SovereigntyRequirement.UNKNOWN])
    return Dimension(
        key="sovereignty",
        label="Data sovereignty and residency",
        weight=20,
        awarded=awarded,
        reasoning=reasoning,
        improves_with=(
            "Confirming which datasets are subject to residency rules and which regulator "
            "or policy imposes them."
            if requirement in {SovereigntyRequirement.UNKNOWN, SovereigntyRequirement.NONE}
            else ""
        ),
    )


def _score_infrastructure(answers: dict) -> Dimension:
    """
    Weight 18 — can they actually host it?

    IOMETE deploys as a Helm chart into Kubernetes. Somewhere to run it is not a nice-to-
    have, it is the precondition.
    """
    location = answers.get("infrastructure_location", InfrastructureLocation.UNDECIDED)
    maturity = (answers.get("kubernetes_maturity") or "").lower()

    base = {
        InfrastructureLocation.ON_PREMISES: 13,
        InfrastructureLocation.PRIVATE_CLOUD: 14,
        InfrastructureLocation.PUBLIC_CLOUD: 14,
        InfrastructureLocation.HYBRID: 15,
        InfrastructureLocation.AIR_GAPPED: 11,
        InfrastructureLocation.UNDECIDED: 8,
    }.get(location, 8)

    notes = []
    if location == InfrastructureLocation.HYBRID:
        notes.append(
            "IOMETE describes its deployment model as \"hybrid first\", so a mixed "
            "on-premises and cloud footprint is a documented pattern rather than an "
            "exception."
        )
    elif location == InfrastructureLocation.PUBLIC_CLOUD:
        notes.append(
            "IOMETE deploys into your own Kubernetes cluster on AWS, Azure or Google "
            "Cloud, using that cloud's object storage. Note that zone-aware scheduling is "
            "documented only for AWS."
        )
    elif location == InfrastructureLocation.ON_PREMISES:
        notes.append(
            "On-premises deployment into your own Kubernetes cluster is documented, with "
            "object storage options including Apache Ozone, MinIO, Dell ECS and any "
            "S3-compatible target."
        )
    elif location == InfrastructureLocation.AIR_GAPPED:
        notes.append(
            "An isolated network is architecturally compatible with a self-hosted "
            "platform, but air-gapped installation is not documented on the IOMETE pages "
            "COMPASS has verified. This needs explicit confirmation."
        )
    else:
        notes.append(
            "Your hosting model is undecided. Because IOMETE installs into a Kubernetes "
            "cluster you provide, this is the first decision to settle."
        )

    if "advanced" in maturity or "production" in maturity:
        base += 3
        notes.append("You already run Kubernetes in production, which removes the main adoption risk.")
    elif "some" in maturity or "learning" in maturity or "basic" in maturity:
        base += 1
        notes.append(
            "You have some Kubernetes experience. Expect the operational learning curve to "
            "be the main project risk rather than the platform itself."
        )
    elif "none" in maturity:
        base -= 4
        notes.append(
            "You reported no Kubernetes capability. This is the single largest gap: IOMETE "
            "is Kubernetes-native and someone has to operate the cluster."
        )

    return Dimension(
        key="infrastructure",
        label="Infrastructure and Kubernetes readiness",
        weight=18,
        awarded=max(0, min(18, base)),
        reasoning=" ".join(notes),
        improves_with=(
            "Identifying who will own the Kubernetes cluster, or scoping IOMETE's "
            "forward-deployed engineering alongside your team."
            if "none" in maturity or not maturity
            else ""
        ),
    )


def _score_scale(answers: dict) -> Dimension:
    """
    Weight 12.

    A lakehouse earns its complexity at scale. Below a terabyte, a well-indexed Postgres is
    often the honest answer, and saying so is more useful than scoring everyone highly.
    """
    volume = answers.get("data_volume", DataVolume.UNKNOWN)
    mapping = {
        DataVolume.UNDER_1TB: (
            5,
            "Under 1 TB. A lakehouse is unlikely to pay for its operational complexity at "
            "this volume — a managed relational warehouse is often the better answer. "
            "IOMETE becomes compelling if you expect rapid growth or have residency "
            "constraints that rule out SaaS.",
        ),
        DataVolume.TB_1_10: (
            9,
            "1–10 TB sits at the point where separating storage from compute starts to pay, "
            "particularly if your current warehouse bill scales with volume.",
        ),
        DataVolume.TB_10_100: (
            12,
            "10–100 TB is squarely where a lakehouse architecture pays off: object storage "
            "is cheap, and compute scales to zero between workloads.",
        ),
        DataVolume.TB_100_1PB: (
            12,
            "At 100 TB–1 PB, keeping one open copy of the data in object storage rather "
            "than duplicating it into a warehouse is a substantial structural saving.",
        ),
        DataVolume.OVER_1PB: (
            11,
            "Above 1 PB the architecture fits well, but scale this large warrants an "
            "explicit sizing and concurrency conversation — IOMETE does not publish "
            "concurrency or executor ceilings, so they must be established directly.",
        ),
        DataVolume.UNKNOWN: (
            7,
            "Data volume was not specified, so the scale case cannot be assessed. This is "
            "the main input to sizing and cost.",
        ),
    }
    awarded, reasoning = mapping.get(volume, mapping[DataVolume.UNKNOWN])
    return Dimension(
        key="scale",
        label="Data volume and workload scale",
        weight=12,
        awarded=awarded,
        reasoning=reasoning,
        improves_with=(
            "Supplying your current total volume and expected 24-month growth."
            if volume == DataVolume.UNKNOWN
            else ""
        ),
    )


def _score_use_case(answers: dict) -> Dimension:
    """
    Weight 15 — is the intended work something IOMETE documents support for?

    Scores are grounded in capabilities with `status: verified` in the knowledge base. A
    use case that rests on a `needs_confirmation` capability is scored lower and flagged,
    not quietly credited.
    """
    primary = answers.get("primary_use_case", UseCase.OTHER)
    secondary = set(answers.get("secondary_use_cases") or [])

    mapping = {
        UseCase.CONSOLIDATION: (
            15,
            "Consolidating a lake and a warehouse into one platform is the core use case: "
            "IOMETE describes combining \"the flexibility of data lakes with the "
            "performance of data warehouses\" over one copy of the data.",
        ),
        UseCase.BI_REPORTING: (
            14,
            "BI and reporting are directly supported. Compute clusters expose a "
            "HiveServer2 JDBC/ODBC endpoint and Arrow Flight, and Power BI, Tableau, "
            "Metabase, Apache Superset and Redash are documented integrations.",
        ),
        UseCase.DATA_ENGINEERING: (
            14,
            "Data engineering is well covered: managed Spark jobs in Scala or PySpark, "
            "reusable job templates, Prefect-backed scheduling, dbt and Apache Airflow "
            "integrations, and Spark Connect for local development.",
        ),
        UseCase.AI_ML: (
            13,
            "AI and ML workloads run on the platform through Jupyter containers and Spark, "
            "next to governed data rather than on extracted copies. IOMETE positions "
            "itself as \"the data platform for the ai era\".",
        ),
        UseCase.DATA_SCIENCE: (
            13,
            "Data science is supported through containerised JupyterLab environments with "
            "Python, R and Scala, running under the platform's access controls.",
        ),
        UseCase.GOVERNANCE: (
            14,
            "Governance is a documented strength: Apache Ranger policies enforced at the "
            "Iceberg REST Catalog, control down to row, column and tag level, masking with "
            "fictional values, and a searchable data catalog with lineage.",
        ),
        UseCase.DATA_MESH: (
            13,
            "A data-mesh operating model is directly supported by Domains — separate "
            "teams, projects or environments with their own resources, members and roles.",
        ),
        UseCase.REAL_TIME: (
            10,
            "Real-time analytics is partially verified. Event Streams ingest over HTTP into "
            "Iceberg tables in near real time, and Spark Structured Streaming jobs are "
            "documented. However the connection pattern for Kafka, Pulsar and Kinesis is "
            "named on IOMETE's homepage without a corresponding documented connector, so "
            "it is marked as needing confirmation.",
        ),
        UseCase.OTHER: (
            8,
            "Your primary use case was not one of the documented categories, so it is "
            "scored conservatively. Describe it to an IOMETE engineer directly.",
        ),
    }
    awarded, reasoning = mapping.get(primary, mapping[UseCase.OTHER])

    # Breadth bonus: several documented use cases on one platform is the consolidation
    # argument, which is where a lakehouse is most defensible.
    well_supported = {
        UseCase.CONSOLIDATION, UseCase.BI_REPORTING, UseCase.DATA_ENGINEERING,
        UseCase.GOVERNANCE, UseCase.AI_ML, UseCase.DATA_SCIENCE, UseCase.DATA_MESH,
    }
    breadth = len(secondary & well_supported)
    if breadth >= 2:
        reasoning += (
            f" You also named {breadth} further documented use cases, which strengthens the "
            "case for one platform rather than several specialised tools."
        )

    return Dimension(
        key="use_case",
        label="Use-case alignment",
        weight=15,
        awarded=min(15, awarded + (1 if breadth >= 2 else 0)),
        reasoning=reasoning,
        improves_with=(
            "Describing the specific workloads you need to run."
            if primary == UseCase.OTHER
            else ""
        ),
    )


def _score_current_pain(answers: dict) -> Dimension:
    """
    Weight 12 — is there a problem worth a migration?

    Platform migrations fail for lack of a driver more often than for lack of features. A
    prospect with no current pain scores low here, honestly.
    """
    architecture = answers.get("current_architecture", CurrentArchitecture.NONE)
    challenges = set(answers.get("challenges") or [])

    mapping = {
        CurrentArchitecture.BOTH: (
            12,
            "You run both a lake and a warehouse, which means you are already paying to "
            "store data twice and maintaining the pipeline between them. Consolidation is "
            "the clearest value case.",
        ),
        CurrentArchitecture.WAREHOUSE: (
            10,
            "A cloud data warehouse gives you a concrete baseline to compare on cost and "
            "on whether your data has to sit in a vendor's environment.",
        ),
        CurrentArchitecture.DATA_LAKE: (
            11,
            "A data lake without transactional tables is exactly the gap Apache Iceberg "
            "closes — ACID guarantees, time travel and safe concurrent writes over the "
            "files you already have.",
        ),
        CurrentArchitecture.LAKEHOUSE: (
            8,
            "You already operate a lakehouse, so the comparison is platform-to-platform "
            "rather than architectural. Sovereignty, cost structure and openness are the "
            "axes that would differentiate.",
        ),
        CurrentArchitecture.DATABASES_ONLY: (
            7,
            "Moving from operational databases straight to a lakehouse is a significant "
            "step. It can be the right one, but expect the project to be as much about "
            "capability building as about technology.",
        ),
        CurrentArchitecture.NONE: (
            5,
            "With nothing formal in place, a self-hosted lakehouse is a large first "
            "commitment. A simpler managed starting point is often the more honest "
            "recommendation unless residency rules force self-hosting.",
        ),
    }
    awarded, reasoning = mapping.get(architecture, mapping[CurrentArchitecture.NONE])

    recognised = {
        "cost", "vendor_lock_in", "data_residency", "performance", "governance",
        "data_silos", "scaling", "compliance", "slow_queries", "duplicate_copies",
    }
    hits = challenges & recognised
    if hits:
        reasoning += (
            " The challenges you named ("
            + ", ".join(sorted(h.replace("_", " ") for h in hits))
            + ") are the ones this architecture is intended to address."
        )

    return Dimension(
        key="current_pain",
        label="Current architecture and pain",
        weight=12,
        awarded=min(12, awarded + (1 if len(hits) >= 2 else 0)),
        reasoning=reasoning,
        improves_with=(
            "Quantifying what the current setup costs you — in spend, in engineer time, or "
            "in decisions you cannot make."
            if not hits
            else ""
        ),
    )


def _score_operations(answers: dict) -> Dimension:
    """
    Weight 13 — can they run it on day 2?

    The dimension most assessments skip and most implementations fail on. Self-hosting
    means owning upgrades, capacity and incidents.
    """
    maturity = (answers.get("kubernetes_maturity") or "").lower()
    team = (answers.get("team_size") or "").lower()
    constraints = set(answers.get("constraints") or [])
    company_type = answers.get("company_type", CompanyType.OTHER)

    awarded = 7.0
    notes: list[str] = []

    if "advanced" in maturity or "production" in maturity:
        awarded += 4
        notes.append("Running Kubernetes in production already is the strongest readiness signal.")
    elif "some" in maturity or "basic" in maturity or "learning" in maturity:
        awarded += 1
        notes.append("Partial Kubernetes experience means a learning curve rather than a blocker.")
    elif "none" in maturity:
        awarded -= 4
        notes.append(
            "No Kubernetes capability means either hiring, partnering, or engaging IOMETE's "
            "forward-deployed engineers. IOMETE describes FDEs as \"services that extend "
            "customer teams\", though scope and commercial terms are not published."
        )

    if "large" in team or "dedicated" in team:
        awarded += 2
        notes.append("A dedicated data platform team can absorb the operational load.")
    elif "small" in team or "1" in team or "2" in team:
        awarded -= 2
        notes.append(
            "A small team taking on a self-hosted platform is a real risk. Scope the "
            "operational effort explicitly rather than assuming it is absorbed."
        )

    if "tight_timeline" in constraints:
        awarded -= 2
        notes.append(
            "A tight timeline works against a self-hosted deployment, which requires "
            "cluster provisioning, storage configuration and a PostgreSQL metadata server "
            "before any analytics happen."
        )
    if "limited_budget" in constraints:
        notes.append(
            "On a constrained budget, note that the infrastructure is yours to pay for; "
            "IOMETE's cost claims are relative to SaaS licensing, not absolute."
        )
    if company_type == CompanyType.PUBLIC_SECTOR:
        awarded += 1
        notes.append(
            "Public-sector procurement usually favours a platform that runs inside your own "
            "estate and uses open formats."
        )

    return Dimension(
        key="operations",
        label="Operational capability and constraints",
        weight=13,
        awarded=max(0, min(13, awarded)),
        reasoning=" ".join(notes)
        or "Operational capability was not described in enough detail to assess.",
        improves_with=(
            "Naming who would operate the cluster, and whether forward-deployed engineering "
            "support is in scope."
            if awarded < 9
            else ""
        ),
    )


def _score_integration(answers: dict) -> Dimension:
    """
    Weight 10 — how much of their existing stack is already documented?

    Scored strictly against `status: verified` integrations in the knowledge base, so a
    generated recommendation cannot name a connector IOMETE does not document.
    """
    systems = [str(s).lower() for s in (answers.get("current_systems") or [])]
    clouds = [str(c).lower() for c in (answers.get("cloud_providers") or [])]
    verified = {name.lower() for name in pk.verified_integration_names()}
    storage = {entry["name"].lower() for entry in pk.storage_backends(verified_only=True)}

    matched: list[str] = []
    unmatched: list[str] = []
    for system in systems:
        if any(system in name or name in system for name in verified | storage):
            matched.append(system)
        elif system in {"postgresql", "postgres", "mysql", "csv", "json", "api", "apis"}:
            # Generic sources: reachable, but via a Spark job rather than a named connector.
            matched.append(system)
        else:
            unmatched.append(system)

    cloud_matched = [c for c in clouds if c in {"aws", "azure", "gcp", "google cloud", "on_prem"}]

    awarded = 4.0
    if matched:
        awarded += min(4.0, 1.3 * len(matched))
    if cloud_matched:
        awarded += 2.0

    notes = []
    if matched:
        notes.append(
            f"{len(matched)} of the systems you listed map onto documented IOMETE "
            f"integrations or storage backends ({', '.join(sorted(set(matched))[:6])})."
        )
    if unmatched:
        notes.append(
            f"These are not covered by a documented integration and need confirmation: "
            f"{', '.join(sorted(set(unmatched))[:6])}. They may still be reachable through "
            "a Spark job or the SQL endpoint, but COMPASS will not claim a connector that "
            "IOMETE does not document."
        )
    if cloud_matched:
        notes.append(
            f"Your cloud footprint ({', '.join(sorted(set(cloud_matched)))}) is a documented "
            "deployment target."
        )
    if not systems:
        notes.append("No existing systems were listed, so integration coverage could not be assessed.")

    return Dimension(
        key="integration",
        label="Integration coverage of your existing stack",
        weight=10,
        awarded=max(0, min(10, awarded)),
        reasoning=" ".join(notes),
        improves_with=(
            "Listing the databases, storage and BI tools you need to keep."
            if not systems
            else ""
        ),
    )


DIMENSION_SCORERS = (
    _score_sovereignty,
    _score_infrastructure,
    _score_scale,
    _score_use_case,
    _score_current_pain,
    _score_operations,
    _score_integration,
)


# =======================================================================================
# Banding
# =======================================================================================


def _band(score: int, answers: dict) -> tuple[str, list[str]]:
    """
    Convert a score into a band, applying hard caps.

    The caps exist because the weighted sum can be misleading in specific, predictable
    situations. A prospect who cannot host Kubernetes is not a "strong fit" with an
    asterisk — they are conditional until that is solved, and saying so prevents a deal
    that fails during implementation.
    """
    caps: list[str] = []
    maturity = (answers.get("kubernetes_maturity") or "").lower()
    location = answers.get("infrastructure_location", InfrastructureLocation.UNDECIDED)
    volume = answers.get("data_volume", DataVolume.UNKNOWN)
    sovereignty = answers.get("sovereignty_requirement", SovereigntyRequirement.UNKNOWN)

    ceiling = FitBand.STRONG

    if "none" in maturity:
        ceiling = FitBand.CONDITIONAL
        caps.append(
            "Capped at conditional: you reported no Kubernetes capability. IOMETE is "
            "Kubernetes-native, so this has to be solved — in-house, with a partner, or "
            "through IOMETE's forward-deployed engineers — before any other strength "
            "matters."
        )

    if volume == DataVolume.UNDER_1TB and sovereignty in {
        SovereigntyRequirement.NONE, SovereigntyRequirement.UNKNOWN
    }:
        ceiling = min(ceiling, FitBand.CONDITIONAL, key=_band_rank)
        caps.append(
            "Capped at conditional: under 1 TB with no residency requirement, a lakehouse "
            "is unlikely to repay its operational complexity. A managed warehouse is "
            "probably the better recommendation today."
        )

    if location == InfrastructureLocation.UNDECIDED and "none" in maturity:
        ceiling = FitBand.NEEDS_DISCUSSION
        caps.append(
            "Capped at needs-discussion: with neither a hosting model nor Kubernetes "
            "capability decided, there is not enough information to assess fit."
        )

    answered = sum(
        1
        for key in (
            "company_type", "infrastructure_location", "data_volume", "primary_use_case",
            "sovereignty_requirement", "current_architecture",
        )
        if answers.get(key) and answers.get(key) not in {"unknown", "undecided", "other"}
    )
    if answered < 3:
        ceiling = FitBand.NEEDS_DISCUSSION
        caps.append(
            "Capped at needs-discussion: too few questions were answered substantively to "
            "produce a meaningful assessment."
        )

    natural = (
        FitBand.STRONG if score >= 78
        else FitBand.PROMISING if score >= 62
        else FitBand.CONDITIONAL if score >= 45
        else FitBand.LIMITED
    )
    band = min(natural, ceiling, key=_band_rank)
    return band, caps


_BAND_ORDER = {
    FitBand.STRONG: 4,
    FitBand.PROMISING: 3,
    FitBand.CONDITIONAL: 2,
    FitBand.LIMITED: 1,
    FitBand.NEEDS_DISCUSSION: 0,
}


def _band_rank(band: str) -> int:
    return _BAND_ORDER.get(band, 0)


BAND_EXPLANATIONS = {
    FitBand.STRONG: (
        "Your requirements line up well with what IOMETE documents, and you appear able to "
        "operate a self-hosted platform. A technical deep-dive is the sensible next step."
    ),
    FitBand.PROMISING: (
        "There is a real case here, with open questions that need answering before you "
        "could commit. Those questions are listed below."
    ),
    FitBand.CONDITIONAL: (
        "Whether IOMETE fits depends on specifics that are not yet settled — most often "
        "who will operate the Kubernetes cluster, or whether the scale justifies a "
        "lakehouse at all."
    ),
    FitBand.LIMITED: (
        "On the answers given, a self-hosted lakehouse looks like more platform than your "
        "situation calls for. A managed service would likely serve you better, and saying "
        "so is more useful than a sales conversation that disappoints later."
    ),
    FitBand.NEEDS_DISCUSSION: (
        "There is not enough information to assess fit. The questions below are the ones "
        "that would change the answer."
    ),
}


# =======================================================================================
# Narrative construction
# =======================================================================================


def _requirement_summary(answers: dict) -> str:
    company = answers.get("company_name") or "Your organisation"
    company_type = dict(CompanyType.choices).get(
        answers.get("company_type", ""), "an organisation"
    )
    location = dict(InfrastructureLocation.choices).get(
        answers.get("infrastructure_location", ""), "an undecided hosting model"
    )
    volume = dict(DataVolume.choices).get(answers.get("data_volume", ""), "an unspecified volume")
    use_case = dict(UseCase.choices).get(answers.get("primary_use_case", ""), "general analytics")
    sovereignty = dict(SovereigntyRequirement.choices).get(
        answers.get("sovereignty_requirement", ""), "unstated residency requirements"
    )
    architecture = dict(CurrentArchitecture.choices).get(
        answers.get("current_architecture", ""), "no formal data platform"
    )

    return (
        f"{company} is {company_type.lower()} running {location.lower()}, processing "
        f"{volume.lower()} of data, primarily for {use_case.lower()}. Today the data "
        f"platform is best described as: {architecture.lower()}. On data sovereignty the "
        f"position is: {sovereignty.lower()}."
    )


def _technical_requirements(answers: dict) -> list[dict]:
    """
    What this prospect would actually have to provide. All from verified sources.

    Listed plainly, including the unglamorous parts, because a prospect who discovers the
    PostgreSQL requirement during implementation is a prospect who feels misled.
    """
    location = answers.get("infrastructure_location", InfrastructureLocation.UNDECIDED)
    clouds = [str(c).lower() for c in (answers.get("cloud_providers") or [])]

    requirements = [
        {
            "requirement": "A Kubernetes cluster you operate",
            "detail": (
                "IOMETE installs as the `iomete-data-plane-enterprise` Helm chart. Platform "
                "services run in a single namespace; Spark workloads can be spread across "
                "per-team namespaces with their own CPU and memory quotas."
            ),
            "sources": ["S4", "S8"],
            "status": "verified",
        },
        {
            "requirement": "An ingress controller in front of the IOMETE Gateway",
            "detail": (
                "All traffic — UI, API, Spark Connect, Arrow Flight and WebSocket — enters "
                "through one Nginx-based Gateway, which expects an ingress controller in "
                "front of it. gRPC routes carry a 24-hour read timeout."
            ),
            "sources": ["S4", "S8"],
            "status": "verified",
        },
        {
            "requirement": "Object storage for all table data",
            "detail": (
                "Table data, Spark event logs and SQL results all live in object storage "
                "under `data/`, `iomete-assets/spark-history/` and "
                "`iomete-assets/sql-results/`. Supported configuration types are "
                "`s3_compatible`, `aws_s3`, `gcs`, `azure_gen1` and `azure_gen2`."
            ),
            "sources": ["S4", "S8"],
            "status": "verified",
        },
        {
            "requirement": "A PostgreSQL server for platform metadata",
            "detail": (
                "All services share one PostgreSQL server. The installer creates separate "
                "databases with an `iomete_` prefix for the Hive Metastore, Ranger, the "
                "Iceberg catalog, Prefect and each microservice. Your analytical data does "
                "not live here. If you front it with PgBouncer, a direct host must also be "
                "configured because schema migrations need a session-scoped advisory lock."
            ),
            "sources": ["S4", "S8"],
            "status": "verified",
        },
        {
            "requirement": "An identity provider for single sign-on",
            "detail": (
                "The Identity Service supports built-in username/password, LDAP, and SSO "
                "via SAML or OIDC. Using your existing directory means access follows your "
                "joiner/leaver process."
            ),
            "sources": ["S4"],
            "status": "verified",
        },
        {
            "requirement": "Kubernetes operational capability",
            "detail": (
                "Someone has to size the cluster, apply upgrades and respond to incidents. "
                "Node scaling can be automated with Karpenter on AWS, GKE Node "
                "Auto-Provisioning, or the AKS Cluster Autoscaler; on-premises it is manual "
                "or driven by your own automation."
            ),
            "sources": ["S9"],
            "status": "verified",
        },
    ]

    if location == InfrastructureLocation.AIR_GAPPED:
        requirements.append(
            {
                "requirement": "Air-gapped installation support — unconfirmed",
                "detail": (
                    "An isolated network is architecturally consistent with a self-hosted "
                    "platform, but air-gapped or offline installation is not documented on "
                    "the IOMETE pages COMPASS has verified. Ask for the image mirroring and "
                    "update process explicitly."
                ),
                "sources": [],
                "status": "needs_confirmation",
            }
        )
    if "aws" not in clouds and location == InfrastructureLocation.PUBLIC_CLOUD:
        requirements.append(
            {
                "requirement": "Note on zone-aware scheduling",
                "detail": (
                    "IOMETE documents zone-aware scheduling for AWS only. On Azure or "
                    "Google Cloud, confirm how availability-zone placement is handled for "
                    "Spark workloads."
                ),
                "sources": ["S8"],
                "status": "verified",
            }
        )
    return requirements


def _advantages(answers: dict, dimensions: list[Dimension]) -> list[dict]:
    """Advantages, each tied to a verified capability and to this prospect's answers."""
    advantages: list[dict] = []
    sovereignty = answers.get("sovereignty_requirement")
    volume = answers.get("data_volume")
    architecture = answers.get("current_architecture")

    if sovereignty in {SovereigntyRequirement.MANDATORY, SovereigntyRequirement.STRONG}:
        advantages.append(
            {
                "advantage": "Data never leaves your environment",
                "detail": (
                    "IOMETE states the platform \"operates entirely within your "
                    "infrastructure\" and that \"no data is sent outside of your "
                    "organization\". For a residency requirement, that is an architectural "
                    "answer rather than a contractual one."
                ),
                "sources": ["S1", "S3"],
                "status": "verified",
            }
        )
    advantages.append(
        {
            "advantage": "Open table format, so you are not locked in",
            "detail": (
                "Tables are Apache Iceberg in your own object storage, and IOMETE ships an "
                "Iceberg REST Catalog implementing the open specification with Ranger "
                "policies enforced at that layer. Other Iceberg-compatible engines can read "
                "the same tables under the same access control."
            ),
            "sources": ["S4", "S7"],
            "status": "verified",
        }
    )
    advantages.append(
        {
            "advantage": "Compute scales to zero when nobody is querying",
            "detail": (
                "Each compute cluster uses Spark dynamic allocation: it starts with one "
                "executor, grows to a configured maximum, and scales back to zero when "
                "idle. Executors can run on spot or preemptible capacity, which IOMETE "
                "documents as up to a 3x reduction for that component."
            ),
            "sources": ["S9"],
            "status": "verified",
        }
    )
    if architecture in {CurrentArchitecture.BOTH, CurrentArchitecture.DATA_LAKE}:
        advantages.append(
            {
                "advantage": "One copy of the data instead of two",
                "detail": (
                    "Iceberg gives the files already in your lake ACID transactions, time "
                    "travel and rollback, schema and partition evolution, and safe "
                    "concurrent writes — so analytics can run against them directly rather "
                    "than against a copy loaded into a warehouse."
                ),
                "sources": ["S6", "S7"],
                "status": "verified",
            }
        )
    advantages.append(
        {
            "advantage": "Access control enforced at the catalog, not in each tool",
            "detail": (
                "Apache Ranger policies are enforced by the Iceberg REST Catalog Service. "
                "A policy enforced inside one BI tool is a suggestion; a policy enforced at "
                "the catalog applies to every engine that reads the tables. Control is "
                "documented down to table, row, column, user, group, team and department "
                "level, with tag-based policies and masking using fictional values."
            ),
            "sources": ["S1", "S4"],
            "status": "verified",
        }
    )
    if volume in {DataVolume.TB_10_100, DataVolume.TB_100_1PB, DataVolume.OVER_1PB}:
        advantages.append(
            {
                "advantage": "Workload isolation that holds at your scale",
                "detail": (
                    "Independent compute clusters per team or environment, per-namespace CPU "
                    "and memory quotas, node selectors separating platform services from "
                    "Spark workloads, and priority classes. A runaway job is contained by "
                    "the platform rather than by an incident call."
                ),
                "sources": ["S9"],
                "status": "verified",
            }
        )
    return advantages


def _gaps(answers: dict, dimensions: list[Dimension], caps: list[str]) -> list[dict]:
    """
    Honest limitations. Never empty — an assessment with no gaps is marketing.

    Weak dimensions are converted into named gaps, plus the structural caveats that apply
    to everyone considering a self-hosted platform.
    """
    gaps: list[dict] = []
    by_key = {dimension.key: dimension for dimension in dimensions}

    for dimension in dimensions:
        ratio = dimension.awarded / dimension.weight if dimension.weight else 1
        if ratio < 0.6:
            gaps.append(
                {
                    "gap": f"Weak on: {dimension.label.lower()}",
                    "detail": dimension.reasoning,
                    "mitigation": dimension.improves_with
                    or "Discuss this directly with an IOMETE sales engineer.",
                    "severity": "high" if ratio < 0.4 else "medium",
                }
            )

    gaps.append(
        {
            "gap": "You own the operations",
            "detail": (
                "Self-hosting means you are responsible for the Kubernetes cluster, object "
                "storage, the PostgreSQL metadata server, upgrades and incident response. "
                "That is the trade for sovereignty and cost control, and it is real work. "
                "If your organisation has no appetite for running infrastructure, a managed "
                "SaaS lakehouse may genuinely suit you better."
            ),
            "mitigation": (
                "Scope IOMETE's forward-deployed engineering alongside your team, or "
                "identify an internal owner before committing."
            ),
            "severity": "medium",
        }
    )
    gaps.append(
        {
            "gap": "Several operational limits are not published",
            "detail": (
                "IOMETE does not publish Kubernetes version requirements, node sizing, "
                "PostgreSQL sizing, concurrency limits or maximum executor counts on the "
                "documentation COMPASS has verified. These matter for sizing and for your "
                "own capacity planning."
            ),
            "mitigation": "Request a reference architecture for your volume and concurrency.",
            "severity": "medium",
        }
    )
    gaps.append(
        {
            "gap": "Cost claims are vendor claims",
            "detail": (
                "IOMETE's homepage claims 2-5x savings versus SaaS and its platform-overview "
                "page claims 2-3x. The two figures disagree, and neither is independently "
                "verified or modelled on your workload. COMPASS will not reproduce them as "
                "a saving for you."
            ),
            "mitigation": (
                "Build your own total-cost model including the infrastructure you must "
                "provide, and compare it against your current bill."
            ),
            "severity": "medium",
        }
    )
    if answers.get("primary_use_case") == UseCase.REAL_TIME:
        gaps.append(
            {
                "gap": "Streaming connector pattern needs confirmation",
                "detail": (
                    "Kafka, Pulsar and Kinesis are named on IOMETE's homepage, but the "
                    "integrations documentation does not describe a dedicated ingestion "
                    "connector for them. Event Streams (HTTP POST into Iceberg) and Spark "
                    "Structured Streaming are documented."
                ),
                "mitigation": (
                    "Ask specifically how your streaming source would connect, and whether "
                    "it is a managed connector or a Spark job you maintain."
                ),
                "severity": "high",
            }
        )
    if by_key.get("integration") and by_key["integration"].awarded < 7:
        gaps.append(
            {
                "gap": "Parts of your stack have no documented integration",
                "detail": by_key["integration"].reasoning,
                "mitigation": (
                    "Confirm the connection pattern for each system you must keep. Most are "
                    "reachable via the SQL endpoint or a Spark job, but confirm rather than "
                    "assume."
                ),
                "severity": "medium",
            }
        )
    return gaps


def _questions(answers: dict, gaps: list[dict], band: str) -> list[str]:
    """
    Questions for the IOMETE sales engineer.

    Derived from this prospect's actual gaps rather than generic. A good question list is
    the most useful thing an assessment like this can produce, because it makes the next
    conversation efficient for both sides.
    """
    questions = [
        "What does a reference deployment look like for our data volume and expected "
        "query concurrency — node counts, sizes and PostgreSQL requirements?",
        "What is the upgrade cadence, what does an upgrade involve operationally, and what "
        "is our rollback path if one fails?",
        "How are platform and data-access audit logs emitted, retained and exported to our "
        "SIEM?",
    ]

    maturity = (answers.get("kubernetes_maturity") or "").lower()
    if "none" in maturity or "some" in maturity:
        questions.append(
            "What exactly does forward-deployed engineering cover, for how long, and what "
            "does our team need to be able to do by the end of it?"
        )
    if answers.get("sovereignty_requirement") in {
        SovereigntyRequirement.MANDATORY, SovereigntyRequirement.STRONG
    }:
        questions.append(
            "Can we see the current SOC 2 report and its scope statement, and what is the "
            "encryption posture at rest and in transit across the Gateway, object storage "
            "and PostgreSQL?"
        )
    if answers.get("infrastructure_location") == InfrastructureLocation.AIR_GAPPED:
        questions.append(
            "Is a fully air-gapped installation supported, and what is the image mirroring "
            "and update process?"
        )
    if answers.get("primary_use_case") == UseCase.REAL_TIME:
        questions.append(
            "How would our streaming source connect — a managed connector, Event Streams "
            "over HTTP, or a Spark Structured Streaming job we maintain?"
        )
    if answers.get("data_volume") == DataVolume.OVER_1PB:
        questions.append(
            "What are the practical ceilings on executors per cluster and concurrent "
            "queries, and how have they held at petabyte scale?"
        )
    if answers.get("primary_use_case") in {UseCase.BI_REPORTING, UseCase.DATA_MESH}:
        questions.append(
            "Which external Iceberg-compatible engines are formally tested against your "
            "Iceberg REST Catalog?"
        )
    if band in {FitBand.LIMITED, FitBand.CONDITIONAL}:
        questions.append(
            "Given our situation, is IOMETE the right fit today — and if not, what would "
            "have to change for it to be?"
        )
    questions.append(
        "Which reference customers in our sector would you be able to introduce us to?"
    )
    return questions[:8]


def _next_step(band: str, answers: dict) -> str:
    if band == FitBand.STRONG:
        return (
            "Book a technical deep-dive. Bring your Kubernetes and storage team, and ask "
            "for a reference architecture sized to the volume you reported."
        )
    if band == FitBand.PROMISING:
        return (
            "Book a scoping call focused on the open questions below, particularly sizing "
            "and operational ownership. Those answers will settle the case either way."
        )
    if band == FitBand.CONDITIONAL:
        return (
            "Settle the conditional items first — usually who operates the Kubernetes "
            "cluster, or whether your data volume justifies a lakehouse. A conversation "
            "before that is likely to be inconclusive."
        )
    if band == FitBand.LIMITED:
        return (
            "A self-hosted lakehouse looks like more platform than you need today. Explore "
            "the architecture playground to understand the model, and revisit this if your "
            "scale grows or a residency requirement appears."
        )
    return (
        "Work through the Fit Finder again with your infrastructure and data volume to "
        "hand — the assessment needs those to say anything useful."
    )


# =======================================================================================
# Entry point
# =======================================================================================


def assess(answers: dict) -> FitResult:
    """
    Produce an indicative fit assessment from wizard answers.

    Pure function: no database access, no model call, no side effects. That makes it
    deterministic, trivially testable, and reproducible — the same answers always produce
    the same assessment, which matters when a prospect downloads a report and refers to it
    three weeks later in a meeting.
    """
    dimensions = [scorer(answers) for scorer in DIMENSION_SCORERS]
    raw_score = sum(dimension.awarded for dimension in dimensions)
    score = round(max(0.0, min(100.0, raw_score)))

    band, caps = _band(score, answers)
    gaps = _gaps(answers, dimensions, caps)

    reasons = [
        f"{dimension.label}: {dimension.reasoning}"
        for dimension in sorted(dimensions, key=lambda d: -(d.awarded / max(d.weight, 1)))[:4]
    ]

    cited: set[str] = set()
    for collection in (_technical_requirements(answers), _advantages(answers, dimensions)):
        for item in collection:
            cited.update(item.get("sources") or [])

    return FitResult(
        score=score,
        band=band,
        rubric=[dimension.to_dict() for dimension in dimensions],
        requirement_summary=_requirement_summary(answers),
        suitability_reasons=reasons,
        technical_requirements=_technical_requirements(answers),
        advantages=_advantages(answers, dimensions),
        gaps=gaps,
        questions_for_sales=_questions(answers, gaps, band),
        next_step=_next_step(band, answers),
        cited_sources=sorted(cited),
        caps_applied=caps,
    )


def rubric_definition() -> dict:
    """
    The published rubric, independent of any single assessment.

    Served at `/api/v1/fit-assessments/rubric/` so a prospect can see how they will be
    scored *before* answering, and so the scoring is auditable rather than a black box.
    """
    return {
        "version": RUBRIC_VERSION,
        "total_weight": 100,
        "dimensions": [
            {
                "key": "sovereignty",
                "label": "Data sovereignty and residency",
                "weight": 20,
                "what_it_measures": (
                    "Whether data-residency rules or internal policy require the platform "
                    "to run inside your own environment. This is weighted highest because "
                    "it is the clearest architectural reason to prefer a self-hosted "
                    "lakehouse over a managed one."
                ),
            },
            {
                "key": "infrastructure",
                "label": "Infrastructure and Kubernetes readiness",
                "weight": 18,
                "what_it_measures": (
                    "Whether you have somewhere to run IOMETE and the capability to operate "
                    "it. IOMETE installs as a Helm chart into Kubernetes you provide."
                ),
            },
            {
                "key": "use_case",
                "label": "Use-case alignment",
                "weight": 15,
                "what_it_measures": (
                    "How well your intended workloads map onto capabilities IOMETE "
                    "documents. Use cases resting on an unconfirmed capability score lower."
                ),
            },
            {
                "key": "operations",
                "label": "Operational capability and constraints",
                "weight": 13,
                "what_it_measures": (
                    "Team size, Kubernetes experience, timeline and budget constraints — "
                    "the day-2 factors that decide whether an implementation succeeds."
                ),
            },
            {
                "key": "scale",
                "label": "Data volume and workload scale",
                "weight": 12,
                "what_it_measures": (
                    "Whether your data volume justifies a lakehouse at all. Small volumes "
                    "score low here deliberately."
                ),
            },
            {
                "key": "current_pain",
                "label": "Current architecture and pain",
                "weight": 12,
                "what_it_measures": (
                    "Whether there is a problem worth a platform migration. Migrations fail "
                    "for lack of a driver more often than for lack of features."
                ),
            },
            {
                "key": "integration",
                "label": "Integration coverage of your existing stack",
                "weight": 10,
                "what_it_measures": (
                    "How much of what you already run is covered by an integration IOMETE "
                    "documents. Scored strictly: COMPASS will not credit a connector that "
                    "is not documented."
                ),
            },
        ],
        "bands": [
            {"band": band, "label": dict(FitBand.choices)[band], "explanation": explanation}
            for band, explanation in BAND_EXPLANATIONS.items()
        ],
        "band_thresholds": {
            "strong": "78 or above",
            "promising": "62–77",
            "conditional": "45–61",
            "limited": "below 45",
            "needs_discussion": "applied when too few questions were answered substantively",
        },
        "hard_caps": [
            "No Kubernetes capability caps the result at conditional, regardless of score.",
            "Under 1 TB with no residency requirement caps the result at conditional.",
            "No hosting model and no Kubernetes capability caps the result at "
            "needs-discussion.",
            "Fewer than three substantive answers caps the result at needs-discussion.",
        ],
        "disclaimer": DISCLAIMER,
        "sources": pk.load()["sources"],
    }
