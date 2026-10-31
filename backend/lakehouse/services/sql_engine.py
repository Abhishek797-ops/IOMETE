"""
The playground's SQL engine.

Real SQL execution against the synthetic dataset, using an **in-memory SQLite database
built fresh for each request**. That choice deserves an explanation, because "run the
user's SQL" is normally a sentence that should worry you.

Why real execution rather than canned results:
    A prospect typing their own `GROUP BY` and getting a real answer learns something about
    what a lakehouse does. A pre-recorded result set teaches them nothing and falls over the
    moment they change a column. Demo mode should be honest about being a simulation, not
    fake about being interactive.

Why it is safe:
    1. **Fresh in-memory database per request.** Nothing persists. The worst possible
       outcome of a successful write is that the attacker modifies data only they can see,
       for the duration of one HTTP request, before it is discarded.
    2. **A SQLite authorizer callback denies every operation except read.** This is enforced
       by SQLite itself, below the SQL parser, so it cannot be evaded by syntax tricks —
       `ATTACH`, `PRAGMA`, writes, and function creation are all refused.
    3. **Statement validation before execution.** Exactly one statement, which must be a
       `SELECT` or `WITH`. Comments are stripped first so `-- ` cannot hide a second
       statement.
    4. **No access to the application database.** This connection has no knowledge of it.
       `sqlite3` is given only the five synthetic tables.
    5. **Resource limits.** A row cap, a column cap, and a statement timeout enforced via a
       progress handler, so a cartesian join cannot hold a worker thread.

The engine also returns an *illustrative* Spark execution plan, labelled as such. It is a
teaching device showing the stages a distributed engine would go through; it is not a real
`EXPLAIN` from Spark and never claims to be.
"""

from __future__ import annotations

import re
import sqlite3
import time
from dataclasses import dataclass, field
from typing import Any

from .dataset import DATASET_ID, tables

#: Hard caps. A prospect exploring data does not need a million rows, and a worker thread
#: held by an accidental cross join is a denial of service against everyone else.
MAX_ROWS = 500
MAX_COLUMNS = 40
STATEMENT_TIMEOUT_SECONDS = 3.0

#: Only these two can start a statement.
_ALLOWED_PREFIXES = ("select", "with")

_COMMENT_BLOCK = re.compile(r"/\*.*?\*/", re.S)
_COMMENT_LINE = re.compile(r"--[^\n]*")


class SqlRejected(ValueError):
    """The statement was refused before execution. Carries a user-facing explanation."""

    def __init__(self, message: str, *, code: str = "sql_rejected"):
        super().__init__(message)
        self.code = code


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[list[Any]]
    row_count: int
    truncated: bool
    duration_ms: int
    sql: str
    execution_plan: list[dict] = field(default_factory=list)
    scanned_tables: list[str] = field(default_factory=list)
    notice: str = ""


def _strip_comments(sql: str) -> str:
    return _COMMENT_LINE.sub(" ", _COMMENT_BLOCK.sub(" ", sql))


def validate(sql: str) -> str:
    """
    Validate and normalise a statement, or raise `SqlRejected` with a helpful message.

    Error messages explain *why* rather than just refusing — a prospect who typed `UPDATE`
    out of habit should learn that the playground is read-only, not hit a wall.
    """
    if not sql or not sql.strip():
        raise SqlRejected("Enter a SELECT query to run.", code="sql_empty")

    cleaned = _strip_comments(sql).strip()
    if not cleaned:
        raise SqlRejected(
            "That query is only comments — there is nothing to run.", code="sql_empty"
        )

    # One statement only. A trailing semicolon is fine; a second statement is not.
    statements = [part for part in cleaned.split(";") if part.strip()]
    if len(statements) > 1:
        raise SqlRejected(
            "Please run one statement at a time. The playground executes a single SELECT "
            "so that results are unambiguous.",
            code="sql_multiple_statements",
        )

    statement = statements[0].strip()
    first_word = statement.split(None, 1)[0].lower() if statement.split() else ""

    if first_word not in _ALLOWED_PREFIXES:
        raise SqlRejected(
            f"The playground is read-only, so `{first_word.upper()}` is not available. "
            "Start your query with SELECT (or WITH, for a common table expression). "
            "In a real IOMETE deployment you would write to Iceberg tables through a Spark "
            "job or the SQL editor, subject to your Ranger access policies.",
            code="sql_read_only",
        )

    if len(statement) > 8000:
        raise SqlRejected(
            "That query is unusually long. Trim it to under 8,000 characters.",
            code="sql_too_long",
        )
    return statement


def _authorizer(action: int, arg1, arg2, db_name, trigger) -> int:
    """
    SQLite's own authorization hook. Allows read operations, denies everything else.

    This runs inside SQLite during statement preparation, below the SQL text, so it is not
    something a cleverly-worded query can talk its way past. `SQLITE_READ`, `SQLITE_SELECT`
    and `SQLITE_FUNCTION` are permitted; `ATTACH`, `PRAGMA`, every write verb and anything
    else is refused.
    """
    allowed = {
        sqlite3.SQLITE_READ,
        sqlite3.SQLITE_SELECT,
        sqlite3.SQLITE_FUNCTION,
    }
    if action not in allowed:
        return sqlite3.SQLITE_DENY

    # SQLite's internal catalogue (`sqlite_master`, `sqlite_schema`, `sqlite_temp_*`) is a
    # read, so the allowlist above would otherwise permit it. It is denied explicitly:
    # there is nothing in it a prospect exploring a demo dataset needs, and letting a query
    # enumerate the schema it was not given is a reconnaissance step rather than analysis.
    if action == sqlite3.SQLITE_READ and isinstance(arg1, str):
        if arg1.lower().startswith("sqlite_"):
            return sqlite3.SQLITE_DENY

    return sqlite3.SQLITE_OK


def _build_connection() -> sqlite3.Connection:
    """
    Create a fresh in-memory database holding the synthetic tables.

    Built per request. Loading ~25k rows into SQLite takes single-digit milliseconds, which
    is a price worth paying for complete isolation between sessions.
    """
    connection = sqlite3.connect(":memory:")

    for name, table in tables().items():
        columns = ", ".join(
            f"\"{column['name']}\" {column['sql_type']}" for column in table.columns
        )
        connection.execute(f'CREATE TABLE "{name}" ({columns})')
        placeholders = ", ".join("?" for _ in table.columns)
        connection.executemany(
            f'INSERT INTO "{name}" VALUES ({placeholders})', table.rows
        )
        # Indexes on the join and partition keys, so a demo query over 25k rows is instant
        # rather than merely fast.
        for column in table.partitioned_by:
            connection.execute(
                f'CREATE INDEX "idx_{name}_{column}" ON "{name}" ("{column}")'
            )
        for column in table.columns:
            if column["name"].endswith("_id"):
                connection.execute(
                    f'CREATE INDEX IF NOT EXISTS "idx_{name}_{column["name"]}" '
                    f'ON "{name}" ("{column["name"]}")'
                )

    connection.commit()

    # Both guards go on only after the data is loaded — the loader itself has to write.
    # `query_only` is the belt and the authorizer is the braces: the pragma blocks writes
    # at the storage layer, the authorizer blocks them (and ATTACH, PRAGMA and function
    # creation) during statement preparation, below the SQL parser.
    connection.execute("PRAGMA query_only = ON")
    connection.set_authorizer(_authorizer)
    return connection


def _normalise_table_references(sql: str) -> str:
    """
    Accept both `orders` and `retail_analytics.orders`.

    The playground displays fully-qualified Iceberg names (`retail_analytics.orders`),
    because that is what a prospect would type against a real catalog. SQLite has no such
    schema, so the prefix is stripped. Doing this *after* validation means it cannot be
    used to smuggle anything past the checks.
    """
    return re.sub(
        rf"\b{re.escape(DATASET_ID)}\.(\w+)", r"\1", sql, flags=re.IGNORECASE
    )


def _simulated_plan(sql: str, scanned: list[str], row_count: int, duration_ms: int) -> list[dict]:
    """
    An illustrative Spark execution plan.

    Labelled `simulated: true` everywhere it surfaces. Its purpose is pedagogical: it shows
    a prospect the stages a distributed engine goes through — partition pruning, a scan per
    table, a shuffle for the join, the exchange for the aggregation — which is exactly the
    thing that is invisible and mysterious about a lakehouse. Constructed from the actual
    query shape so it is never nonsense, but it is not a real Spark plan and does not
    pretend to be.
    """
    lowered = sql.lower()
    plan: list[dict] = []
    step = 1

    for table_name in scanned:
        table = tables().get(table_name)
        if table is None:
            continue
        partition_pruned = any(
            column in lowered for column in table.partitioned_by
        ) and "where" in lowered
        plan.append(
            {
                "step": step,
                "operator": "Scan iceberg",
                "detail": f"{DATASET_ID}.{table_name}",
                "note": (
                    f"Reads Parquet data files. Partition pruning on "
                    f"`{', '.join(table.partitioned_by)}` applies because your WHERE clause "
                    "filters on it — only the matching partitions are read."
                    if partition_pruned
                    else (
                        f"Reads Parquet data files. No filter on the partition key "
                        f"(`{', '.join(table.partitioned_by)}`), so all partitions are "
                        "scanned. Filtering on the partition key is the single biggest "
                        "performance lever in a lakehouse."
                        if table.partitioned_by
                        else "Reads Parquet data files."
                    )
                ),
                "partition_pruning": partition_pruned,
            }
        )
        step += 1

    if "join" in lowered:
        plan.append(
            {
                "step": step,
                "operator": "Exchange hashpartitioning",
                "detail": "Shuffle for join",
                "note": (
                    "Rows are redistributed across executors so matching keys land on the "
                    "same one. Shuffles are the expensive part of distributed SQL — Spark's "
                    "adaptive query execution can switch to a broadcast join when one side "
                    "is small enough."
                ),
            }
        )
        step += 1
        plan.append(
            {
                "step": step,
                "operator": "SortMergeJoin",
                "detail": "Join on the shuffled keys",
                "note": "Matching rows are combined on each executor independently.",
            }
        )
        step += 1

    if any(token in lowered for token in ("group by", "count(", "sum(", "avg(", "min(", "max(")):
        plan.append(
            {
                "step": step,
                "operator": "HashAggregate (partial)",
                "detail": "Aggregate within each partition",
                "note": (
                    "Each executor aggregates its own rows first, which dramatically reduces "
                    "the volume that has to cross the network."
                ),
            }
        )
        step += 1
        plan.append(
            {
                "step": step,
                "operator": "Exchange + HashAggregate (final)",
                "detail": "Combine partial aggregates",
                "note": "The partial results are merged into the final answer.",
            }
        )
        step += 1

    if "order by" in lowered:
        plan.append(
            {
                "step": step,
                "operator": "Sort",
                "detail": "Order the result set",
                "note": "A global sort requires a range-partitioning exchange first.",
            }
        )
        step += 1

    plan.append(
        {
            "step": step,
            "operator": "CollectLimit",
            "detail": f"Return {row_count} row(s) to the client",
            "note": (
                f"Results travel back over Arrow Flight or the JDBC endpoint. Measured "
                f"locally at {duration_ms} ms against the in-memory demo dataset."
            ),
        }
    )

    for entry in plan:
        entry["simulated"] = True
    return plan


def _scanned_tables(sql: str) -> list[str]:
    lowered = sql.lower()
    return [name for name in tables() if re.search(rf"\b{name}\b", lowered)]


def run(sql: str) -> QueryResult:
    """
    Execute a validated SELECT against the synthetic dataset.

    Raises `SqlRejected` for a refused statement, and for a SQL error it wraps SQLite's
    message in something a non-expert can act on.
    """
    statement = validate(sql)
    prepared = _normalise_table_references(statement)

    connection = _build_connection()
    started = time.perf_counter()
    deadline = started + STATEMENT_TIMEOUT_SECONDS

    def _interrupt_if_slow() -> int:
        # Progress handler: returning non-zero aborts. This is how a runaway cartesian
        # join is stopped without killing the worker.
        return 1 if time.perf_counter() > deadline else 0

    connection.set_progress_handler(_interrupt_if_slow, 10_000)

    try:
        cursor = connection.execute(prepared)
        description = cursor.description or []
        if len(description) > MAX_COLUMNS:
            raise SqlRejected(
                f"That query returns {len(description)} columns. Select up to "
                f"{MAX_COLUMNS} so the results stay readable.",
                code="sql_too_many_columns",
            )
        columns = [column[0] for column in description]
        fetched = cursor.fetchmany(MAX_ROWS + 1)
        truncated = len(fetched) > MAX_ROWS
        rows = [list(row) for row in fetched[:MAX_ROWS]]
    except sqlite3.OperationalError as exc:
        message = str(exc)
        if "interrupted" in message.lower():
            raise SqlRejected(
                f"The query took longer than {STATEMENT_TIMEOUT_SECONDS:g} seconds and was "
                "stopped. In the demo playground, try narrowing it with a WHERE clause on "
                "a partition key such as `order_month`.",
                code="sql_timeout",
            ) from exc
        if "not authorized" in message.lower():
            raise SqlRejected(
                "That operation is not permitted — the playground is strictly read-only.",
                code="sql_read_only",
            ) from exc
        raise SqlRejected(_friendly_sql_error(message), code="sql_error") from exc
    except sqlite3.DatabaseError as exc:
        raise SqlRejected(_friendly_sql_error(str(exc)), code="sql_error") from exc
    finally:
        connection.close()

    duration_ms = int((time.perf_counter() - started) * 1000)
    scanned = _scanned_tables(prepared)

    return QueryResult(
        columns=columns,
        rows=rows,
        row_count=len(rows),
        truncated=truncated,
        duration_ms=duration_ms,
        sql=statement,
        execution_plan=_simulated_plan(statement, scanned, len(rows), duration_ms),
        scanned_tables=scanned,
        notice=(
            f"Showing the first {MAX_ROWS} rows. Add a LIMIT or an aggregation to see a "
            "complete result."
            if truncated
            else ""
        ),
    )


def _friendly_sql_error(message: str) -> str:
    """Translate SQLite's terse errors into something actionable."""
    lowered = message.lower()
    if "no such table" in lowered:
        name = message.split(":")[-1].strip()
        available = ", ".join(f"{DATASET_ID}.{t}" for t in tables())
        return (
            f"There is no table called `{name}` in this dataset. Available tables: "
            f"{available}."
        )
    if "no such column" in lowered:
        name = message.split(":")[-1].strip()
        return (
            f"There is no column called `{name}`. Open the schema panel to see the columns "
            "on each table."
        )
    if "syntax error" in lowered:
        return f"SQL syntax error: {message}. Check for a missing comma, quote or keyword."
    if "ambiguous column name" in lowered:
        name = message.split(":")[-1].strip()
        return (
            f"The column `{name}` exists on more than one of the joined tables. Qualify it, "
            f"for example `orders.{name}`."
        )
    if "misuse of aggregate" in lowered:
        return (
            f"{message}. An aggregate such as SUM() cannot be used in a WHERE clause — use "
            "HAVING after a GROUP BY instead."
        )
    return f"The query could not be executed: {message}"


# =======================================================================================
# Curated sample queries
# =======================================================================================

SAMPLE_QUERIES: tuple[dict, ...] = (
    {
        "id": "revenue-by-month",
        "title": "Revenue trend by month",
        "teaches": (
            "Partition pruning. `order_month` is the partition key, so filtering on it "
            "means Spark reads only the relevant files instead of the whole table."
        ),
        "difficulty": "starter",
        "chart": {"type": "line", "x": "order_month", "y": ["gross_revenue"]},
        "sql": """SELECT
    order_month,
    COUNT(*)                        AS orders,
    ROUND(SUM(gross_amount), 2)     AS gross_revenue,
    ROUND(SUM(margin_amount), 2)    AS margin,
    ROUND(AVG(gross_amount), 2)     AS avg_order_value
FROM retail_analytics.orders
WHERE status != 'cancelled'
GROUP BY order_month
ORDER BY order_month""",
    },
    {
        "id": "revenue-by-region-channel",
        "title": "Revenue by region and channel",
        "teaches": (
            "A two-dimensional aggregation — the shape behind most BI dashboards. In IOMETE "
            "this would run from Power BI or Tableau over the same SQL endpoint."
        ),
        "difficulty": "starter",
        "chart": {"type": "grouped_bar", "x": "region", "series": "channel", "y": ["revenue"]},
        "sql": """SELECT
    region,
    channel,
    COUNT(*)                     AS orders,
    ROUND(SUM(gross_amount), 2)  AS revenue
FROM retail_analytics.orders
WHERE status = 'delivered'
GROUP BY region, channel
ORDER BY revenue DESC""",
    },
    {
        "id": "top-products",
        "title": "Top products by margin",
        "teaches": (
            "A join across two Iceberg tables. Spark shuffles rows so matching product keys "
            "land on the same executor — the shuffle is the expensive step, and it is what "
            "the execution plan below makes visible."
        ),
        "difficulty": "intermediate",
        "chart": {"type": "bar", "x": "product_name", "y": ["total_margin"]},
        "sql": """SELECT
    p.sku,
    p.product_name,
    p.category,
    SUM(oi.quantity)                                      AS units_sold,
    ROUND(SUM(oi.line_total), 2)                          AS revenue,
    ROUND(SUM(oi.line_total - (p.unit_cost * oi.quantity)), 2) AS total_margin
FROM retail_analytics.order_items oi
JOIN retail_analytics.products p ON p.product_id = oi.product_id
GROUP BY p.sku, p.product_name, p.category
ORDER BY total_margin DESC
LIMIT 15""",
    },
    {
        "id": "category-performance",
        "title": "Category performance with margin rate",
        "teaches": (
            "Derived metrics computed at query time. Because there is one governed copy of "
            "the data, every team computes margin the same way instead of each maintaining "
            "its own extract."
        ),
        "difficulty": "intermediate",
        "chart": {"type": "bar", "x": "category", "y": ["revenue", "revenue_per_unit"]},
        "sql": """SELECT
    category,
    COUNT(DISTINCT order_id)                            AS orders,
    SUM(quantity)                                       AS units,
    ROUND(SUM(line_total), 2)                           AS revenue,
    ROUND(SUM(line_total) / SUM(quantity), 2)           AS revenue_per_unit
FROM retail_analytics.order_items
GROUP BY category
ORDER BY revenue DESC""",
    },
    {
        "id": "conversion-funnel",
        "title": "Clickstream conversion funnel",
        "teaches": (
            "Analysing near-real-time event data alongside historical orders — the same "
            "tables, no separate streaming warehouse. In IOMETE these events arrive through "
            "Event Streams over HTTP."
        ),
        "difficulty": "intermediate",
        "chart": {"type": "funnel", "x": "event_type", "y": ["events"]},
        "sql": """SELECT
    event_type,
    COUNT(*)                       AS events,
    COUNT(DISTINCT session_id)     AS sessions
FROM retail_analytics.clickstream_events
GROUP BY event_type
ORDER BY events DESC""",
    },
    {
        "id": "cohort-retention",
        "title": "Customer cohorts by signup month",
        "teaches": (
            "A CTE joining a dimension to a fact table — the kind of question that is "
            "painful when customer and order data live in different systems, and "
            "straightforward when they are tables in the same lakehouse."
        ),
        "difficulty": "advanced",
        "chart": {"type": "bar", "x": "cohort_month", "y": ["revenue"]},
        "sql": """WITH cohorts AS (
    SELECT
        customer_id,
        segment,
        SUBSTR(signup_date, 1, 7) AS cohort_month
    FROM retail_analytics.customers
)
SELECT
    c.cohort_month,
    c.segment,
    COUNT(DISTINCT o.customer_id)   AS active_customers,
    COUNT(o.order_id)               AS orders,
    ROUND(SUM(o.gross_amount), 2)   AS revenue
FROM cohorts c
JOIN retail_analytics.orders o ON o.customer_id = c.customer_id
WHERE o.status = 'delivered'
GROUP BY c.cohort_month, c.segment
HAVING COUNT(o.order_id) > 20
ORDER BY c.cohort_month, revenue DESC
LIMIT 40""",
    },
    {
        "id": "returns-analysis",
        "title": "Return rate by category and region",
        "teaches": (
            "Conditional aggregation to compute a rate. A single query answering a question "
            "that usually needs a ticket to the data team."
        ),
        "difficulty": "advanced",
        "chart": {"type": "bar", "x": "category", "y": ["return_rate_pct"]},
        "sql": """SELECT
    oi.category,
    o.region,
    COUNT(DISTINCT o.order_id)                                            AS orders,
    SUM(CASE WHEN o.status = 'returned' THEN 1 ELSE 0 END)                AS returned_lines,
    ROUND(
        100.0 * SUM(CASE WHEN o.status = 'returned' THEN 1 ELSE 0 END)
        / COUNT(*), 2
    )                                                                     AS return_rate_pct
FROM retail_analytics.order_items oi
JOIN retail_analytics.orders o ON o.order_id = oi.order_id
GROUP BY oi.category, o.region
HAVING COUNT(DISTINCT o.order_id) > 50
ORDER BY return_rate_pct DESC
LIMIT 25""",
    },
)


def sample_queries() -> list[dict]:
    return [dict(query) for query in SAMPLE_QUERIES]


def get_sample(sample_id: str) -> dict | None:
    for query in SAMPLE_QUERIES:
        if query["id"] == sample_id:
            return dict(query)
    return None
