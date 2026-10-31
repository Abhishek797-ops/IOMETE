"""
Product knowledge base integrity.

These tests defend the factual-accuracy promise. A customer-facing claim with no resolvable
source is a bug, so the validator must catch one — and the guardrail list must actually be
published rather than living only in a prompt.
"""

from __future__ import annotations

import copy

import pytest

from knowledge.services import product_knowledge as pk

pytestmark = pytest.mark.django_db


class TestTheShippedKnowledgeBaseIsValid:
    def test_it_loads_and_validates(self):
        data = pk.load()
        report = pk.validate(data)
        assert report.ok, report.errors
        assert not report.warnings, report.warnings

    def test_every_source_is_complete(self):
        for source in pk.load()["sources"]:
            assert source["id"]
            assert source["title"]
            assert source["url"].startswith("https://iomete.com"), (
                f"{source['id']} is not an official IOMETE URL: {source['url']}"
            )
            assert source["fetched_at"]

    @pytest.mark.parametrize(
        "collection",
        ["capabilities", "technologies", "integrations", "storage_backends", "deployment_models"],
    )
    def test_every_entry_has_a_known_status(self, collection):
        for entry in pk.load()[collection]:
            assert entry.get("status") in pk.VALID_STATUSES, entry

    def test_every_citation_resolves(self):
        data = pk.load()
        known = {source["id"] for source in data["sources"]}
        for collection in ("capabilities", "technologies", "integrations",
                           "storage_backends", "deployment_models"):
            for entry in data[collection]:
                for reference in entry.get("sources") or []:
                    assert reference in known, f"{collection}: unknown source {reference}"

    def test_verified_entries_cite_at_least_one_source(self):
        """A `verified` claim with no citation is the exact failure this file prevents."""
        for collection in ("capabilities", "technologies", "integrations", "storage_backends"):
            for entry in pk.load()[collection]:
                if entry.get("status") == "verified":
                    assert entry.get("sources"), (
                        f"{collection}/{entry.get('id') or entry.get('name')} is marked "
                        "verified but cites nothing."
                    )

    def test_the_guardrail_list_is_populated_and_covers_the_obvious_risks(self):
        prohibited = " ".join(pk.do_not_claim()).lower()
        assert len(pk.do_not_claim()) >= 5
        for topic in ("pricing", "customer", "benchmark", "service level", "saving"):
            assert topic in prohibited, f"`do_not_claim` does not mention {topic}"

    def test_vendor_claims_are_labelled_as_such(self):
        """
        IOMETE's compliance statements and cost multiples are published by IOMETE and not
        independently verifiable. They must carry `vendor_claim`, not `verified`.
        """
        by_id = {entry["id"]: entry for entry in pk.load()["capabilities"]}
        assert by_id["compliance"]["status"] == "vendor_claim"
        assert by_id["cost-levers"]["status"] == "vendor_claim"
        # And the discrepancy between the two published figures is acknowledged.
        assert "2-5x" in by_id["cost-levers"]["limitations"]
        assert "2-3x" in by_id["cost-levers"]["limitations"]

    def test_unconfirmed_capabilities_are_labelled_rather_than_asserted(self):
        by_id = {entry["id"]: entry for entry in pk.load()["capabilities"]}
        # Streaming connectors are named on the homepage but have no documented connector.
        assert by_id["streaming-sources"]["status"] == "needs_confirmation"
        assert by_id["query-federation"]["status"] == "needs_confirmation"
        for entry in pk.load()["capabilities"]:
            if entry["status"] == "needs_confirmation":
                assert entry.get("limitations"), (
                    f"{entry['id']} needs confirmation but does not say what is unconfirmed."
                )

    def test_all_five_personas_are_present_and_cite_sources(self):
        personas = pk.load()["personas"]
        assert {persona["id"] for persona in personas} == {
            "cto", "data-engineer", "data-analyst", "security-compliance", "business",
        }
        for persona in personas:
            assert persona["opening"]
            assert persona["cares_about"]
            assert persona["key_points"]
            assert persona["questions_to_ask_iomete"]
            for point in persona["key_points"]:
                assert point["title"] and point["body"]

    def test_each_persona_includes_an_honest_caveat(self):
        """
        A persona narrative with no trade-off is a brochure. The CTO and business personas
        in particular must state that self-hosting means owning the operations.
        """
        for persona_id in ("cto", "business", "security-compliance"):
            persona = pk.get_persona(persona_id)
            bodies = " ".join(point["body"].lower() for point in persona["key_points"])
            has_caveat = any(point.get("caveat") for point in persona["key_points"])
            mentions_tradeoff = any(
                phrase in bodies
                for phrase in ("prerequisite", "own the operations", "trade-off", "vendor claim")
            )
            assert has_caveat or mentions_tradeoff, (
                f"persona {persona_id} states no honest trade-off"
            )

    def test_all_eleven_explainer_questions_are_answered(self):
        questions = pk.load()["explainer_questions"]
        assert len(questions) == 11
        for question in questions:
            assert question["question"].endswith("?")
            assert len(question["answer"]) > 80, question["id"]

    def test_the_architecture_covers_the_documented_services(self):
        architecture = pk.architecture()
        assert {tier["id"] for tier in architecture["tiers"]} == {
            "infrastructure", "platform-services", "workloads"
        }
        service_ids = {service["id"] for service in architecture["services"]}
        for expected in (
            "iom-gateway", "identity-service", "iceberg-rest-catalog", "compute-clusters",
            "kubernetes", "postgresql", "sql-service", "catalog-service",
        ):
            assert expected in service_ids
        for service in architecture["services"]:
            # The knowledge API returns these flat; the architecture playground nests them
            # under `detail` when it builds graph nodes.
            assert service["what_it_does"], service["id"]
            assert service["why_needed"], service["id"]
            assert service["customer_gain"], service["id"]
            assert service["sources"], f"{service['id']} cites no source"


class TestValidationCatchesProblems:
    def _mutate(self, **changes):
        data = copy.deepcopy(pk.load())
        data.pop("_source_index", None)
        for key, value in changes.items():
            data[key] = value
        return data

    def test_an_unresolvable_citation_is_an_error(self):
        data = self._mutate()
        data["capabilities"][0]["sources"] = ["S999"]
        report = pk.validate(data)
        assert not report.ok
        assert any("S999" in error for error in report.errors)

    def test_an_unknown_status_is_an_error(self):
        data = self._mutate()
        data["capabilities"][0]["status"] = "probably_true"
        report = pk.validate(data)
        assert not report.ok
        assert any("probably_true" in error for error in report.errors)

    def test_a_missing_status_is_an_error(self):
        data = self._mutate()
        del data["capabilities"][0]["status"]
        report = pk.validate(data)
        assert not report.ok
        assert any("missing `status`" in error for error in report.errors)

    def test_an_empty_guardrail_list_is_an_error(self):
        report = pk.validate(self._mutate(do_not_claim=[]))
        assert not report.ok
        assert any("do_not_claim" in error for error in report.errors)

    def test_a_missing_top_level_key_is_an_error(self):
        data = self._mutate()
        del data["personas"]
        report = pk.validate(data)
        assert not report.ok
        assert any("personas" in error for error in report.errors)

    def test_a_verified_entry_without_sources_is_a_warning(self):
        data = self._mutate()
        data["capabilities"][0]["status"] = "verified"
        data["capabilities"][0]["sources"] = []
        report = pk.validate(data)
        assert report.ok, "This is a warning, not an error."
        assert any("cites no source" in warning for warning in report.warnings)

    def test_the_management_command_passes_on_the_shipped_file(self):
        from io import StringIO

        from django.core.management import call_command

        out = StringIO()
        call_command("check_knowledge", "--strict", stdout=out)
        output = out.getvalue()
        assert "Knowledge base is valid" in output
        assert "last verified" in output


class TestTheKnowledgeApi:
    def test_the_full_knowledge_base_is_public(self, api):
        response = api.get("/api/v1/knowledge/product/")
        assert response.status_code == 200
        data = response.data
        assert data["capabilities"]
        assert data["do_not_claim"]
        assert data["status_legend"]
        # Citations arrive resolved, so a client never has to join them itself.
        assert isinstance(data["capabilities"][0]["sources"], list)
        if data["capabilities"][0]["sources"]:
            assert data["capabilities"][0]["sources"][0]["url"]

    def test_the_status_legend_tells_the_client_how_to_render_each_status(self, api):
        response = api.get("/api/v1/knowledge/product/")
        legend = response.data["status_legend"]
        assert set(legend) == pk.VALID_STATUSES
        assert "never presented as a COMPASS finding" in legend["vendor_claim"]

    def test_the_explainer_endpoint_returns_the_questions_and_personas(self, api):
        response = api.get("/api/v1/knowledge/explainer/")
        assert response.status_code == 200
        assert len(response.data["questions"]) == 11
        assert len(response.data["personas"]) == 5
        assert response.data["concepts"]

    @pytest.mark.parametrize(
        "persona_id", ["cto", "data-engineer", "data-analyst", "security-compliance", "business"]
    )
    def test_each_persona_is_retrievable(self, api, persona_id):
        response = api.get(f"/api/v1/knowledge/personas/{persona_id}/")
        assert response.status_code == 200
        assert response.data["id"] == persona_id
        assert response.data["key_points"]

    def test_an_unknown_persona_returns_404_with_the_available_options(self, api):
        response = api.get("/api/v1/knowledge/personas/cfo/")
        assert response.status_code == 404
        assert response.data["error"]["details"]["available"]

    def test_the_architecture_endpoint_serves_the_playground_data(self, api):
        response = api.get("/api/v1/knowledge/architecture/")
        assert response.status_code == 200
        assert response.data["architecture"]["services"]
        assert response.data["storage_backends"]
        assert response.data["deployment_models"]

    def test_capabilities_can_be_filtered_by_status(self, api):
        response = api.get("/api/v1/knowledge/capabilities/?status=needs_confirmation")
        assert response.status_code == 200
        assert response.data["capabilities"]
        assert all(
            entry["status"] == "needs_confirmation" for entry in response.data["capabilities"]
        )

    def test_the_guardrail_list_is_published(self, api):
        response = api.get("/api/v1/knowledge/do-not-claim/")
        assert response.status_code == 200
        assert response.data["do_not_claim"]
        assert response.data["note"]

    @pytest.mark.parametrize(
        "query,expected_substring",
        [
            ("iceberg", "Iceberg"),
            ("kubernetes", "Kubernetes"),
            ("ranger", "Ranger"),
            ("spark", "Spark"),
            ("sovereign", "sovereign"),
        ],
    )
    def test_search_finds_the_obvious_terms(self, api, query, expected_substring):
        response = api.get(f"/api/v1/knowledge/search/?q={query}")
        assert response.status_code == 200
        assert response.data["count"] > 0, f"no results for {query!r}"
        combined = str(response.data["results"])
        assert expected_substring.lower() in combined.lower()

    def test_search_with_no_query_returns_nothing_rather_than_everything(self, api):
        response = api.get("/api/v1/knowledge/search/?q=")
        assert response.status_code == 200
        assert response.data["count"] == 0

    def test_search_results_carry_their_citations(self, api):
        response = api.get("/api/v1/knowledge/search/?q=iceberg")
        for result in response.data["results"]:
            assert result["kind"]
            assert result["title"]
            assert "entry" in result


class TestHelpers:
    def test_verified_integration_names_excludes_unconfirmed_entries(self):
        names = pk.verified_integration_names()
        assert "Power BI" in names
        assert "dbt" in names
        # Nothing with a non-verified status should appear.
        unverified = {
            entry["name"]
            for entry in pk.load()["integrations"]
            if entry.get("status") != "verified"
        }
        assert not (names & unverified)

    def test_verified_only_storage_backends_excludes_unconfirmed_ones(self):
        verified = {entry["name"] for entry in pk.storage_backends(verified_only=True)}
        assert "AWS S3" in verified
        # HDFS and NFS are listed but not documented as object-storage config types.
        assert "Hadoop HDFS" not in verified
        assert "NFS" not in verified

    def test_knowledge_meta_reports_counts_for_the_status_endpoint(self):
        meta = pk.knowledge_meta()
        assert meta["available"] is True
        assert meta["source_count"] >= 5
        assert meta["capability_count"] >= 15
        assert meta["verified_capability_count"] >= 1
        assert meta["do_not_claim_count"] >= 5

    def test_resolve_sources_ignores_unknown_ids_without_raising(self):
        assert pk.resolve_sources(["S1", "S999"]) != []
        assert all(source["id"] != "S999" for source in pk.resolve_sources(["S1", "S999"]))

    def test_a_missing_file_raises_a_clear_error(self, settings, tmp_path):
        from knowledge.services.product_knowledge import KnowledgeBaseError

        settings.PRODUCT_KNOWLEDGE_PATH = tmp_path / "absent.json"
        pk.load.cache_clear()
        with pytest.raises(KnowledgeBaseError) as excinfo:
            pk.load()
        assert "refuses to serve product claims" in str(excinfo.value)
