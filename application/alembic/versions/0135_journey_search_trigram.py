"""Add online trigram indexes for normalized Journey contains search."""

from alembic import op
import sqlalchemy as sa

revision = "0135_journey_search_trigram"
down_revision = "0134_flight_status_width"
branch_labels = None
depends_on = None

TABLE = "go_journey_runtime"
INDEXES = (
    ("ix_go_journey_title_lower_trgm", "lower(title)"),
    ("ix_go_journey_destination_lower_trgm", "lower(coalesce(destination_summary, ''))"),
)


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name != "postgresql" or not sa.inspect(bind).has_table(TABLE):
        return
    # CREATE INDEX CONCURRENTLY is forbidden inside a transaction. Alembic's
    # autocommit block commits the migration transaction before each online DDL.
    with op.get_context().autocommit_block():
        op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
        for name, expression in INDEXES:
            op.execute(
                f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {name} "
                f"ON {TABLE} USING gin ({expression} gin_trgm_ops)"
            )


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    with op.get_context().autocommit_block():
        for name, _ in reversed(INDEXES):
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {name}")
