"""
The synthetic lakehouse dataset.

A deterministic e-commerce analytics dataset: customers, products, orders and order items,
plus a clickstream events table. Generated from a fixed seed, so every environment — and
every prospect's session — sees identical data. That matters for a demo: a sample query in
the documentation has to return the numbers the documentation says it returns.

Why synthetic data generated in code rather than a fixture file: the generator encodes
realistic *structure* — seasonality, a long-tail of product popularity, a small fraction of
returns, regional skew — which is what makes the sample queries produce interesting
answers instead of uniform noise. A flat CSV of random rows demonstrates nothing.

Scale is deliberately modest (a few thousand orders). The playground's job is to explain
how a lakehouse works, not to benchmark one. Every figure shown is labelled as simulated.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
from typing import Any

#: Fixed seed. Changing it changes every documented sample result, so don't.
SEED = 20261031

DATASET_ID = "retail_analytics"
DATASET_LABEL = "Retail analytics (synthetic)"

_START = date(2024, 1, 1)
_END = date(2026, 9, 30)

_REGIONS = (
    ("EMEA", 0.34), ("North America", 0.31), ("APAC", 0.22), ("LATAM", 0.13),
)
_COUNTRIES = {
    "EMEA": ("Germany", "United Kingdom", "France", "Netherlands", "Spain", "Poland"),
    "North America": ("United States", "Canada", "Mexico"),
    "APAC": ("Japan", "Australia", "Singapore", "India", "South Korea"),
    "LATAM": ("Brazil", "Argentina", "Chile", "Colombia"),
}
_CATEGORIES = (
    ("Electronics", 0.24, (49.0, 1899.0)),
    ("Home & Kitchen", 0.19, (12.0, 499.0)),
    ("Apparel", 0.17, (9.0, 249.0)),
    ("Sports & Outdoors", 0.13, (14.0, 899.0)),
    ("Books & Media", 0.11, (5.0, 79.0)),
    ("Beauty & Health", 0.09, (6.0, 189.0)),
    ("Grocery", 0.07, (2.0, 59.0)),
)
_CHANNELS = (("web", 0.52), ("mobile_app", 0.33), ("marketplace", 0.11), ("phone", 0.04))
_STATUSES = (
    ("delivered", 0.78), ("shipped", 0.09), ("processing", 0.05),
    ("cancelled", 0.04), ("returned", 0.04),
)
_SEGMENTS = (("consumer", 0.68), ("business", 0.24), ("enterprise", 0.08))
_PAYMENT = (("card", 0.61), ("wallet", 0.21), ("bank_transfer", 0.12), ("invoice", 0.06))
_EVENTS = (
    ("page_view", 0.46), ("product_view", 0.27), ("add_to_cart", 0.14),
    ("checkout_start", 0.08), ("purchase", 0.05),
)


def _weighted(rng: random.Random, options: tuple) -> Any:
    total = sum(weight for _, weight, *_ in options)
    roll = rng.random() * total
    cumulative = 0.0
    for option in options:
        cumulative += option[1]
        if roll <= cumulative:
            return option
    return options[-1]


def _seasonality(day: date) -> float:
    """
    A multiplier that makes the time series look like retail rather than a flat line.

    November/December peak, a January trough, and a mild mid-year bump. Without this,
    "revenue by month" is a boring horizontal line and the playground's point is lost.
    """
    month_factor = {
        1: 0.78, 2: 0.84, 3: 0.95, 4: 0.97, 5: 1.02, 6: 1.08,
        7: 1.05, 8: 0.99, 9: 1.03, 10: 1.12, 11: 1.46, 12: 1.58,
    }[day.month]
    # Weekends are busier for consumer retail.
    weekday_factor = 1.18 if day.weekday() >= 5 else 0.96
    # Mild year-over-year growth, so a "this year vs last year" query is meaningful.
    growth = 1.0 + 0.11 * (day.year - _START.year)
    return month_factor * weekday_factor * growth


@dataclass
class Table:
    name: str
    description: str
    columns: list[dict]
    rows: list[tuple]
    partitioned_by: list[str] = field(default_factory=list)
    #: Iceberg-style metadata, clearly labelled simulated wherever it is surfaced.
    simulated_metadata: dict = field(default_factory=dict)

    @property
    def row_count(self) -> int:
        return len(self.rows)

    def schema_payload(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "columns": self.columns,
            "row_count": self.row_count,
            "partitioned_by": self.partitioned_by,
            "simulated_metadata": self.simulated_metadata,
            "ddl": self.ddl(),
        }

    def ddl(self) -> str:
        """
        Iceberg-flavoured CREATE TABLE, for display.

        Shown so a prospect can see what an Iceberg table declaration actually looks like —
        `USING iceberg`, partitioning, table properties. Labelled as illustrative because
        the playground executes against SQLite, not Spark.
        """
        lines = [f"CREATE TABLE {DATASET_ID}.{self.name} ("]
        width = max(len(c["name"]) for c in self.columns) + 2
        for index, column in enumerate(self.columns):
            comma = "," if index < len(self.columns) - 1 else ""
            comment = f"  -- {column['description']}" if column.get("description") else ""
            lines.append(
                f"  {column['name']:<{width}}{column['iceberg_type']}{comma}{comment}"
            )
        lines.append(")")
        lines.append("USING iceberg")
        if self.partitioned_by:
            lines.append(f"PARTITIONED BY ({', '.join(self.partitioned_by)})")
        lines.append("TBLPROPERTIES (")
        lines.append("  'format-version' = '2',")
        lines.append("  'write.delete.mode' = 'copy-on-write',")
        lines.append("  'write.parquet.compression-codec' = 'zstd'")
        lines.append(")")
        return "\n".join(lines)


def _simulated_metadata(rng: random.Random, row_count: int, partitions: int) -> dict:
    """
    Plausible Iceberg table metadata for display.

    Every consumer of this labels it `simulated: true`. It exists to teach what Iceberg
    tracks — snapshots, manifests, file counts, a current snapshot id — not to report real
    figures. Deriving the numbers from the actual row count keeps it internally consistent,
    which matters because a prospect who notices the numbers do not add up stops trusting
    the whole demo.
    """
    files = max(1, partitions * rng.randint(1, 3))
    snapshots = []
    base = datetime(2026, 9, 30, 2, 15, tzinfo=UTC)
    for index in range(4):
        moment = base - timedelta(days=index * 7, hours=index)
        snapshots.append(
            {
                "snapshot_id": 3_900_000_000_000_000_000 + rng.randint(10**15, 9 * 10**17),
                "committed_at": moment.isoformat(),
                "operation": "append" if index else "overwrite",
                "added_files": rng.randint(1, 6),
                "added_records": int(row_count * rng.uniform(0.02, 0.09)),
                "summary": "Scheduled ingestion job" if index else "Daily compaction",
            }
        )
    return {
        "simulated": True,
        "notice": (
            "Illustrative Iceberg metadata, generated to show what the table format tracks. "
            "These are not figures from a real IOMETE deployment."
        ),
        "format_version": 2,
        "current_snapshot_id": snapshots[0]["snapshot_id"],
        "total_data_files": files,
        "total_delete_files": rng.randint(0, 2),
        "total_records": row_count,
        "estimated_size_bytes": int(row_count * rng.uniform(180, 420)),
        "manifest_files": max(1, files // 4),
        "snapshots": snapshots,
        "capabilities_demonstrated": [
            "ACID transactions — each snapshot is an atomic commit",
            "Time travel — query the table as of any snapshot id or timestamp",
            "Rollback — restore the table to an earlier snapshot",
            "Schema and partition evolution — without rewriting the data",
            "Concurrent writes — readers never see a partial commit",
        ],
    }


@lru_cache(maxsize=1)
def build() -> dict[str, Table]:
    """
    Generate the dataset. Cached for the process lifetime — it is static and identical
    everywhere, so regenerating it per request would be pure waste.
    """
    rng = random.Random(SEED)

    # --- customers -----------------------------------------------------------------
    customers: list[tuple] = []
    for customer_id in range(1, 801):
        region, _ = _weighted(rng, _REGIONS)[:2]
        country = rng.choice(_COUNTRIES[region])
        segment, _ = _weighted(rng, _SEGMENTS)[:2]
        signup = _START + timedelta(days=rng.randint(0, (_END - _START).days - 30))
        customers.append(
            (
                customer_id,
                f"CUST-{customer_id:05d}",
                region,
                country,
                segment,
                signup.isoformat(),
                round(rng.uniform(0.0, 1.0), 3),
            )
        )

    customers_table = Table(
        name="customers",
        description=(
            "One row per customer account, with region, country and commercial segment. "
            "Slowly changing — in a real lakehouse this would be a dimension table updated "
            "by merge-on-read."
        ),
        columns=[
            {"name": "customer_id", "iceberg_type": "bigint", "sql_type": "INTEGER",
             "description": "Surrogate key"},
            {"name": "customer_ref", "iceberg_type": "string", "sql_type": "TEXT",
             "description": "Business-facing reference"},
            {"name": "region", "iceberg_type": "string", "sql_type": "TEXT",
             "description": "EMEA / North America / APAC / LATAM"},
            {"name": "country", "iceberg_type": "string", "sql_type": "TEXT",
             "description": "Country of the billing address"},
            {"name": "segment", "iceberg_type": "string", "sql_type": "TEXT",
             "description": "consumer / business / enterprise"},
            {"name": "signup_date", "iceberg_type": "date", "sql_type": "TEXT",
             "description": "When the account was created"},
            {"name": "loyalty_score", "iceberg_type": "double", "sql_type": "REAL",
             "description": "Modelled engagement score, 0–1"},
        ],
        rows=customers,
        partitioned_by=["region"],
        simulated_metadata=_simulated_metadata(rng, len(customers), 4),
    )

    # --- products ------------------------------------------------------------------
    products: list[tuple] = []
    category_of: dict[int, str] = {}
    price_of: dict[int, float] = {}
    for product_id in range(1, 241):
        category, _, (low, high) = _weighted(rng, _CATEGORIES)
        # Log-uniform pricing: realistic long tail rather than a flat spread.
        price = round(low * (high / low) ** rng.random(), 2)
        category_of[product_id] = category
        price_of[product_id] = price
        products.append(
            (
                product_id,
                f"SKU-{product_id:05d}",
                category,
                f"{category.split(' ')[0]} item {product_id}",
                price,
                round(price * rng.uniform(0.42, 0.78), 2),
                rng.choice(("active", "active", "active", "discontinued")),
            )
        )

    products_table = Table(
        name="products",
        description="Product catalogue with list price and unit cost, so margin is derivable.",
        columns=[
            {"name": "product_id", "iceberg_type": "bigint", "sql_type": "INTEGER",
             "description": "Surrogate key"},
            {"name": "sku", "iceberg_type": "string", "sql_type": "TEXT",
             "description": "Stock-keeping unit"},
            {"name": "category", "iceberg_type": "string", "sql_type": "TEXT",
             "description": "Product category"},
            {"name": "product_name", "iceberg_type": "string", "sql_type": "TEXT",
             "description": "Display name"},
            {"name": "list_price", "iceberg_type": "decimal(10,2)", "sql_type": "REAL",
             "description": "Current list price"},
            {"name": "unit_cost", "iceberg_type": "decimal(10,2)", "sql_type": "REAL",
             "description": "Cost of goods — margin = list_price - unit_cost"},
            {"name": "status", "iceberg_type": "string", "sql_type": "TEXT",
             "description": "active / discontinued"},
        ],
        rows=products,
        partitioned_by=["category"],
        simulated_metadata=_simulated_metadata(rng, len(products), 7),
    )

    # --- orders and order_items ----------------------------------------------------
    orders: list[tuple] = []
    order_items: list[tuple] = []
    order_id = 0
    item_id = 0
    total_days = (_END - _START).days

    # Popularity follows a long tail, so "top products" is interesting.
    popularity = sorted(
        range(1, 241), key=lambda _: rng.random()
    )
    popularity_weights = [1.0 / (index + 3) ** 0.85 for index in range(len(popularity))]

    for day_offset in range(total_days + 1):
        day = _START + timedelta(days=day_offset)
        expected = 5.5 * _seasonality(day)
        count = max(0, int(rng.gauss(expected, expected * 0.35)))
        for _ in range(count):
            order_id += 1
            customer = rng.randint(1, 800)
            region = customers[customer - 1][2]
            channel, _ = _weighted(rng, _CHANNELS)[:2]
            status, _ = _weighted(rng, _STATUSES)[:2]
            payment, _ = _weighted(rng, _PAYMENT)[:2]
            ordered_at = datetime(
                day.year, day.month, day.day,
                rng.randint(0, 23), rng.randint(0, 59), rng.randint(0, 59),
                tzinfo=UTC,
            )

            line_count = rng.choices((1, 2, 3, 4, 5), weights=(0.42, 0.26, 0.17, 0.09, 0.06))[0]
            order_total = 0.0
            order_cost = 0.0
            for _ in range(line_count):
                item_id += 1
                product = rng.choices(popularity, weights=popularity_weights, k=1)[0]
                quantity = rng.choices((1, 2, 3, 6), weights=(0.68, 0.19, 0.09, 0.04))[0]
                unit_price = round(price_of[product] * rng.uniform(0.85, 1.0), 2)
                line_total = round(unit_price * quantity, 2)
                order_total += line_total
                order_cost += round(products[product - 1][5] * quantity, 2)
                order_items.append(
                    (
                        item_id, order_id, product, quantity, unit_price, line_total,
                        category_of[product],
                    )
                )

            shipping = 0.0 if order_total > 75 else round(rng.uniform(3.5, 12.0), 2)
            orders.append(
                (
                    order_id,
                    f"ORD-{order_id:07d}",
                    customer,
                    ordered_at.isoformat(),
                    day.isoformat(),
                    day.strftime("%Y-%m"),
                    region,
                    channel,
                    status,
                    payment,
                    round(order_total, 2),
                    shipping,
                    round(order_total + shipping, 2),
                    round(order_total - order_cost, 2),
                    line_count,
                )
            )

    orders_table = Table(
        name="orders",
        description=(
            "One row per order. Partitioned by order month — the column a dashboard filters "
            "on, which is what makes partition pruning effective."
        ),
        columns=[
            {"name": "order_id", "iceberg_type": "bigint", "sql_type": "INTEGER",
             "description": "Surrogate key"},
            {"name": "order_ref", "iceberg_type": "string", "sql_type": "TEXT",
             "description": "Business-facing order reference"},
            {"name": "customer_id", "iceberg_type": "bigint", "sql_type": "INTEGER",
             "description": "Joins to customers.customer_id"},
            {"name": "ordered_at", "iceberg_type": "timestamp", "sql_type": "TEXT",
             "description": "Order timestamp, UTC"},
            {"name": "order_date", "iceberg_type": "date", "sql_type": "TEXT",
             "description": "Date part, for daily aggregation"},
            {"name": "order_month", "iceberg_type": "string", "sql_type": "TEXT",
             "description": "YYYY-MM — the partition key"},
            {"name": "region", "iceberg_type": "string", "sql_type": "TEXT",
             "description": "Denormalised from the customer, as a warehouse would"},
            {"name": "channel", "iceberg_type": "string", "sql_type": "TEXT",
             "description": "web / mobile_app / marketplace / phone"},
            {"name": "status", "iceberg_type": "string", "sql_type": "TEXT",
             "description": "delivered / shipped / processing / cancelled / returned"},
            {"name": "payment_method", "iceberg_type": "string", "sql_type": "TEXT",
             "description": "card / wallet / bank_transfer / invoice"},
            {"name": "net_amount", "iceberg_type": "decimal(12,2)", "sql_type": "REAL",
             "description": "Goods value excluding shipping"},
            {"name": "shipping_amount", "iceberg_type": "decimal(12,2)", "sql_type": "REAL",
             "description": "Shipping charged (free above 75)"},
            {"name": "gross_amount", "iceberg_type": "decimal(12,2)", "sql_type": "REAL",
             "description": "Total charged"},
            {"name": "margin_amount", "iceberg_type": "decimal(12,2)", "sql_type": "REAL",
             "description": "net_amount minus cost of goods"},
            {"name": "line_count", "iceberg_type": "int", "sql_type": "INTEGER",
             "description": "Number of order lines"},
        ],
        rows=orders,
        partitioned_by=["order_month"],
        simulated_metadata=_simulated_metadata(rng, len(orders), 33),
    )

    order_items_table = Table(
        name="order_items",
        description="One row per order line. The fact table most analytical queries start from.",
        columns=[
            {"name": "order_item_id", "iceberg_type": "bigint", "sql_type": "INTEGER",
             "description": "Surrogate key"},
            {"name": "order_id", "iceberg_type": "bigint", "sql_type": "INTEGER",
             "description": "Joins to orders.order_id"},
            {"name": "product_id", "iceberg_type": "bigint", "sql_type": "INTEGER",
             "description": "Joins to products.product_id"},
            {"name": "quantity", "iceberg_type": "int", "sql_type": "INTEGER",
             "description": "Units ordered"},
            {"name": "unit_price", "iceberg_type": "decimal(10,2)", "sql_type": "REAL",
             "description": "Price actually charged per unit"},
            {"name": "line_total", "iceberg_type": "decimal(12,2)", "sql_type": "REAL",
             "description": "quantity × unit_price"},
            {"name": "category", "iceberg_type": "string", "sql_type": "TEXT",
             "description": "Denormalised product category"},
        ],
        rows=order_items,
        partitioned_by=["category"],
        simulated_metadata=_simulated_metadata(rng, len(order_items), 7),
    )

    # --- clickstream events --------------------------------------------------------
    events: list[tuple] = []
    event_id = 0
    # Sampled rather than exhaustive: enough rows to demonstrate a funnel without making
    # the in-memory dataset unwieldy.
    for day_offset in range(0, total_days + 1, 2):
        day = _START + timedelta(days=day_offset)
        for _ in range(int(28 * _seasonality(day))):
            event_id += 1
            event_type, _ = _weighted(rng, _EVENTS)[:2]
            customer = rng.randint(1, 800) if rng.random() < 0.62 else None
            events.append(
                (
                    event_id,
                    datetime(
                        day.year, day.month, day.day,
                        rng.randint(0, 23), rng.randint(0, 59), rng.randint(0, 59),
                        tzinfo=UTC,
                    ).isoformat(),
                    day.strftime("%Y-%m"),
                    event_type,
                    customer,
                    rng.randint(1, 240) if event_type != "page_view" else None,
                    rng.choice(("web", "mobile_app")),
                    f"sess-{rng.randint(10**6, 10**7 - 1)}",
                )
            )

    events_table = Table(
        name="clickstream_events",
        description=(
            "Sampled web and app events. In IOMETE this is the shape of table Event Streams "
            "writes to — HTTP POST ingestion landing in Iceberg in near real time."
        ),
        columns=[
            {"name": "event_id", "iceberg_type": "bigint", "sql_type": "INTEGER",
             "description": "Surrogate key"},
            {"name": "event_at", "iceberg_type": "timestamp", "sql_type": "TEXT",
             "description": "Event timestamp, UTC"},
            {"name": "event_month", "iceberg_type": "string", "sql_type": "TEXT",
             "description": "YYYY-MM — the partition key"},
            {"name": "event_type", "iceberg_type": "string", "sql_type": "TEXT",
             "description": "page_view / product_view / add_to_cart / checkout_start / purchase"},
            {"name": "customer_id", "iceberg_type": "bigint", "sql_type": "INTEGER",
             "description": "Null for anonymous sessions"},
            {"name": "product_id", "iceberg_type": "bigint", "sql_type": "INTEGER",
             "description": "Null for non-product events"},
            {"name": "device", "iceberg_type": "string", "sql_type": "TEXT",
             "description": "web / mobile_app"},
            {"name": "session_id", "iceberg_type": "string", "sql_type": "TEXT",
             "description": "Session identifier"},
        ],
        rows=events,
        partitioned_by=["event_month"],
        simulated_metadata=_simulated_metadata(rng, len(events), 33),
    )

    return {
        "customers": customers_table,
        "products": products_table,
        "orders": orders_table,
        "order_items": order_items_table,
        "clickstream_events": events_table,
    }


def tables() -> dict[str, Table]:
    return build()


def describe() -> dict:
    """Dataset overview for the playground's schema panel."""
    built = build()
    return {
        "dataset_id": DATASET_ID,
        "label": DATASET_LABEL,
        "description": (
            "A synthetic retail analytics dataset — customers, products, orders, order "
            "lines and clickstream events — generated deterministically from a fixed seed. "
            "It models realistic structure (seasonality, a long tail of product "
            "popularity, returns, regional skew) so the sample queries produce meaningful "
            "answers."
        ),
        "is_synthetic": True,
        "synthetic_notice": (
            "This is synthetic data, generated deterministically for demonstration. It does "
            "not represent any real company's data, and the Iceberg metadata shown "
            "alongside it is illustrative rather than read from a live IOMETE deployment."
        ),
        "date_range": {"from": _START.isoformat(), "to": _END.isoformat()},
        "total_rows": sum(table.row_count for table in built.values()),
        "tables": [table.schema_payload() for table in built.values()],
        "pipeline": pipeline_stages(),
    }


def pipeline_stages() -> list[dict]:
    """
    The conceptual workflow the playground animates.

    Each stage names the IOMETE component responsible and cites the knowledge base, so the
    explanation is source-backed rather than a generic lakehouse diagram.
    """
    return [
        {
            "order": 1,
            "id": "ingest",
            "title": "Data enters the platform",
            "summary": (
                "Orders arrive from the operational database via a scheduled Spark job; "
                "clickstream events arrive over HTTP through Event Streams and land in "
                "Iceberg within moments."
            ),
            "iomete_component": "Spark Jobs / Event Streams (Papyrus)",
            "sources": ["S3", "S4", "S10"],
        },
        {
            "order": 2,
            "id": "store",
            "title": "Data is stored in object storage you own",
            "summary": (
                "Files land in your own bucket under `data/`. Storage is decoupled from "
                "compute, which is what makes it cheap and independently scalable."
            ),
            "iomete_component": "Object storage (s3a:// / gs:// / abfs://)",
            "sources": ["S4", "S8"],
        },
        {
            "order": 3,
            "id": "organise",
            "title": "Files become Iceberg tables",
            "summary": (
                "Apache Iceberg adds a metadata layer: ACID commits, snapshots you can "
                "time-travel to, schema and partition evolution, and safe concurrent "
                "writes. This is the step that turns a pile of files into a table."
            ),
            "iomete_component": "Apache Iceberg + Iceberg REST Catalog",
            "sources": ["S4", "S7"],
        },
        {
            "order": 4,
            "id": "govern",
            "title": "Access policy is applied at the catalog",
            "summary": (
                "Apache Ranger policies are enforced by the Iceberg REST Catalog, so every "
                "engine reading these tables is subject to the same row, column and "
                "tag-level rules — not just the one BI tool that was configured."
            ),
            "iomete_component": "Iceberg REST Catalog + Identity Service (Ranger)",
            "sources": ["S1", "S4"],
        },
        {
            "order": 5,
            "id": "process",
            "title": "Spark processes the data",
            "summary": (
                "A compute cluster runs a Spark driver with executors that scale from one "
                "up to a configured maximum and back to zero when idle. You pay for "
                "executors only while queries run."
            ),
            "iomete_component": "Compute Clusters (Apache Spark)",
            "sources": ["S4", "S9"],
        },
        {
            "order": 6,
            "id": "query",
            "title": "SQL answers the business question",
            "summary": (
                "Analysts write SQL in the browser workspace with auto-completion, history "
                "and visual explain plans. BI tools connect to the same clusters over "
                "HiveServer2 JDBC/ODBC or Arrow Flight."
            ),
            "iomete_component": "SQL Service + Gateway",
            "sources": ["S1", "S3", "S4", "S10"],
        },
        {
            "order": 7,
            "id": "consume",
            "title": "Results reach people and models",
            "summary": (
                "Dashboards, notebooks and ML workloads all read the same governed tables. "
                "One copy of the data, so there is nothing to reconcile."
            ),
            "iomete_component": "BI integrations + Jupyter containers",
            "sources": ["S3", "S4", "S5"],
        },
    ]
