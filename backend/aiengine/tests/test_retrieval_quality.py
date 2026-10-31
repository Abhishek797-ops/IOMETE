"""
Retrieval quality — acceptance tests 2, 3 and 4.

These assert *relevance outcomes*, not implementation details. A test that checked
"returns five results" would pass on a broken system; these check that the right ticket is
found when the words differ, that an exact error code measurably improves ranking, and
that an incompatible environment is gated rather than recommended.

They are only meaningful because the fixtures build tickets through the real intake
pipeline and because the default embedding provider is deterministic — so the numbers below
are reproducible rather than flaky thresholds.
"""

from __future__ import annotations

import pytest

from aiengine.services import normalization, ranking, retrieval
from tickets.models import Environment, GateStatus, TicketComponent
from tickets.services import lifecycle, similar

pytestmark = [pytest.mark.django_db, pytest.mark.retrieval, pytest.mark.acceptance]


def _resolve(ticket, reviewer, *, summary="Raised executor memory to 12g.", quality=5):
    lifecycle.record_resolution(
        ticket=ticket,
        user=reviewer,
        summary=summary,
        evidence="The job completed and OOMKilled no longer appears.",
        fde_investigation_minutes=120,
    )
    lifecycle.verify_resolution(ticket=ticket, reviewer=reviewer, quality=quality)
    ticket.refresh_from_db()
    return ticket


class TestParaphraseRecall:
    """
    Acceptance test 2: a paraphrased description still retrieves the relevant history.

    This is the test that justifies having a vector channel at all.
    """

    def test_paraphrased_ticket_finds_the_historical_case(
        self, make_ticket, org_a, customer_a, fde_lead
    ):
        historical = _resolve(
            make_ticket(
                organization=org_a,
                reporter=customer_a,
                title="Executors terminated repeatedly during the nightly risk aggregation",
                description=(
                    "The nightly aggregation over the transactions table fails after about "
                    "forty minutes. Executors start disappearing and the job never finishes."
                ),
            ),
            fde_lead,
        )

        # Deliberately different vocabulary: "worker processes" not "executors",
        # "batch summarisation" not "nightly aggregation", "shut down" not "terminated".
        paraphrased = make_ticket(
            organization=org_a,
            reporter=customer_a,
            title="Worker processes keep dying while the batch rollup runs",
            description=(
                "Whenever our overnight batch summarisation runs, the worker processes shut "
                "down before finishing and the job never completes."
            ),
            error_message="Container killed: OOMKilled (exit code 137)",
        )

        analysis = similar.analyse(ticket=paraphrased, user=customer_a, limit=5)
        references = [match.ticket.reference for match in analysis.ticket_matches]
        assert historical.reference in references, (
            f"The paraphrased ticket did not retrieve the historical case. Got {references}."
        )
        top = analysis.ticket_matches[0]
        assert top.ticket.reference == historical.reference
        assert top.offerable, "The correct match should be offerable as a lead."
        assert top.score.diagnosis_confidence > 0.4

    def test_paraphrase_without_any_error_code_still_retrieves(
        self, make_ticket, org_a, customer_a, fde_lead
    ):
        """
        The harder case: no error code at all, so the fingerprint channel contributes
        nothing and recall rests on the vector, lexical and metadata channels.
        """
        historical = _resolve(
            make_ticket(
                organization=org_a,
                reporter=customer_a,
                title="Executors terminated repeatedly during the nightly aggregation",
            ),
            fde_lead,
        )
        # Deliberately free of any extractable error token — no exception class, no
        # Kubernetes reason, and none of the prose aliases that normalisation canonicalises
        # (so no "out of memory", no "access denied"). This is what a report from someone
        # who has not looked at the logs actually looks like.
        vague = make_ticket(
            organization=org_a,
            reporter=customer_a,
            title="Our overnight job keeps failing with workers dying",
            description=(
                "The overnight job will not finish. The worker processes keep dying partway "
                "through and we have not managed to capture the exact message yet."
            ),
            error_message="",
        )
        assert not (vague.normalized or {}).get("error_codes"), (
            "This test needs a ticket with no extractable error code; normalisation found "
            f"{(vague.normalized or {}).get('error_codes')}."
        )
        analysis = similar.analyse(ticket=vague, user=customer_a, limit=5)
        references = [match.ticket.reference for match in analysis.ticket_matches]
        assert historical.reference in references

        # And the system should say that the strongest signal is missing, rather than
        # projecting false confidence.
        assert any("error code" in note.lower() for note in analysis.retrieval_notes), (
            analysis.retrieval_notes
        )
        assert any(
            "verbatim error" in question.lower() or "error line" in question.lower()
            for question in analysis.diagnostic_questions
        ), analysis.diagnostic_questions


class TestFingerprintLift:
    """
    Acceptance test 3: an exact error fingerprint measurably increases match relevance.

    Asserted as a *comparison* between two otherwise-identical queries — one with the exact
    error line, one without. Comparing against a fixed threshold would be fragile; comparing
    the two is the actual claim.
    """

    def test_exact_error_code_outranks_prose_only_similarity(
        self, make_ticket, org_a, customer_a, fde_lead
    ):
        # Decoy: prose that reads very like the query but a different error entirely.
        decoy = _resolve(
            make_ticket(
                organization=org_a,
                reporter=customer_a,
                title="Executors keep restarting during the nightly job run",
                description=(
                    "Our nightly job fails partway through. Executors are terminated "
                    "repeatedly and the job never finishes."
                ),
                error_message=(
                    "ExecutorLostFailure Reason: Container killed: Evicted "
                    "(the node was under disk pressure)"
                ),
            ),
            fde_lead,
            summary="Freed disk on the affected node.",
        )
        # Target: different prose, same error signature as the query will have.
        target = _resolve(
            make_ticket(
                organization=org_a,
                reporter=customer_a,
                title="Memory limit exceeded on the aggregation cluster",
                description="The aggregation cluster cannot complete its work.",
                error_message=(
                    "ExecutorLostFailure Reason: Container killed: OOMKilled (exit code 137)"
                ),
            ),
            fde_lead,
        )

        query = make_ticket(
            organization=org_a,
            reporter=customer_a,
            title="Executors keep restarting during the nightly job run",
            description=(
                "Our nightly job fails partway through. Executors are terminated repeatedly "
                "and the job never finishes."
            ),
            error_message=(
                "ExecutorLostFailure Reason: Container killed: OOMKilled (exit code 137)"
            ),
        )
        analysis = similar.analyse(ticket=query, user=customer_a, limit=5)
        scores = {match.ticket.reference: match.score for match in analysis.ticket_matches}

        assert target.reference in scores and decoy.reference in scores

        target_score = scores[target.reference]
        decoy_score = scores[decoy.reference]

        # The decoy legitimately shares `ExecutorLostFailure`, so it earns a partial
        # fingerprint score — that is correct behaviour, not a bug. The claim being tested
        # is that *more* exact error overlap produces a higher score, so this compares the
        # two rather than demanding a zero the data does not support.
        target_fingerprint = target_score.channel_scores.get("fingerprint", 0)
        decoy_fingerprint = decoy_score.channel_scores.get("fingerprint", 0)
        assert target_fingerprint > decoy_fingerprint, (
            f"Full error-signature overlap ({target_fingerprint}) should outscore partial "
            f"overlap ({decoy_fingerprint})."
        )

        # And that lifts diagnosis confidence above the prose-alike decoy, even though the
        # decoy's wording is a verbatim match for the query's.
        assert target_score.diagnosis_confidence > decoy_score.diagnosis_confidence, (
            f"target diag={target_score.diagnosis_confidence} "
            f"decoy diag={decoy_score.diagnosis_confidence}"
        )

    def test_identical_error_signature_yields_the_strongest_evidence_label(
        self, make_ticket, org_a, customer_a, fde_lead
    ):
        historical = _resolve(make_ticket(organization=org_a, reporter=customer_a), fde_lead)
        query = make_ticket(organization=org_a, reporter=customer_a)
        analysis = similar.analyse(ticket=query, user=customer_a, limit=3)
        match = next(
            m for m in analysis.ticket_matches if m.ticket.reference == historical.reference
        )
        kinds = {item.kind for item in match.score.evidence}
        assert "error_fingerprint" in kinds or "error_codes" in kinds
        strong = [
            item for item in match.score.evidence
            if item.kind in {"error_fingerprint", "symptoms"} and item.strength == "strong"
        ]
        assert strong, [item.to_dict() for item in match.score.evidence]


class TestCompatibilityGate:
    """
    Acceptance test 4: a similar error on an incompatible version or environment is not
    blindly recommended.
    """

    def test_incompatible_version_penalises_a_historical_match(
        self, make_ticket, org_a, org_legacy, customer_a, customer_legacy, fde_lead
    ):
        legacy = _resolve(
            make_ticket(organization=org_legacy, reporter=customer_legacy), fde_lead
        )
        query = make_ticket(organization=org_a, reporter=customer_a)

        # An FDE sees across tenants, which is how the version mismatch becomes visible.
        analysis = similar.analyse(ticket=query, user=fde_lead, limit=8)
        match = next(
            (m for m in analysis.ticket_matches if m.ticket.reference == legacy.reference),
            None,
        )
        assert match is not None, "Cross-tenant match should be retrievable by an FDE."
        assert match.score.gate_status == GateStatus.PENALISED
        assert "version" in match.score.gate_reason.lower()

    def test_gated_playbook_is_not_recommended_and_escalates_instead(
        self, make_ticket, org_legacy, customer_legacy, make_playbook, fde_lead
    ):
        """
        A playbook declared for >=3.0 must not be offered to a 2.4.0 cluster — and the
        recommendation must become `escalate` rather than silently degrading to
        "have a look around".
        """
        make_playbook(reviewer=fde_lead, approve=True, applicable_versions=">=3.0,<4.0")
        ticket = make_ticket(organization=org_legacy, reporter=customer_legacy)

        analysis = similar.analyse(ticket=ticket, user=customer_legacy, limit=5)
        gated = [
            match for match in analysis.playbook_matches
            if match.score.gate_status == GateStatus.GATED
        ]
        assert gated, "The version-incompatible playbook should have been gated."
        assert analysis.recommended_playbook is None
        assert analysis.recommendation == "escalate"
        assert "not applicable" in analysis.recommendation_reason.lower()

    def test_environment_mismatch_gates_a_playbook(
        self, make_ticket, org_a, customer_a, make_playbook, fde_lead
    ):
        make_playbook(
            reviewer=fde_lead,
            approve=True,
            applicable_environments=["development"],
        )
        ticket = make_ticket(
            organization=org_a, reporter=customer_a, environment=Environment.PRODUCTION
        )
        analysis = similar.analyse(ticket=ticket, user=customer_a, limit=5)
        gated = [
            match for match in analysis.playbook_matches
            if match.score.gate_status == GateStatus.GATED
        ]
        assert gated
        assert "environment" in gated[0].score.gate_reason.lower()

    def test_unknown_version_is_treated_as_not_applicable(
        self, make_ticket, org_a, customer_a, make_playbook, fde_lead
    ):
        """
        Unknown must mean "do not recommend", not "probably fine". This is the conservative
        default the whole gate depends on.
        """
        make_playbook(reviewer=fde_lead, approve=True, applicable_versions=">=3.0,<4.0")
        ticket = make_ticket(organization=org_a, reporter=customer_a, iomete_version="")
        ticket.iomete_version = ""
        ticket.save(update_fields=["iomete_version"])

        analysis = similar.analyse(ticket=ticket, user=customer_a, limit=5)
        assert analysis.recommended_playbook is None
        gated = [
            match for match in analysis.playbook_matches
            if match.score.gate_status == GateStatus.GATED
        ]
        assert gated
        assert "unknown" in gated[0].score.gate_reason.lower()
        assert any("version" in q.lower() for q in analysis.diagnostic_questions)


class TestScoreSeparation:
    """
    The three confidences must remain distinct concepts. If they ever collapse into one
    number, the product's central claim is false.
    """

    def test_a_well_fixed_but_unrelated_match_scores_low_resolution_confidence(
        self, make_ticket, org_a, customer_a, fde_lead
    ):
        unrelated = _resolve(
            make_ticket(
                organization=org_a,
                reporter=customer_a,
                title="Table disappeared from the catalog after a failed migration",
                description="A table we query daily is no longer visible in the catalog.",
                error_message=(
                    "org.apache.iceberg.exceptions.NoSuchTableException: Table does not "
                    "exist: lakehouse.risk.exposure"
                ),
                component=TicketComponent.ICEBERG_METADATA,
            ),
            fde_lead,
            summary="Re-registered the table against the last good metadata file.",
            quality=5,
        )
        query = make_ticket(organization=org_a, reporter=customer_a)
        analysis = similar.analyse(ticket=query, user=customer_a, limit=6)

        match = next(
            (m for m in analysis.ticket_matches if m.ticket.reference == unrelated.reference),
            None,
        )
        if match is None:
            pytest.skip("The unrelated ticket was not retrieved at all, which is also correct.")

        # Its fix was verified and high quality, but it is a different problem — so
        # resolution confidence must be low, and it must not be offered as a lead.
        assert match.score.diagnosis_confidence < 0.25
        assert match.score.resolution_confidence < 0.35, (
            "A verified fix for an unrelated problem must not read as actionable here."
        )
        assert not match.offerable

    def test_scores_are_never_asserted_as_certainty(
        self, make_ticket, org_a, customer_a, fde_lead
    ):
        _resolve(make_ticket(organization=org_a, reporter=customer_a), fde_lead)
        query = make_ticket(organization=org_a, reporter=customer_a)
        analysis = similar.analyse(ticket=query, user=customer_a, limit=3)
        for match in analysis.ticket_matches:
            assert match.score.diagnosis_confidence <= ranking.MAX_DIAGNOSIS_CONFIDENCE
            assert match.score.resolution_confidence <= ranking.MAX_RESOLUTION_CONFIDENCE

    def test_every_match_carries_explanatory_evidence(
        self, make_ticket, org_a, customer_a, fde_lead
    ):
        _resolve(make_ticket(organization=org_a, reporter=customer_a), fde_lead)
        query = make_ticket(organization=org_a, reporter=customer_a)
        analysis = similar.analyse(ticket=query, user=customer_a, limit=3)
        assert analysis.ticket_matches
        for match in analysis.ticket_matches:
            assert match.score.evidence, f"{match.ticket.reference} has no evidence."
            for item in match.score.evidence:
                assert item.label and item.detail
                assert item.strength in {"strong", "moderate", "weak", "negative"}


class TestHybridChannels:
    def test_all_four_channels_are_exercised(
        self, make_ticket, org_a, customer_a, fde_lead
    ):
        _resolve(make_ticket(organization=org_a, reporter=customer_a), fde_lead)
        query = make_ticket(organization=org_a, reporter=customer_a)
        analysis = similar.analyse(ticket=query, user=customer_a, limit=5)
        counts = analysis.retrieval_run.channel_counts
        assert set(counts) == {"vector", "lexical", "fingerprint", "metadata"}
        assert sum(counts.values()) > 0
        # Every channel should contribute for a ticket this similar.
        assert all(counts[channel] > 0 for channel in counts), counts

    def test_backend_is_reported_truthfully(self, make_ticket, org_a, customer_a):
        described = retrieval.describe_vector_backend()
        assert described["vector_backend"] in {"pgvector", "numpy"}
        assert described["vector_backend_reason"]
        # On the test database (SQLite) it must report numpy, not pgvector.
        assert described["vector_backend"] == "numpy"

    def test_only_resolved_tickets_are_retrievable_as_precedent(
        self, make_ticket, org_a, customer_a
    ):
        """An open ticket has no verified outcome, so it is not precedent."""
        open_ticket = make_ticket(
            organization=org_a, reporter=customer_a, title="An unresolved open incident"
        )
        query = make_ticket(organization=org_a, reporter=customer_a)
        analysis = similar.analyse(ticket=query, user=customer_a, limit=5)
        references = [match.ticket.reference for match in analysis.ticket_matches]
        assert open_ticket.reference not in references


class TestNormalizationFeatures:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("Container killed: OOMKilled (exit code 137)", "OOMKilled"),
            ("Pod is in CrashLoopBackOff", "CrashLoopBackOff"),
            (
                "org.apache.iceberg.exceptions.CommitFailedException: stale metadata",
                "CommitFailedException",
            ),
            ("FailedScheduling: 0/6 nodes are available", "FailedScheduling"),
            ("RangerAccessControlException: Permission denied", "RangerAccessControlException"),
            ("AmazonS3Exception: Access Denied (Status Code: 403)", "AccessDenied"),
        ],
    )
    def test_error_codes_are_extracted(self, text, expected):
        assert expected in normalization.extract_error_codes(text)

    @pytest.mark.parametrize(
        "text,symptom",
        [
            ("Executors keep restarting", "executor_restarting"),
            ("Worker processes shut down before finishing", "executor_restarting"),
            ("The workers keep dying mid-query", "executor_restarting"),
            ("We are seeing out of memory errors", "out_of_memory"),
            ("Permission denied on the table", "permission_denied"),
            ("Table does not exist in the catalog", "table_not_found"),
            ("Queries are extremely slow", "query_slow"),
            ("Ingestion has stalled", "ingestion_stalled"),
        ],
    )
    def test_symptoms_are_extracted(self, text, symptom):
        assert symptom in normalization.extract_symptoms(text)

    def test_category_is_unknown_rather_than_guessed(self):
        """An honest `unknown` beats a confident wrong category poisoning the metadata channel."""
        result = normalization.normalize(
            title="A question about the platform",
            description="How do I invite a colleague to my organization?",
        )
        assert result.category == "unknown"
        assert result.error_codes == []

    def test_declared_component_is_respected(self):
        result = normalization.normalize(
            title="Something is wrong with storage",
            description="The bucket seems unreachable from the cluster.",
            declared_component=TicketComponent.JUPYTER,
        )
        assert result.component == TicketComponent.JUPYTER
