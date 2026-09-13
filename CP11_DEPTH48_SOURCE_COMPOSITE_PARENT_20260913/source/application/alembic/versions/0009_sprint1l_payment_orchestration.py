"""Sprint 1L payment authorization/book/capture orchestration

Revision ID: 0009_sprint1l
Revises: 0008_sprint1k
"""
from alembic import op
import sqlalchemy as sa

revision = "0009_sprint1l"
down_revision = "0008_sprint1k"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        "payment_booking_orchestration",
        sa.Column("orchestration_id", sa.String(64), primary_key=True),
        sa.Column("order_id", sa.String(64), nullable=False, unique=True),
        sa.Column("payment_id", sa.String(64), nullable=True),
        sa.Column("phase", sa.String(40), nullable=False),
        sa.Column("supplier_confirmation_no", sa.String(128), nullable=True),
        sa.Column("compensation_status", sa.String(32), nullable=False, server_default="NONE"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_payment_booking_orch_order", "payment_booking_orchestration", ["order_id"], unique=True)
    op.create_index("ix_payment_booking_orch_phase", "payment_booking_orchestration", ["phase"])

def downgrade():
    op.drop_index("ix_payment_booking_orch_phase", table_name="payment_booking_orchestration")
    op.drop_index("ix_payment_booking_orch_order", table_name="payment_booking_orchestration")
    op.drop_table("payment_booking_orchestration")
