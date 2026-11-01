"""
Fit assessment and architecture recommendation.

The brief forbids misleading compatibility percentages, so these tests defend the opposite
property: the score is always accompanied by a published rubric, the band is capped when a
disqualifying constraint exists, gaps are never empty, and the diagram distinguishes
documented product behaviour from COMPASS's own conceptual placement.
"""

from __future__ import annotations

import pytest

from prospects.models import (
    CompanyType,
    CurrentArchitecture,
    DataVolume,
    FitBand,
    InfrastructureLocation,
    SovereigntyRequirement,
    UseCase,
)
from prospects.services import architecture as architecture_service
from prospects.services import fit as fit_service

STRONG_ANSWERS = {
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
    "challenges": ["data_residency", "cost", "duplicate_copies"],
    "current_architecture": CurrentArchitecture.BOTH,
    "constraints": [],
    "kubernetes_maturity": "production",
    "team_size": "dedicated platform team",
}


class TestTheRubricIsPublished:
    def test_the_rubric_sums_to_one_hundred(self):
        definition = fit_service.rubric_definition()
        assert definition["total_weight"] == 100
        assert sum(d["weight"] for d in definition["dimensions"]) == 100

    def test_every_dimension_explains_what_it_measures(self):
        for dimension in fit_service.rubric_definition()["dimensions"]:
            assert dimension["key"]
            assert dimension["label"]
            assert len(dimension["what_it_measures"]) > 60, dimension["key"]

    def test_the_bands_and_caps_are_documented(self):
        definition = fit_service.rubric_definition()
        assert len(definition["bands"]) == 5
        assert definition["band_thresholds"]
        assert definition["hard_caps"]
        assert definition["disclaimer"]

    def test_the_rubric_cites_the_knowledge_base_sources(self):
        assert fit_service.rubric_definition()["sources"]

    def test_the_rubric_is_public(self, api, db):
        response = api.get("/api/v1/fit-assessments/rubric/")
        assert response.status_code == 200
        assert response.data["total_weight"] == 100
        assert response.data["hard_caps"]


class TestAssessmentShape:
    def test_an_assessment_always_publishes_its_rubric_breakdown(self):
        result = fit_service.assess(STRONG_ANSWERS)
        assert len(result.rubric) == 7
        for entry in result.rubric:
            assert entry["dimension"]
            assert entry["weight"] > 0
            assert 0 <= entry["awarded"] <= entry["max"]
            assert entry["reasoning"], entry["dimension"]

    def test_the_awarded_points_match_the_headline_score(self):
        result = fit_service.assess(STRONG_ANSWERS)
        assert result.score == round(sum(e["awarded"] for e in result.rubric))

    def test_the_disclaimer_states_it_is_indicative(self):
        result = fit_service.assess(STRONG_ANSWERS)
        assert "indicative" in result.disclaimer.lower()
        assert "not an official iomete" in result.disclaimer.lower()

    def test_gaps_are_never_empty_even_for_an_ideal_prospect(self):
        """An assessment with no limitations is marketing, not an assessment."""
        result = fit_service.assess(STRONG_ANSWERS)
        assert result.band == FitBand.STRONG
        assert result.gaps, "Even a strong fit must carry honest limitations."
        gap_text = " ".join(gap["gap"] + gap["detail"] for gap in result.gaps).lower()
        assert "own the operations" in gap_text
        assert "vendor claim" in gap_text

    def test_every_gap_offers_a_mitigation(self):
        result = fit_service.assess(STRONG_ANSWERS)
        for gap in result.gaps:
            assert gap["mitigation"], gap["gap"]
            assert gap["severity"] in {"high", "medium", "low"}

    def test_questions_for_sales_are_produced(self):
        result = fit_service.assess(STRONG_ANSWERS)
        assert 3 <= len(result.questions_for_sales) <= 8
        assert all(question.endswith("?") for question in result.questions_for_sales)

    def test_technical_requirements_list_the_unglamorous_prerequisites(self):
        """
        A prospect who discovers the PostgreSQL requirement during implementation is a
        prospect who feels misled.
        """
        result = fit_service.assess(STRONG_ANSWERS)
        requirements = " ".join(
            item["requirement"] + item["detail"] for item in result.technical_requirements
        ).lower()
        for expected in ("kubernetes", "object storage", "postgresql", "ingress"):
            assert expected in requirements, f"{expected} is not stated as a requirement"

    def test_every_requirement_and_advantage_carries_a_status(self):
        result = fit_service.assess(STRONG_ANSWERS)
        for collection in (result.technical_requirements, result.advantages):
            for item in collection:
                assert item["status"] in {"verified", "needs_confirmation", "vendor_claim"}

    def test_cited_sources_resolve_to_the_knowledge_base(self):
        from knowledge.services.product_knowledge import load

        known = {source["id"] for source in load()["sources"]}
        result = fit_service.assess(STRONG_ANSWERS)
        assert result.cited_sources
        for reference in result.cited_sources:
            assert reference in known

    def test_the_assessment_is_deterministic(self):
        """
        The same answers must always produce the same assessment, because a prospect
        downloads the report and quotes it in a meeting three weeks later.
        """
        first = fit_service.assess(STRONG_ANSWERS)
        second = fit_service.assess(STRONG_ANSWERS)
        assert first.score == second.score
        assert first.band == second.band
        assert first.rubric == second.rubric


class TestHardCapsOverrideTheArithmetic:
    def test_no_kubernetes_capability_caps_the_band(self):
        """
        Self-hosting is the product's central requirement. A prospect who cannot host it is
        not a "strong fit with an asterisk".
        """
        answers = {**STRONG_ANSWERS, "kubernetes_maturity": "none", "team_size": "small"}
        result = fit_service.assess(answers)
        assert fit_service._band_rank(result.band) <= fit_service._band_rank(
            FitBand.CONDITIONAL
        )
        assert any("kubernetes" in cap.lower() for cap in result.caps_applied)

    def test_small_volume_without_a_residency_driver_is_capped(self):
        answers = {
            **STRONG_ANSWERS,
            "data_volume": DataVolume.UNDER_1TB,
            "sovereignty_requirement": SovereigntyRequirement.NONE,
        }
        result = fit_service.assess(answers)
        assert fit_service._band_rank(result.band) <= fit_service._band_rank(
            FitBand.CONDITIONAL
        )
        assert any("1 tb" in cap.lower() for cap in result.caps_applied)

    def test_too_few_answers_yields_needs_discussion(self):
        result = fit_service.assess(
            {
                "company_type": CompanyType.OTHER,
                "infrastructure_location": InfrastructureLocation.UNDECIDED,
                "data_volume": DataVolume.UNKNOWN,
                "primary_use_case": UseCase.OTHER,
                "sovereignty_requirement": SovereigntyRequirement.UNKNOWN,
                "current_architecture": CurrentArchitecture.NONE,
            }
        )
        assert result.band == FitBand.NEEDS_DISCUSSION
        assert result.caps_applied

    def test_a_poor_fit_is_told_so_plainly(self):
        """
        Saying "this is not for you" is more useful than a sales conversation that
        disappoints later.
        """
        result = fit_service.assess(
            {
                "company_type": CompanyType.STARTUP,
                "company_name": "Tiny Co",
                "infrastructure_location": InfrastructureLocation.PUBLIC_CLOUD,
                "cloud_providers": ["aws"],
                "current_systems": ["PostgreSQL"],
                "data_volume": DataVolume.UNDER_1TB,
                "primary_use_case": UseCase.BI_REPORTING,
                "sovereignty_requirement": SovereigntyRequirement.NONE,
                "challenges": [],
                "current_architecture": CurrentArchitecture.DATABASES_ONLY,
                "constraints": ["limited_budget", "small_team"],
                "kubernetes_maturity": "none",
                "team_size": "small",
            }
        )
        assert fit_service._band_rank(result.band) <= fit_service._band_rank(
            FitBand.CONDITIONAL
        )
        assert "managed" in result.next_step.lower() or "conditional" in result.next_step.lower()

    def test_a_strong_prospect_is_recognised(self):
        result = fit_service.assess(STRONG_ANSWERS)
        assert result.band == FitBand.STRONG
        assert result.caps_applied == []
        assert "deep-dive" in result.next_step.lower()


class TestUnconfirmedCapabilitiesAreFlagged:
    def test_a_streaming_use_case_raises_the_connector_question(self):
        answers = {**STRONG_ANSWERS, "primary_use_case": UseCase.REAL_TIME}
        result = fit_service.assess(answers)
        gap_text = " ".join(gap["gap"] + gap["detail"] for gap in result.gaps).lower()
        assert "streaming connector" in gap_text or "kafka" in gap_text
        assert any("streaming" in q.lower() for q in result.questions_for_sales)

    def test_an_air_gapped_prospect_is_told_it_is_unconfirmed(self):
        answers = {
            **STRONG_ANSWERS,
            "infrastructure_location": InfrastructureLocation.AIR_GAPPED,
        }
        result = fit_service.assess(answers)
        unconfirmed = [
            item for item in result.technical_requirements
            if item["status"] == "needs_confirmation"
        ]
        assert unconfirmed
        assert any("air-gapped" in item["requirement"].lower() for item in unconfirmed)
        assert any("air-gapped" in q.lower() for q in result.questions_for_sales)

    def test_unlisted_systems_are_not_credited_as_integrations(self):
        answers = {
            **STRONG_ANSWERS,
            "current_systems": ["Teradata", "SAP HANA", "Informatica"],
        }
        result = fit_service.assess(answers)
        integration = next(
            entry for entry in result.rubric if entry["dimension"] == "integration"
        )
        assert "need confirmation" in integration["reasoning"].lower()
        assert integration["awarded"] < integration["max"]


class TestArchitectureRecommendation:
    def test_every_node_declares_its_claim_status(self):
        graph = architecture_service.generate(STRONG_ANSWERS)
        assert graph.nodes
        valid = {
            "documented", "documented_integration", "customer_system", "conceptual",
            "needs_confirmation",
        }
        for node in graph.nodes:
            assert node["claim_status"] in valid, node

    def test_the_legend_explains_every_status_used(self):
        graph = architecture_service.generate(STRONG_ANSWERS)
        legend_statuses = {entry["claim_status"] for entry in graph.legend}
        used = {node["claim_status"] for node in graph.nodes}
        assert used <= legend_statuses

    def test_iomete_components_are_documented_and_cited(self):
        graph = architecture_service.generate(STRONG_ANSWERS)
        documented = [
            node for node in graph.nodes if node["claim_status"] == "documented"
        ]
        assert len(documented) >= 8
        for node in documented:
            assert node["sources"], f"{node['id']} is marked documented but cites nothing"
            assert node["sources"][0]["url"].startswith("https://iomete.com")

    def test_customer_systems_make_no_product_claim(self):
        graph = architecture_service.generate(STRONG_ANSWERS)
        customer_nodes = [
            node for node in graph.nodes if node["claim_status"] == "customer_system"
        ]
        assert customer_nodes, "The prospect's own systems should appear."
        for node in customer_nodes:
            assert "you told us" in node["description"].lower()

    def test_the_disclaimer_separates_documented_from_conceptual(self):
        graph = architecture_service.generate(STRONG_ANSWERS)
        disclaimer = graph.conceptual_disclaimer.lower()
        assert "documented" in disclaimer
        assert "conceptual" in disclaimer
        # And explicitly denies that IOMETE replaces the existing estate.
        assert "does not replace" in disclaimer

    def test_the_core_data_path_is_present(self):
        graph = architecture_service.generate(STRONG_ANSWERS)
        node_ids = {node["id"] for node in graph.nodes}
        for expected in (
            "storage", "iceberg-tables", "iceberg-rest-catalog", "compute-clusters",
            "iom-gateway", "kubernetes", "postgresql",
        ):
            assert expected in node_ids, f"{expected} missing from the graph"

        edges = {(edge["source"], edge["target"]) for edge in graph.edges}
        assert ("storage", "iceberg-tables") in edges
        assert ("iceberg-tables", "iceberg-rest-catalog") in edges
        assert ("iceberg-rest-catalog", "compute-clusters") in edges

    def test_every_edge_connects_two_declared_nodes(self):
        """A dangling edge renders as a line into nowhere in React Flow."""
        graph = architecture_service.generate(STRONG_ANSWERS)
        node_ids = {node["id"] for node in graph.nodes}
        for edge in graph.edges:
            assert edge["source"] in node_ids, edge
            assert edge["target"] in node_ids, edge

    def test_every_node_sits_in_a_declared_layer(self):
        graph = architecture_service.generate(STRONG_ANSWERS)
        layer_ids = {layer["id"] for layer in graph.layers}
        for node in graph.nodes:
            assert node["layer"] in layer_ids, node

    def test_an_unconfirmed_source_is_flagged_and_raises_a_question(self):
        answers = {**STRONG_ANSWERS, "current_systems": ["Kafka", "PostgreSQL"]}
        graph = architecture_service.generate(answers)
        kafka_edges = [
            edge for edge in graph.edges if "kafka" in edge["source"].lower()
        ]
        assert kafka_edges
        assert kafka_edges[0]["claim_status"] == "needs_confirmation"
        assert any("kafka" in question.lower() for question in graph.open_questions)

    def test_a_raw_database_is_a_conceptual_placement_not_a_connector(self):
        """
        dbt is a documented integration; a bare PostgreSQL reached by a Spark job the
        customer writes is not. Conflating the two would be a promise nobody made.
        """
        graph = architecture_service.generate(
            {**STRONG_ANSWERS, "current_systems": ["PostgreSQL", "dbt"]}
        )
        by_mechanism = {note["system"]: note for note in graph.integration_notes}
        assert by_mechanism["PostgreSQL"]["claim_status"] == "conceptual"
        assert by_mechanism["dbt"]["claim_status"] == "documented_integration"

    def test_the_storage_node_matches_the_stated_cloud(self):
        aws = architecture_service.generate(
            {**STRONG_ANSWERS, "cloud_providers": ["aws"],
             "infrastructure_location": InfrastructureLocation.PUBLIC_CLOUD}
        )
        node = next(node for node in aws.nodes if node["id"] == "storage")
        assert "S3" in node["label"]
        assert node["detail"]["uri_scheme"] == "s3a://"

        azure = architecture_service.generate(
            {**STRONG_ANSWERS, "cloud_providers": ["azure"],
             "infrastructure_location": InfrastructureLocation.PUBLIC_CLOUD}
        )
        node = next(node for node in azure.nodes if node["id"] == "storage")
        assert "Azure" in node["label"]
        assert node["detail"]["uri_scheme"] == "abfs://"

    def test_open_questions_always_include_operational_ownership(self):
        graph = architecture_service.generate(STRONG_ANSWERS)
        assert any("operate" in question.lower() for question in graph.open_questions)

    def test_the_reference_architecture_is_labelled_illustrative(self):
        reference = architecture_service.reference_architecture()
        assert reference["is_illustrative"] is True
        assert "illustrative examples" in reference["conceptual_disclaimer"]
        assert reference["nodes"]
        assert reference["legend"]


@pytest.mark.django_db
class TestTheProspectApi:
    def test_an_anonymous_assessment_works_without_contact_details(self, api):
        response = api.post(
            "/api/v1/fit-assessments/",
            {"answers": STRONG_ANSWERS},
            format="json",
        )
        assert response.status_code == 201, response.data
        assessment = response.data["assessment"]
        assert assessment["band"] == FitBand.STRONG
        assert assessment["rubric"]
        assert assessment["gaps"]
        assert assessment["score_caveat"]
        assert "not a compatibility percentage" in assessment["score_caveat"]
        # The architecture is generated in the same call.
        assert response.data["architecture"]["nodes"]
        assert response.data["legend"]

    def test_contact_details_require_consent(self, api):
        response = api.post(
            "/api/v1/fit-assessments/",
            {
                "answers": STRONG_ANSWERS,
                "contact_email": "someone@example.com",
                "consent_given": False,
            },
            format="json",
        )
        assert response.status_code == 400
        assert "consent" in str(response.data).lower()

    def test_consent_is_stored_with_the_exact_wording_shown(self, api):
        from prospects.models import ProspectProfile
        from prospects.serializers import CONSENT_TEXT

        response = api.post(
            "/api/v1/fit-assessments/",
            {
                "answers": STRONG_ANSWERS,
                "contact_name": "Ingrid Halvorsen",
                "contact_email": "ingrid@example.com",
                "consent_given": True,
            },
            format="json",
        )
        assert response.status_code == 201
        profile = ProspectProfile.objects.get(contact_email="ingrid@example.com")
        assert profile.consent_given is True
        assert profile.consent_text == CONSENT_TEXT
        assert profile.consent_at is not None

    def test_an_assessment_is_retrievable_by_its_own_link(self, api):
        created = api.post(
            "/api/v1/fit-assessments/", {"answers": STRONG_ANSWERS}, format="json"
        )
        assessment_id = created.data["assessment"]["id"]
        response = api.get(f"/api/v1/fit-assessments/{assessment_id}/")
        assert response.status_code == 200
        assert response.data["band"] == FitBand.STRONG

    def test_listing_assessments_is_staff_only(self, api, auth_client, customer_a, fde):
        """Public listing would enumerate every prospect's answers."""
        assert api.get("/api/v1/fit-assessments/").status_code == 401
        assert auth_client(customer_a).get("/api/v1/fit-assessments/").status_code == 403
        assert auth_client(fde).get("/api/v1/fit-assessments/").status_code == 200

    def test_the_report_payload_contains_everything_needed_to_render_it(self, api):
        created = api.post(
            "/api/v1/fit-assessments/", {"answers": STRONG_ANSWERS}, format="json"
        )
        assessment_id = created.data["assessment"]["id"]
        response = api.get(f"/api/v1/fit-assessments/{assessment_id}/report/")
        assert response.status_code == 200
        for key in ("assessment", "architecture", "legend", "rubric_definition",
                    "sources", "status_legend", "disclaimer", "generated_at"):
            assert key in response.data, key
        assert response.data["sources"]

    def test_architecture_can_be_generated_standalone(self, api):
        response = api.post(
            "/api/v1/architecture/generate/", {"answers": STRONG_ANSWERS}, format="json"
        )
        assert response.status_code == 200
        assert response.data["nodes"]
        assert response.data["legend"]
        assert response.data["conceptual_disclaimer"]

    def test_the_reference_architecture_is_public(self, api):
        response = api.get("/api/v1/architecture/reference/")
        assert response.status_code == 200
        assert response.data["is_illustrative"] is True

    def test_a_demo_request_attaches_the_assessment(self, api):
        created = api.post(
            "/api/v1/fit-assessments/", {"answers": STRONG_ANSWERS}, format="json"
        )
        assessment_id = created.data["assessment"]["id"]
        response = api.post(
            "/api/v1/demo-requests/",
            {
                "contact_name": "Ingrid Halvorsen",
                "contact_email": "ingrid@meridian.example",
                "company_name": "Meridian Insurance",
                "message": "We cannot use a hosted service for regulatory reasons.",
                "assessment": assessment_id,
                "consent_given": True,
            },
            format="json",
        )
        assert response.status_code == 201, response.data
        assert str(response.data["assessment"]) == str(assessment_id)
        assert "fit assessment" in response.data["confirmation"]

    def test_a_demo_request_requires_consent(self, api):
        response = api.post(
            "/api/v1/demo-requests/",
            {
                "contact_name": "A",
                "contact_email": "a@example.com",
                "company_name": "A Co",
                "consent_given": False,
            },
            format="json",
        )
        assert response.status_code == 400

    def test_internal_notes_are_not_returned_to_a_prospect(self, api, auth_client, fde):
        created = api.post(
            "/api/v1/demo-requests/",
            {
                "contact_name": "A",
                "contact_email": "a@example.com",
                "company_name": "A Co",
                "consent_given": True,
            },
            format="json",
        )
        assert "internal_notes" not in created.data

        request_id = created.data["id"]
        auth_client(fde).patch(
            f"/api/v1/demo-requests/{request_id}/",
            {"internal_notes": "Budget looks thin.", "status": "contacted"},
            format="json",
        )
        # A staff read includes it; there is no public read path at all.
        staff_view = auth_client(fde).get(f"/api/v1/demo-requests/{request_id}/")
        assert staff_view.data["internal_notes"] == "Budget looks thin."
        assert api.get(f"/api/v1/demo-requests/{request_id}/").status_code == 401
