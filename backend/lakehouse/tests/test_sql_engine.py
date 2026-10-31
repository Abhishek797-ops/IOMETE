"""
Lakehouse playground: SQL safety and usefulness.

The playground runs user-supplied SQL, which is normally a sentence that should worry you.
These tests defend both halves of why it is acceptable here: it genuinely cannot write or
reach anything, and it genuinely executes real queries rather than replaying canned output.
"""

from __future__ import annotations

import pytest

from lakehouse.services import dataset, sql_engine


class TestReadOnlyEnforcement:
    @pytest.mark.parametrize(
        "statement",
        [
            "INSERT INTO orders VALUES (1)",
            "UPDATE orders SET net_amount = 0",
            "DELETE FROM orders",
            "DROP TABLE orders",
            "ALTER TABLE orders ADD COLUMN x TEXT",
            "CREATE TABLE evil (x TEXT)",
            "TRUNCATE orders",
            "REPLACE INTO orders VALUES (1)",
            "ATTACH DATABASE '/etc/passwd' AS leak",
            "PRAGMA table_list",
            "VACUUM",
        ],
    )
    def test_every_write_or_meta_statement_is_refused(self, statement):
        with pytest.raises(sql_engine.SqlRejected) as excinfo:
            sql_engine.run(statement)
        assert excinfo.value.code in {"sql_read_only", "sql_error", "sql_rejected"}

    def test_the_refusal_explains_itself(self):
        with pytest.raises(sql_engine.SqlRejected) as excinfo:
            sql_engine.run("DELETE FROM orders")
        message = str(excinfo.value)
        assert "read-only" in message
        # And points the user at what they can do instead.
        assert "SELECT" in message

    def test_a_second_statement_cannot_be_smuggled_in(self):
        with pytest.raises(sql_engine.SqlRejected) as excinfo:
            sql_engine.run("SELECT 1; DROP TABLE orders")
        assert excinfo.value.code == "sql_multiple_statements"

    def test_a_comment_cannot_hide_a_second_statement(self):
        """Comments are stripped before the statement count, so `-- ` cannot mask a `;`."""
        with pytest.raises(sql_engine.SqlRejected):
            sql_engine.run("SELECT 1 -- harmless\n; DROP TABLE orders")

    def test_a_block_comment_cannot_mask_a_write(self):
        with pytest.raises(sql_engine.SqlRejected) as excinfo:
            sql_engine.run("/* SELECT */ DELETE FROM orders")
        assert excinfo.value.code == "sql_read_only"

    def test_a_comment_only_statement_is_rejected_cleanly(self):
        with pytest.raises(sql_engine.SqlRejected) as excinfo:
            sql_engine.run("-- just a thought")
        assert excinfo.value.code == "sql_empty"

    def test_the_application_database_is_not_reachable(self):
        """
        The engine is given only the five synthetic tables, in a separate in-memory
        database. Django's own tables must not exist in it.
        """
        for table in ("accounts_user", "tickets_ticket", "django_migrations",
                      "integrations_integrationconfiguration"):
            with pytest.raises(sql_engine.SqlRejected) as excinfo:
                sql_engine.run(f"SELECT * FROM {table}")
            assert excinfo.value.code in {"sql_error", "sql_read_only"}
            assert "no table" in str(excinfo.value).lower()

    def test_sqlite_internal_tables_are_not_readable(self):
        with pytest.raises(sql_engine.SqlRejected):
            sql_engine.run("SELECT name FROM sqlite_master")

    def test_an_oversized_statement_is_refused(self):
        with pytest.raises(sql_engine.SqlRejected) as excinfo:
            sql_engine.run("SELECT " + ("1, " * 5000) + "1")
        assert excinfo.value.code in {"sql_too_long", "sql_too_many_columns"}

    def test_a_runaway_query_is_stopped(self):
        """A cartesian product must not hold a worker thread indefinitely."""
        with pytest.raises(sql_engine.SqlRejected) as excinfo:
            sql_engine.run(
                "SELECT count(*) FROM order_items a, order_items b, order_items c, "
                "order_items d"
            )
        assert excinfo.value.code == "sql_timeout"
        assert "stopped" in str(excinfo.value)


class TestRealExecution:
    def test_a_simple_aggregation_returns_real_rows(self):
        result = sql_engine.run(
            "SELECT region, count(*) AS orders FROM retail_analytics.orders "
            "GROUP BY region ORDER BY orders DESC"
        )
        assert result.columns == ["region", "orders"]
        assert result.rows
        assert sum(row[1] for row in result.rows) > 1000
        assert {row[0] for row in result.rows} <= {
            "EMEA", "North America", "APAC", "LATAM"
        }

    def test_the_fully_qualified_name_and_the_bare_name_both_work(self):
        qualified = sql_engine.run("SELECT count(*) FROM retail_analytics.orders")
        bare = sql_engine.run("SELECT count(*) FROM orders")
        assert qualified.rows == bare.rows

    def test_a_join_across_tables_works(self):
        result = sql_engine.run(
            "SELECT p.category, SUM(oi.line_total) AS revenue "
            "FROM retail_analytics.order_items oi "
            "JOIN retail_analytics.products p ON p.product_id = oi.product_id "
            "GROUP BY p.category ORDER BY revenue DESC"
        )
        assert len(result.rows) >= 5
        assert all(row[1] > 0 for row in result.rows)

    def test_a_common_table_expression_works(self):
        result = sql_engine.run(
            "WITH monthly AS ("
            "  SELECT order_month, SUM(gross_amount) AS revenue "
            "  FROM retail_analytics.orders GROUP BY order_month"
            ") SELECT order_month, revenue FROM monthly ORDER BY revenue DESC LIMIT 5"
        )
        assert len(result.rows) == 5

    def test_results_are_capped_and_the_cap_is_disclosed(self):
        result = sql_engine.run("SELECT * FROM retail_analytics.orders")
        assert result.row_count == sql_engine.MAX_ROWS
        assert result.truncated is True
        assert "first" in result.notice.lower()

    def test_the_dataset_is_deterministic_across_runs(self):
        """
        Determinism is what lets the documentation state what a sample query returns.
        """
        first = sql_engine.run("SELECT count(*) FROM retail_analytics.orders")
        dataset.build.cache_clear()
        second = sql_engine.run("SELECT count(*) FROM retail_analytics.orders")
        assert first.rows == second.rows

    def test_the_data_has_realistic_structure_not_uniform_noise(self):
        """
        Seasonality and a long tail are what make the sample queries interesting. Without
        them the playground teaches nothing, so it is worth asserting they are there.
        """
        monthly = sql_engine.run(
            "SELECT order_month, SUM(gross_amount) AS revenue FROM retail_analytics.orders "
            "GROUP BY order_month ORDER BY revenue DESC"
        )
        revenues = [row[1] for row in monthly.rows]
        assert max(revenues) > 1.5 * min(revenues), "Revenue is suspiciously flat."

        products = sql_engine.run(
            "SELECT product_id, count(*) AS n FROM retail_analytics.order_items "
            "GROUP BY product_id ORDER BY n DESC"
        )
        counts = [row[1] for row in products.rows]
        assert counts[0] > 3 * counts[len(counts) // 2], "No long tail in product popularity."


class TestErrorMessagesAreActionable:
    def test_an_unknown_table_lists_the_available_ones(self):
        with pytest.raises(sql_engine.SqlRejected) as excinfo:
            sql_engine.run("SELECT * FROM retail_analytics.invoices")
        message = str(excinfo.value)
        assert "no table called" in message
        assert "retail_analytics.orders" in message

    def test_an_unknown_column_points_at_the_schema_panel(self):
        with pytest.raises(sql_engine.SqlRejected) as excinfo:
            sql_engine.run("SELECT nonexistent FROM retail_analytics.orders")
        assert "no column called" in str(excinfo.value)
        assert "schema panel" in str(excinfo.value)

    def test_an_ambiguous_column_suggests_qualifying_it(self):
        with pytest.raises(sql_engine.SqlRejected) as excinfo:
            sql_engine.run(
                "SELECT order_id FROM retail_analytics.orders o "
                "JOIN retail_analytics.order_items oi ON oi.order_id = o.order_id"
            )
        message = str(excinfo.value)
        assert "more than one" in message
        assert "orders.order_id" in message

    def test_a_syntax_error_is_explained(self):
        with pytest.raises(sql_engine.SqlRejected) as excinfo:
            sql_engine.run("SELECT FROM WHERE")
        assert "syntax error" in str(excinfo.value).lower()

    def test_an_empty_statement_is_rejected_clearly(self):
        with pytest.raises(sql_engine.SqlRejected) as excinfo:
            sql_engine.run("   ")
        assert excinfo.value.code == "sql_empty"


class TestTheSimulatedExecutionPlan:
    def test_every_plan_entry_is_marked_simulated(self):
        result = sql_engine.run(
            "SELECT region, count(*) FROM retail_analytics.orders GROUP BY region"
        )
        assert result.execution_plan
        assert all(entry["simulated"] is True for entry in result.execution_plan)

    def test_a_filter_on_the_partition_key_is_reported_as_pruning(self):
        pruned = sql_engine.run(
            "SELECT count(*) FROM retail_analytics.orders WHERE order_month = '2026-01'"
        )
        scan = next(
            entry for entry in pruned.execution_plan if entry["operator"] == "Scan iceberg"
        )
        assert scan["partition_pruning"] is True
        assert "only the matching partitions" in scan["note"]

    def test_no_partition_filter_is_reported_honestly(self):
        unpruned = sql_engine.run("SELECT count(*) FROM retail_analytics.orders")
        scan = next(
            entry for entry in unpruned.execution_plan if entry["operator"] == "Scan iceberg"
        )
        assert scan["partition_pruning"] is False
        assert "all partitions are scanned" in scan["note"]

    def test_a_join_produces_shuffle_and_join_stages(self):
        result = sql_engine.run(
            "SELECT p.category, count(*) FROM retail_analytics.order_items oi "
            "JOIN retail_analytics.products p ON p.product_id = oi.product_id "
            "GROUP BY p.category"
        )
        operators = [entry["operator"] for entry in result.execution_plan]
        assert any("Exchange" in operator for operator in operators)
        assert any("Join" in operator for operator in operators)
        assert any("HashAggregate" in operator for operator in operators)

    def test_a_plain_select_has_no_shuffle(self):
        result = sql_engine.run("SELECT order_ref FROM retail_analytics.orders LIMIT 5")
        operators = [entry["operator"] for entry in result.execution_plan]
        assert not any("Join" in operator for operator in operators)


class TestSampleQueries:
    def test_there_are_samples_across_difficulty_levels(self):
        samples = sql_engine.sample_queries()
        assert len(samples) >= 6
        assert {sample["difficulty"] for sample in samples} >= {
            "starter", "intermediate", "advanced"
        }

    @pytest.mark.parametrize("sample", sql_engine.sample_queries(), ids=lambda s: s["id"])
    def test_every_sample_runs_and_returns_rows(self, sample):
        result = sql_engine.run(sample["sql"])
        assert result.rows, f"{sample['id']} returned nothing"
        assert result.columns

    @pytest.mark.parametrize("sample", sql_engine.sample_queries(), ids=lambda s: s["id"])
    def test_every_sample_teaches_something_and_declares_a_chart(self, sample):
        assert sample["teaches"], f"{sample['id']} has no explanation"
        assert sample["chart"]["type"]
        assert sample["title"]

    @pytest.mark.parametrize("sample", sql_engine.sample_queries(), ids=lambda s: s["id"])
    def test_every_sample_charts_columns_it_actually_returns(self, sample):
        """
        A chart hint naming a column the query does not produce would render an empty
        chart in the UI, which looks like a bug in the product rather than in the sample.
        """
        result = sql_engine.run(sample["sql"])
        columns = set(result.columns)
        chart = sample["chart"]
        for key in ("x", "series"):
            if chart.get(key):
                assert chart[key] in columns, (
                    f"{sample['id']}: chart {key}={chart[key]!r} not in {sorted(columns)}"
                )
        for column in chart.get("y") or []:
            assert column in columns, (
                f"{sample['id']}: chart y={column!r} not in {sorted(columns)}"
            )


class TestTheDataset:
    def test_all_five_tables_are_present_with_schemas(self):
        described = dataset.describe()
        names = {table["name"] for table in described["tables"]}
        assert names == {
            "customers", "products", "orders", "order_items", "clickstream_events"
        }
        for table in described["tables"]:
            assert table["columns"]
            assert table["row_count"] > 0
            assert table["ddl"].startswith("CREATE TABLE")
            assert "USING iceberg" in table["ddl"]
            for column in table["columns"]:
                assert column["name"] and column["iceberg_type"] and column["sql_type"]

    def test_the_dataset_is_labelled_synthetic(self):
        described = dataset.describe()
        assert described["is_synthetic"] is True
        assert "synthetic" in described["synthetic_notice"].lower()
        assert "not represent any real" in described["synthetic_notice"].lower()

    def test_iceberg_metadata_is_labelled_illustrative(self):
        for table in dataset.describe()["tables"]:
            metadata = table["simulated_metadata"]
            assert metadata["simulated"] is True
            assert "not figures from a real" in metadata["notice"].lower()
            assert metadata["capabilities_demonstrated"]

    def test_simulated_metadata_is_internally_consistent(self):
        """Numbers that visibly do not add up would undermine the whole demo."""
        for table in dataset.describe()["tables"]:
            metadata = table["simulated_metadata"]
            assert metadata["total_records"] == table["row_count"]
            assert metadata["total_data_files"] >= 1
            assert metadata["manifest_files"] >= 1
            assert metadata["snapshots"]
            assert metadata["current_snapshot_id"] == metadata["snapshots"][0]["snapshot_id"]

    def test_the_pipeline_has_seven_cited_stages(self):
        stages = dataset.pipeline_stages()
        assert len(stages) == 7
        assert [stage["order"] for stage in stages] == list(range(1, 8))
        for stage in stages:
            assert stage["title"] and stage["summary"]
            assert stage["iomete_component"]
            assert stage["sources"], f"stage {stage['id']} cites no source"

    def test_pipeline_citations_resolve_to_real_sources(self):
        from knowledge.services.product_knowledge import load

        known = {source["id"] for source in load()["sources"]}
        for stage in dataset.pipeline_stages():
            for reference in stage["sources"]:
                assert reference in known, f"{stage['id']} cites unknown {reference}"


@pytest.mark.django_db
class TestThePlaygroundApi:
    def test_the_dataset_endpoint_is_public(self, api):
        response = api.get("/api/v1/lakehouse-demo/dataset/")
        assert response.status_code == 200
        assert response.data["mode"] == "demo"
        assert len(response.data["tables"]) == 5
        assert response.data["pipeline"]

    def test_a_query_runs_and_is_labelled_simulated(self, api):
        response = api.post(
            "/api/v1/lakehouse-demo/query/",
            {
                "sql": "SELECT region, count(*) AS orders FROM retail_analytics.orders "
                       "GROUP BY region"
            },
            format="json",
        )
        assert response.status_code == 200
        assert response.data["mode"] == "demo"
        assert response.data["is_simulated"] is True
        assert response.data["rows"]
        assert response.data["execution_plan"]
        assert "illustrative" in response.data["execution_plan_notice"].lower()
        assert "simulated" in response.data["simulation_notice"].lower()

    def test_a_sample_can_be_run_by_id(self, api):
        response = api.post(
            "/api/v1/lakehouse-demo/query/",
            {"sample_id": "revenue-by-month"},
            format="json",
        )
        assert response.status_code == 200
        assert response.data["rows"]
        assert response.data["sample"]["id"] == "revenue-by-month"

    def test_an_unknown_sample_lists_the_available_ones(self, api):
        response = api.post(
            "/api/v1/lakehouse-demo/query/", {"sample_id": "nope"}, format="json"
        )
        assert response.status_code == 404
        assert response.data["error"]["details"]["available"]

    def test_a_write_attempt_is_refused_with_a_helpful_message(self, api):
        response = api.post(
            "/api/v1/lakehouse-demo/query/",
            {"sql": "DELETE FROM retail_analytics.orders"},
            format="json",
        )
        assert response.status_code == 400
        assert response.data["error"]["code"] == "sql_read_only"
        assert response.data["error"]["details"]["tables"]

    def test_query_runs_are_logged_including_failures(self, api):
        from lakehouse.models import LakehouseQueryRun

        api.post(
            "/api/v1/lakehouse-demo/query/",
            {"sql": "SELECT count(*) FROM retail_analytics.orders", "session_key": "sess-1"},
            format="json",
        )
        api.post(
            "/api/v1/lakehouse-demo/query/",
            {"sql": "DROP TABLE orders", "session_key": "sess-1"},
            format="json",
        )
        runs = LakehouseQueryRun.objects.filter(session_key="sess-1")
        assert runs.count() == 2
        assert runs.filter(succeeded=True).count() == 1
        assert runs.filter(succeeded=False, error_code="sql_read_only").count() == 1

    def test_requesting_neither_sql_nor_a_sample_is_a_validation_error(self, api):
        response = api.post("/api/v1/lakehouse-demo/query/", {}, format="json")
        assert response.status_code == 400

    def test_the_samples_endpoint_is_public(self, api):
        response = api.get("/api/v1/lakehouse-demo/sample-queries/")
        assert response.status_code == 200
        assert response.data["queries"]
