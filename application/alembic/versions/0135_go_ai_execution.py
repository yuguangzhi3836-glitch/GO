"""Add GO AI-specific durable execution ownership and checkpoints."""
from alembic import op
import sqlalchemy as sa

revision = "0135_go_ai_execution"
down_revision = "0134_flight_status_width"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "go_ai_execution",
        sa.Column("go_ai_request_id", sa.String(64), primary_key=True),
        sa.Column("owner_id", sa.String(128), nullable=False),
        sa.Column("fencing_token", sa.BigInteger(), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("checkpoint_json", sa.JSON(), nullable=True),
        sa.Column("checkpoint_hash", sa.String(64), nullable=True),
        sa.Column("checkpoint_complete", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("provider_outcome", sa.String(32), nullable=False, server_default="NOT_STARTED"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_go_ai_execution_owner_id", "go_ai_execution", ["owner_id"])
    op.create_index("ix_go_ai_execution_lease_expires_at", "go_ai_execution", ["lease_expires_at"])
    op.create_index("ix_go_ai_execution_state", "go_ai_execution", ["state"])


def downgrade():
    op.drop_index("ix_go_ai_execution_state", table_name="go_ai_execution")
    op.drop_index("ix_go_ai_execution_lease_expires_at", table_name="go_ai_execution")
    op.drop_index("ix_go_ai_execution_owner_id", table_name="go_ai_execution")
    op.drop_table("go_ai_execution")
