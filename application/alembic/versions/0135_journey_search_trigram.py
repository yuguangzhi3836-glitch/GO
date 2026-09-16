"""Add trigram indexes for normalized Journey contains search."""

from alembic import op

revision = "0135_journey_search_trigram"
down_revision = "0134_flight_status_width"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_go_journey_title_lower_trgm "
        "ON go_journey USING gin (lower(title) gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_go_journey_destination_lower_trgm "
        "ON go_journey USING gin (lower(coalesce(destination_summary, '')) gin_trgm_ops)"
    )


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute("DROP INDEX IF EXISTS ix_go_journey_destination_lower_trgm")
    op.execute("DROP INDEX IF EXISTS ix_go_journey_title_lower_trgm")
