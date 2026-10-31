"""
Create the optional pgvector index table.

This is the migration that lets COMPASS run with zero infrastructure on SQLite *and* use a
real approximate-nearest-neighbour index on Postgres, without maintaining two sets of
models.

How it works:

* The embedding itself lives in a portable `JSONField` on `Ticket` and `ResolutionPlaybook`.
  That is the source of truth and it exists on every backend.
* On PostgreSQL, this migration additionally creates `aiengine_vector_index`: a derived
  table with a real `vector` column and an HNSW index. `EmbeddingIndexService` keeps it in
  sync, and `HybridRetrievalService` uses it when it is present.
* On any other backend the migration is a no-op and retrieval computes exact cosine
  similarity in numpy, which at COMPASS's scale is both correct and fast.

Two things are deliberate and worth not "fixing":

1. **`CREATE EXTENSION` failure is tolerated.** The application database user frequently
   lacks the privilege, and a deployment that cannot install an *optional accelerator*
   should not fail to migrate. The failure is logged, and `describe_vector_backend()`
   reports numpy with the reason — so the operator sees the truth rather than a silent
   downgrade.
2. **The vector dimension comes from `settings.EMBEDDING_DIM` at migration time.** Changing
   that setting later does not retroactively alter this column, so
   `manage.py reembed --rebuild-index` detects the mismatch and recreates the table.
"""

from django.conf import settings
from django.db import migrations


def _dim() -> int:
    return int(getattr(settings, "EMBEDDING_DIM", 384))


def create_vector_index(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return

    dim = _dim()
    with schema_editor.connection.cursor() as cursor:
        try:
            cursor.execute("CREATE EXTENSION IF NOT EXISTS vector")
        except Exception as exc:  # noqa: BLE001
            # Optional accelerator: never block a migration over it.
            print(
                f"\n  [compass] pgvector extension unavailable ({exc}). "
                "Vector search will use the portable numpy backend. "
                "Install pgvector and re-run `manage.py migrate` to enable it."
            )
            return

        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS aiengine_vector_index (
                object_type      varchar(20) NOT NULL,
                object_id        uuid        NOT NULL,
                organization_id  uuid        NULL,
                embedding        vector({dim}) NOT NULL,
                updated_at       timestamptz NOT NULL DEFAULT NOW(),
                PRIMARY KEY (object_type, object_id)
            )
            """
        )
        # Organization is indexed because the tenant predicate is applied inside the
        # vector query, not after it — see retrieval._vector_channel_pgvector.
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS aiengine_vector_org_idx "
            "ON aiengine_vector_index (organization_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS aiengine_vector_type_idx "
            "ON aiengine_vector_index (object_type)"
        )
        try:
            # HNSW over cosine distance: the operator class must match the `<=>` operator
            # used in the query, or Postgres silently ignores the index.
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS aiengine_vector_hnsw_idx "
                "ON aiengine_vector_index USING hnsw (embedding vector_cosine_ops) "
                "WITH (m = 16, ef_construction = 64)"
            )
        except Exception as exc:  # noqa: BLE001
            print(
                f"\n  [compass] HNSW index unavailable ({exc}); falling back to an "
                "exact sequential scan inside Postgres. Requires pgvector >= 0.5.0."
            )


def drop_vector_index(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("DROP TABLE IF EXISTS aiengine_vector_index")


class Migration(migrations.Migration):
    dependencies = [
        ("aiengine", "0002_initial"),
    ]

    operations = [
        migrations.RunPython(
            create_vector_index, drop_vector_index, elidable=False
        ),
    ]
