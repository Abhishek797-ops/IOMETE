"""
Call preparation briefs.

The friction: a sales engineer has fifteen minutes before a call with a company they have
not researched. What they need is not a summary of IOMETE — they already know the product
— but a *prepared position*: what this particular buyer will ask, which of those questions
IOMETE's documentation actually answers, and which it does not.

The design constraint that makes this more than a text generator is the last part. Every
line of a brief carries a `status`, and the three that matter are:

* ``verified`` / ``vendor_claim`` — traceable to IOMETE's own published documentation,
  with the source ids attached. A ``vendor_claim`` is IOMETE's statement about itself and
  is always attributed as such rather than asserted as fact.
* ``assumed`` — inferred from what the rep typed (industry, size, stack), not from any
  source. Shown separately so the rep can see, before the call, exactly which parts of
  their brief are guesses about this company.
* ``unknown`` — public documentation does not answer it. These are **not** softened into
  plausible prose. They are collected into the questions the rep should take back to
  IOMETE, and counted.

``coverage`` reports that count, including an explicit unknown rate. A brief that admits
it cannot answer four of eleven likely questions is more useful fifteen minutes before a
call than one that answers all eleven and is wrong about three — the rep who repeats a
confident fabrication loses the deal at the technical evaluation, not in the meeting.

Nothing here invents pricing, savings, benchmarks, customers or SLAs; ``do_not_say`` is
built directly from the knowledge base's ``do_not_claim`` list and travels *with* the
brief, because the moment a rep most needs those guardrails is the moment they are
improvising an answer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from knowledge.services import product_knowledge as pk

BRIEF_VERSION = "1.0"

DISCLAIMER = (
    "This brief was assembled by IOMETE COMPASS from IOMETE's public documentation plus "
    "what you typed about the company. Lines marked 'assumed' are inferences from your "
    "inputs, not research about this company, and lines marked 'unknown' are questions "
    "the public documentation does not answer. Nothing here is a quotation, a commitment "
    "or an official IOMETE position. Confirm the open questions internally before the call."
)

#: Status vocabulary used across a brief. The first two mirror the knowledge base; the
#: last two are specific to a brief, because a brief mixes sourced product facts with
#: inferences about one company and must never blur them.
STATUS_SOURCED = ("verified", "vendor_claim", "needs_confirmation")
STATUS_ASSUMED = "assumed"
STATUS_UNKNOWN = "unknown"


# =====================================================================================
# Industry and stack profiles
# =====================================================================================

#: What each industry typically brings to the call. Deliberately coarse: these are
#: *assumptions about a sector*, surfaced as such, not research about the company. A rep
#: who sees "assumed" beside a line knows to verify it in the first five minutes.
INDUSTRY_PROFILES: dict[str, dict[str, Any]] = {
    "financial_services": {
        "label": "Financial services",
        "pressures": [
            "Data residency and regulatory audit are usually non-negotiable.",
            "Change control is formal; a platform that cannot be operated inside an "
            "existing change process is a procurement problem, not a technical one.",
        ],
        "lead_with": ["sovereignty", "governance", "open-formats"],
        "personas": ["security-compliance", "cto", "data-engineer"],
        "likely_blockers": [
            "An existing warehouse contract with time left to run.",
            "An internal platform team that will ask who operates Kubernetes.",
        ],
    },
    "healthcare": {
        "label": "Healthcare and life sciences",
        "pressures": [
            "Patient data handling usually forces an on-premises or private-cloud "
            "deployment.",
            "Procurement commonly requires a named compliance position before a technical "
            "evaluation starts.",
        ],
        "lead_with": ["sovereignty", "governance"],
        "personas": ["security-compliance", "cto"],
        "likely_blockers": [
            "Compliance sign-off ahead of any proof of concept.",
            "Limited platform engineering capacity.",
        ],
    },
    "public_sector": {
        "label": "Government and public sector",
        "pressures": [
            "Sovereignty is often a statutory requirement rather than a preference.",
            "Air-gapped or isolated-network deployment may be mandatory.",
        ],
        "lead_with": ["sovereignty", "open-formats", "deployment"],
        "personas": ["security-compliance", "cto", "business"],
        "likely_blockers": [
            "Open tender rules and long procurement cycles.",
            "A requirement to avoid single-vendor dependence.",
        ],
    },
    "telecom": {
        "label": "Telecommunications",
        "pressures": [
            "Event volumes are large and growing; storage cost is a board-level line.",
            "Existing Spark or Hadoop estates mean skills are transferable but migration "
            "is real work.",
        ],
        "lead_with": ["scale", "open-formats", "compute"],
        "personas": ["data-engineer", "cto"],
        "likely_blockers": [
            "An incumbent platform with sunk investment.",
            "Scepticism about yet another platform migration.",
        ],
    },
    "retail": {
        "label": "Retail and e-commerce",
        "pressures": [
            "Seasonal peaks make elastic compute the cost argument.",
            "Analytics and BI tooling is already embedded and must keep working.",
        ],
        "lead_with": ["compute", "analytics", "integrations"],
        "personas": ["data-analyst", "data-engineer", "business"],
        "likely_blockers": [
            "A BI estate nobody wants to re-point.",
            "Limited appetite for infrastructure ownership.",
        ],
    },
    "manufacturing": {
        "label": "Manufacturing and industrial",
        "pressures": [
            "Plant data often cannot leave the site, which forces hybrid or edge "
            "deployment.",
            "OT and IT ownership boundaries complicate who runs the platform.",
        ],
        "lead_with": ["sovereignty", "deployment"],
        "personas": ["cto", "data-engineer"],
        "likely_blockers": [
            "Unclear ownership between plant and central IT.",
            "Connectivity constraints at the site.",
        ],
    },
    "technology": {
        "label": "Technology and software",
        "pressures": [
            "The team will evaluate the architecture directly and ask about lock-in.",
            "Kubernetes capability is usually present, which removes the main objection.",
        ],
        "lead_with": ["open-formats", "compute", "deployment"],
        "personas": ["data-engineer", "cto"],
        "likely_blockers": [
            "A strong build-it-ourselves instinct.",
            "Comparison against assembling open source directly.",
        ],
    },
    "other": {
        "label": "Other or unknown sector",
        "pressures": [
            "Sector pressures are unknown — establish them in the first five minutes.",
        ],
        "lead_with": ["open-formats", "sovereignty"],
        "personas": ["cto", "data-engineer"],
        "likely_blockers": [
            "Unknown. Qualify before positioning.",
        ],
    },
}

#: Stack keywords that change what the rep should expect to be asked. Matching is on
#: lowercase substrings of whatever the rep typed, so "Snowflake (prod)" still matches.
STACK_SIGNALS: list[dict[str, Any]] = [
    {
        "match": ("snowflake", "bigquery", "redshift", "databricks", "synapse"),
        "signal": "They already run a managed cloud warehouse or lakehouse.",
        "implication": (
            "The conversation is a migration and a comparison, not a greenfield build. "
            "Expect questions about what moving actually involves and what breaks."
        ),
        "ask": "What specifically is not working about the current platform?",
    },
    {
        "match": ("hadoop", "hive", "cloudera", "hortonworks", "emr"),
        "signal": "There is an existing Hadoop or Hive estate.",
        "implication": (
            "Spark and Iceberg skills are largely transferable, which is a genuine "
            "advantage worth stating — and the team will know enough to test any claim."
        ),
        "ask": "Is the existing estate being decommissioned, or does this run alongside it?",
    },
    {
        "match": ("spark",),
        "signal": "They already run Apache Spark.",
        "implication": (
            "The compute engine is familiar, so the conversation moves quickly to "
            "operations, governance and table format."
        ),
        "ask": "Who operates the Spark estate today, and are they in this meeting?",
    },
    {
        "match": ("kubernetes", "k8s", "openshift", "eks", "aks", "gke", "rancher"),
        "signal": "Kubernetes is already in use.",
        "implication": (
            "This removes the single most common blocker. Say so early — it changes the "
            "shape of the whole evaluation."
        ),
        "ask": "Which team owns the clusters, and would they own this one?",
    },
    {
        "match": ("iceberg",),
        "signal": "They already use Apache Iceberg.",
        "implication": (
            "The table format argument is already won. Move to the platform services "
            "around it rather than re-explaining open formats."
        ),
        "ask": "Which catalogue are you using with Iceberg today?",
    },
    {
        "match": ("power bi", "powerbi", "tableau", "looker", "superset", "metabase", "qlik"),
        "signal": "There is an established BI estate.",
        "implication": (
            "Continuity matters more than capability here. Only claim an integration "
            "IOMETE actually documents — a wrong answer surfaces at the technical "
            "evaluation."
        ),
        "ask": "How many reports would have to be re-pointed, and who owns them?",
    },
    {
        "match": ("kafka", "kinesis", "pubsub", "event hub"),
        "signal": "Streaming ingestion is already in place.",
        "implication": (
            "Expect questions about how events land in tables and how fresh the data is."
        ),
        "ask": "What is the acceptable lag between an event and it being queryable?",
    },
    {
        "match": ("oracle", "sql server", "db2", "teradata"),
        "signal": "Significant legacy relational estate.",
        "implication": (
            "Expect questions about how operational data gets in, and expect a licence "
            "cost conversation you should not quantify on IOMETE's behalf."
        ),
        "ask": "Is the goal to offload reporting from these systems, or to replace them?",
    },
]

#: Objections a rep should be ready for, with the honest position on each. `status` is the
#: strongest thing COMPASS can say: several of these are deliberately `unknown`, because
#: the public documentation does not settle them and a rehearsed guess is worse than
#: "I will find out".
OBJECTIONS: list[dict[str, Any]] = [
    {
        "id": "who-operates-it",
        "objection": "We do not have a team to run Kubernetes.",
        "position": (
            "This is the real blocker and should be met directly rather than deflected. "
            "IOMETE deploys as a Helm chart into a Kubernetes cluster the customer "
            "provides, so somebody has to own that cluster."
        ),
        "status": "verified",
        "sources": ["S4", "S8"],
        "if_pressed": (
            "Establish whether they have a platform team at all. If not, that is a "
            "qualification finding, not an objection to overcome in the meeting."
        ),
    },
    {
        "id": "why-not-managed",
        "objection": "Why not just use a managed warehouse?",
        "position": (
            "Often they should, and saying so builds more credibility than arguing. The "
            "case for IOMETE is strongest when data cannot leave their control, or when "
            "they want open formats to avoid lock-in."
        ),
        "status": "verified",
        "sources": ["S3", "S7"],
        "if_pressed": (
            "Ask what happens if they need to move the data elsewhere in three years. "
            "That question separates a real sovereignty requirement from a preference."
        ),
    },
    {
        "id": "lock-in",
        "objection": "How do we know we are not locked into you?",
        "position": (
            "Data is stored as Apache Iceberg tables in object storage the customer owns, "
            "in open formats other engines can read."
        ),
        "status": "verified",
        "sources": ["S4", "S7"],
        "if_pressed": (
            "Offer the architecture walkthrough rather than a claim. The storage layout "
            "is the argument."
        ),
    },
    {
        "id": "cost",
        "objection": "What will this cost us compared to what we run now?",
        "position": (
            "Do not answer with a number. IOMETE publishes cost-efficiency claims on its "
            "own site, and those figures are not consistent between pages, so they can be "
            "cited only as the vendor's claim — never as a projection for this company."
        ),
        "status": "vendor_claim",
        "sources": ["S1", "S6"],
        "if_pressed": (
            "Offer to model it with their own volumes after the call. Any figure given in "
            "the meeting will be quoted back during procurement."
        ),
    },
    {
        "id": "scale-limits",
        "objection": "How far does this actually scale?",
        "position": (
            "Public documentation describes the scaling mechanisms but does not publish "
            "concurrency ceilings, maximum executor counts or throughput figures."
        ),
        "status": "unknown",
        "sources": ["S9"],
        "if_pressed": (
            "Say it is not published and take the specific workload shape back to IOMETE. "
            "Do not estimate."
        ),
    },
    {
        "id": "support",
        "objection": "What support and response times do we get?",
        "position": (
            "Support tiers and response commitments are commercial terms, not published "
            "product documentation."
        ),
        "status": "unknown",
        "sources": [],
        "if_pressed": "Route to IOMETE commercial. Do not improvise an SLA.",
    },
    {
        "id": "compliance",
        "objection": "Are you SOC 2 / HIPAA / GDPR compliant?",
        "position": (
            "IOMETE publishes statements on these on its own site. They are the vendor's "
            "statements and should be attributed that way, pointing the buyer at the "
            "trust centre rather than restating them as verified fact."
        ),
        "status": "vendor_claim",
        "sources": ["S1"],
        "if_pressed": (
            "Offer to get the current attestations. A compliance lead will ask for the "
            "document, not the claim."
        ),
    },
    {
        "id": "migration-effort",
        "objection": "How long would migrating take?",
        "position": (
            "There is no published migration timeline, and it depends entirely on their "
            "estate."
        ),
        "status": "unknown",
        "sources": [],
        "if_pressed": (
            "Offer a scoping session. A number guessed in the meeting becomes the "
            "deadline you are judged against."
        ),
    },
]

#: The opening lines. Short on purpose: a talk track that has to be read is not used.
OPENINGS: dict[str, str] = {
    "discovery": (
        "We are a data lakehouse that runs entirely inside your infrastructure. Before I "
        "describe anything, I want to understand where your data has to live and who "
        "operates your platform today."
    ),
    "demo": (
        "I will show you the platform running, but the part that matters for you is where "
        "it runs and who controls the data. Stop me when you want to go into that."
    ),
    "technical": (
        "This is built on Spark, Iceberg and Kubernetes — all open, nothing proprietary in "
        "the storage layer. I expect you will want to test that claim, so let us start "
        "wherever you are most sceptical."
    ),
    "business_case": (
        "The decision usually comes down to one question: does your data have to stay "
        "under your control? If it does, the comparison is not against a managed warehouse "
        "at all. If it does not, I will tell you that too."
    ),
    "follow_up": (
        "Last time we left some questions open. I have answers to the ones IOMETE "
        "documents publicly, and I have been straight about the ones it does not."
    ),
}


# =====================================================================================
# Result
# =====================================================================================


@dataclass
class BriefLine:
    """One statement in a brief, carrying its own provenance."""

    text: str
    status: str
    sources: list[str] = field(default_factory=list)
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "status": self.status,
            "sources": self.sources,
            "detail": self.detail,
        }


@dataclass
class CallBrief:
    company_name: str
    industry: str
    industry_label: str
    meeting_type: str
    headline: str
    opening: str
    inputs_given: list[dict[str, Any]]
    assumptions: list[dict[str, Any]]
    stack_signals: list[dict[str, Any]]
    lead_with: list[dict[str, Any]]
    likely_questions: list[dict[str, Any]]
    objections: list[dict[str, Any]]
    qualifying_questions: list[str]
    do_not_say: list[str]
    unknowns: list[dict[str, Any]]
    coverage: dict[str, Any]
    cited_sources: list[str]
    disclaimer: str
    brief_version: str


# =====================================================================================
# Builders
# =====================================================================================


def _normalise_stack(raw: list[str] | None) -> list[str]:
    return [item.strip() for item in (raw or []) if item and item.strip()]


def _match_stack(stack: list[str]) -> list[dict[str, Any]]:
    """Match what the rep typed against known signals, one hit per signal."""
    lowered = [item.lower() for item in stack]
    matched: list[dict[str, Any]] = []
    for signal in STACK_SIGNALS:
        hits = [
            original
            for original, low in zip(stack, lowered, strict=True)
            if any(token in low for token in signal["match"])
        ]
        if hits:
            matched.append(
                {
                    "matched_on": hits,
                    "signal": signal["signal"],
                    "implication": signal["implication"],
                    "ask": signal["ask"],
                    # An inference from what the rep typed, not a researched fact.
                    "status": STATUS_ASSUMED,
                }
            )
    return matched


def _capabilities_to_lead_with(profile: dict[str, Any], stack: list[str]) -> list[dict]:
    """
    Pick capabilities worth opening with.

    Drawn from the knowledge base and filtered to `verified` only: a call brief is exactly
    where an unverified capability would get stated as fact and then have to be walked
    back.
    """
    wanted_categories = {
        "sovereignty": ("security", "governance", "deployment"),
        "governance": ("governance", "security"),
        "open-formats": ("storage", "data-management"),
        "compute": ("compute",),
        "analytics": ("analytics",),
        "scale": ("compute", "storage"),
        "deployment": ("deployment",),
        "integrations": ("integration", "analytics"),
    }
    categories: set[str] = set()
    for key in profile["lead_with"]:
        categories.update(wanted_categories.get(key, ()))

    verified = pk.capabilities(status="verified")
    chosen: list[dict[str, Any]] = []
    for capability in verified:
        if capability.get("category") in categories:
            chosen.append(
                {
                    "name": capability["name"],
                    "why_now": capability.get("business_benefit", ""),
                    "limitation": capability.get("limitations", ""),
                    "status": capability.get("status", "verified"),
                    "sources": capability.get("sources", []),
                    "source_ids": [
                        source["id"]
                        for source in capability.get("sources", [])
                        if isinstance(source, dict) and "id" in source
                    ],
                }
            )
    # Enough to open with, not a feature dump. A rep reading ten bullets reads none.
    return chosen[:6]


def _likely_questions(profile: dict[str, Any], personas: list[str]) -> list[dict[str, Any]]:
    """
    What this buyer will probably ask, and what COMPASS can honestly answer.

    Two sources: the explainer questions (which already carry sourced answers) and each
    persona's own `questions_to_ask_iomete` — the latter are, by construction, the ones
    the knowledge base does *not* answer, so they come through as `unknown` and are
    counted as such rather than padded with plausible text.
    """
    knowledge = pk.load()
    selected = personas or profile["personas"]

    questions: list[dict[str, Any]] = []
    seen: set[str] = set()

    for entry in knowledge.get("explainer_questions", []):
        key = entry["question"].strip().lower()
        if key in seen:
            continue
        seen.add(key)
        questions.append(
            {
                "question": entry["question"],
                "answer": entry["answer"],
                "status": entry.get("status", "verified"),
                # Resolved refs, not bare ids: the brief is rendered directly and a
                # citation the reader cannot click is not a citation.
                "sources": pk.resolve_sources(entry.get("sources")),
                "source_ids": list(entry.get("sources", [])),
                "asked_by": "any",
            }
        )

    for persona_id in selected:
        persona = pk.get_persona(persona_id)
        if not persona:
            continue
        for question in persona.get("questions_to_ask_iomete", []):
            key = question.strip().lower()
            if key in seen:
                continue
            seen.add(key)
            questions.append(
                {
                    "question": question,
                    "answer": (
                        "Not answered by IOMETE's public documentation. Take this to "
                        "IOMETE rather than answering it in the meeting."
                    ),
                    "status": STATUS_UNKNOWN,
                    "sources": [],
                    "source_ids": [],
                    "asked_by": persona.get("label", persona_id),
                }
            )

    return questions


def _qualifying_questions(
    profile: dict[str, Any], stack_signals: list[dict[str, Any]], company_size: str
) -> list[str]:
    """What the rep should establish in the first five minutes."""
    questions = [
        "Does your data have to stay inside your own infrastructure — and is that a "
        "regulation, a policy, or a preference?",
        "Who operates your Kubernetes clusters today, and are they part of this decision?",
    ]
    questions.extend(signal["ask"] for signal in stack_signals)
    if company_size in {"small", "unknown", ""}:
        questions.append(
            "How many people would be available to operate this platform day to day?"
        )
    questions.append(
        "What would have to be true for you to move off whatever you run today?"
    )
    # Preserve order, drop repeats.
    return list(dict.fromkeys(questions))


def _coverage(
    questions: list[dict[str, Any]],
    objections: list[dict[str, Any]],
    assumptions: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    How much of this brief is actually sourced.

    The headline is `unknown_rate`. A rep should be able to see, before walking into the
    room, what proportion of the likely conversation COMPASS could not substantiate.
    """
    statuses = [item["status"] for item in questions] + [
        item["status"] for item in objections
    ]
    sourced = sum(1 for status in statuses if status in STATUS_SOURCED)
    unknown = sum(1 for status in statuses if status == STATUS_UNKNOWN)
    total = len(statuses)

    return {
        "total_statements": total,
        "sourced": sourced,
        "unknown": unknown,
        "assumed": len(assumptions),
        "unknown_rate": round(unknown / total, 3) if total else 0.0,
        "note": (
            "Every statement in this brief is counted. 'Sourced' means it traces to "
            "IOMETE's published documentation; 'unknown' means the documentation does "
            "not answer it and COMPASS declined to guess; 'assumed' counts inferences "
            "made from what you typed about the company rather than from any source."
        ),
    }


def prepare(payload: dict[str, Any]) -> CallBrief:
    """
    Build a call brief.

    Deterministic: the same inputs produce the same brief, and every product statement is
    pulled from the knowledge base rather than generated. That is the difference between
    this and asking a language model to write a call plan — the output can be audited, and
    the parts it cannot support are counted instead of smoothed over.
    """
    company_name = (payload.get("company_name") or "").strip() or "the company"
    industry = payload.get("industry") or "other"
    profile = INDUSTRY_PROFILES.get(industry, INDUSTRY_PROFILES["other"])
    meeting_type = payload.get("meeting_type") or "discovery"
    company_size = payload.get("company_size") or "unknown"
    stack = _normalise_stack(payload.get("known_stack"))
    personas = payload.get("attendee_personas") or []

    stack_signals = _match_stack(stack)
    lead_with = _capabilities_to_lead_with(profile, stack)
    questions = _likely_questions(profile, personas)

    inputs_given = [
        {"label": "Company", "value": company_name},
        {"label": "Industry", "value": profile["label"]},
        {"label": "Size", "value": company_size},
        {"label": "Meeting type", "value": meeting_type},
        {"label": "Stack you told us about", "value": ", ".join(stack) or "none given"},
    ]

    assumptions = [
        BriefLine(text=pressure, status=STATUS_ASSUMED).as_dict()
        for pressure in profile["pressures"]
    ]
    assumptions.extend(
        BriefLine(text=blocker, status=STATUS_ASSUMED).as_dict()
        for blocker in profile["likely_blockers"]
    )
    if not stack:
        assumptions.append(
            BriefLine(
                text=(
                    "No stack was supplied, so nothing in this brief is tailored to what "
                    "they actually run. Establish it early."
                ),
                status=STATUS_UNKNOWN,
            ).as_dict()
        )

    unknowns = [
        {
            "question": item["question"],
            "why": "IOMETE's public documentation does not answer this.",
            "asked_by": item.get("asked_by", "any"),
        }
        for item in questions
        if item["status"] == STATUS_UNKNOWN
    ]
    unknowns.extend(
        {
            "question": objection["objection"],
            "why": objection["position"],
            "asked_by": "any",
        }
        for objection in OBJECTIONS
        if objection["status"] == STATUS_UNKNOWN
    )

    # Collected from the raw id lists, never from the resolved records — mixing the two
    # is how a set of source ids ends up holding unhashable dicts.
    cited: set[str] = set()
    for item in questions:
        cited.update(item.get("source_ids", []))
    for capability in lead_with:
        cited.update(capability.get("source_ids", []))
    for objection in OBJECTIONS:
        cited.update(objection.get("sources", []))

    headline = (
        f"{company_name} — {profile['label'].lower()}, "
        f"{meeting_type.replace('_', ' ')} call"
    )

    return CallBrief(
        company_name=company_name,
        industry=industry,
        industry_label=profile["label"],
        meeting_type=meeting_type,
        headline=headline,
        opening=OPENINGS.get(meeting_type, OPENINGS["discovery"]),
        inputs_given=inputs_given,
        assumptions=assumptions,
        stack_signals=stack_signals,
        lead_with=lead_with,
        likely_questions=questions,
        objections=[
            {
                **objection,
                "sources": pk.resolve_sources(objection.get("sources")),
                "source_ids": list(objection.get("sources", [])),
            }
            for objection in OBJECTIONS
        ],
        qualifying_questions=_qualifying_questions(profile, stack_signals, company_size),
        do_not_say=pk.do_not_claim(),
        unknowns=unknowns,
        coverage=_coverage(questions, OBJECTIONS, assumptions),
        cited_sources=sorted(cited),
        disclaimer=DISCLAIMER,
        brief_version=BRIEF_VERSION,
    )


def industries() -> list[dict[str, str]]:
    """The industry options, for the form."""
    return [
        {"value": key, "label": profile["label"]}
        for key, profile in INDUSTRY_PROFILES.items()
    ]


def meeting_types() -> list[dict[str, str]]:
    return [
        {"value": "discovery", "label": "First discovery call"},
        {"value": "demo", "label": "Product demo"},
        {"value": "technical", "label": "Technical deep-dive"},
        {"value": "business_case", "label": "Business case / exec conversation"},
        {"value": "follow_up", "label": "Follow-up call"},
    ]
