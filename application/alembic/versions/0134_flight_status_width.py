"""Preserve complete flight payment states in existing and fresh databases."""
from alembic import op
import sqlalchemy as sa

revision = "0134_flight_status_width"
down_revision = "0133_flight_change_plan"
branch_labels = None
depends_on = None


def upgrade():
    # Legacy SQLite partial histories may omit the flight runtime entirely.
    # Do not manufacture a business table or hide a missing PostgreSQL table.
    bind = op.get_bind()
    if bind.dialect.name == "sqlite" and not sa.inspect(bind).has_table("flight_order_runtime"):
        return
    with op.batch_alter_table("flight_order_runtime") as batch:
        batch.alter_column(
            "status", existing_type=sa.String(32), type_=sa.String(64),
            existing_nullable=False,
        )


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name == "sqlite" and not sa.inspect(bind).has_table("flight_order_runtime"):
        return
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
