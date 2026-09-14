"""Preserve complete flight payment states in existing and fresh databases."""
from alembic import op
import sqlalchemy as sa

revision = "0134_flight_status_width"
down_revision = "0133_flight_change_plan"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("flight_order_runtime") as batch:
        batch.alter_column(
            "status", existing_type=sa.String(32), type_=sa.String(64),
            existing_nullable=False,
        )


def downgrade():
    # A PostgreSQL narrowing cast may truncate: reject before changing the column.
    count = op.get_bind().execute(sa.text(
        "SELECT count(*) FROM flight_order_runtime WHERE length(status) > 32"
    )).scalar_one()
    if count:
        raise RuntimeError("FLIGHT_STATUS_DOWNGRADE_WOULD_TRUNCATE_HISTORY")
    with op.batch_alter_table("flight_order_runtime") as batch:
        batch.alter_column(
            "status", existing_type=sa.String(64), type_=sa.String(32),
            existing_nullable=False,
        )
