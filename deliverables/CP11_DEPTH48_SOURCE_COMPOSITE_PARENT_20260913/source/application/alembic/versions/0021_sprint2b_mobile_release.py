"""Sprint 2B real-device QA, push receipt lifecycle and mobile release hardening.

Revision ID: 0021_sprint2b
Revises: 0020_sprint2a
"""
from alembic import op
import sqlalchemy as sa

revision = "0021_sprint2b"
down_revision = "0020_sprint2a"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        "mobile_push_receipt",
        sa.Column("receipt_id", sa.String(64), primary_key=True),
        sa.Column("notification_id", sa.String(64), nullable=False),
        sa.Column("device_id", sa.String(64), nullable=False),
        sa.Column("provider", sa.String(24), nullable=False),
        sa.Column("provider_message_id", sa.String(160), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="SUBMITTED"),
        sa.Column("error_code", sa.String(96), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_mobile_push_receipt_notification", "mobile_push_receipt", ["notification_id"])
    op.create_index("ix_mobile_push_receipt_device", "mobile_push_receipt", ["device_id"])
    op.create_index("ix_mobile_push_receipt_provider_message", "mobile_push_receipt", ["provider_message_id"])
    op.create_index("ix_mobile_push_receipt_status", "mobile_push_receipt", ["status"])
    op.create_index("ix_mobile_push_receipt_status_submitted", "mobile_push_receipt", ["status", "submitted_at"])

def downgrade():
    op.drop_table("mobile_push_receipt")
