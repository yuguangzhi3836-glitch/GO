"""Sprint 1K prebook revalidation and booking consistency
Revision ID: 0008_sprint1k
Revises: 0007_sprint1j
"""
from alembic import op
import sqlalchemy as sa
revision="0008_sprint1k"
down_revision="0007_sprint1j"
branch_labels=None
depends_on=None

def upgrade():
    with op.batch_alter_table("prebook") as b:
        b.add_column(sa.Column("hold_type",sa.String(16),nullable=False,server_default="SOFT"))
        b.add_column(sa.Column("inventory_held",sa.Boolean(),nullable=False,server_default=sa.false()))
        b.add_column(sa.Column("price_locked",sa.Boolean(),nullable=False,server_default=sa.true()))
        b.add_column(sa.Column("fare_rule_id",sa.String(64),nullable=True))
        b.add_column(sa.Column("benefits_fingerprint",sa.String(64),nullable=True))
    op.create_table("prebook_revalidation",
        sa.Column("revalidation_id",sa.String(64),primary_key=True),sa.Column("offer_id",sa.String(64),nullable=False),sa.Column("prebook_id",sa.String(64)),sa.Column("connector_id",sa.String(64),nullable=False),sa.Column("original_total_minor",sa.BigInteger(),nullable=False),sa.Column("supplier_total_minor",sa.BigInteger()),sa.Column("currency",sa.String(3),nullable=False),sa.Column("price_status",sa.String(32),nullable=False),sa.Column("inventory_status",sa.String(32),nullable=False),sa.Column("policy_status",sa.String(32),nullable=False),sa.Column("benefit_status",sa.String(32),nullable=False),sa.Column("hold_type",sa.String(16),nullable=False),sa.Column("lock_expires_at",sa.DateTime(timezone=True)),sa.Column("snapshot",sa.JSON(),nullable=False),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False))
    op.create_index("ix_prebook_revalidation_offer_time","prebook_revalidation",["offer_id","created_at"])
    op.create_table("booking_consistency_check",
        sa.Column("check_id",sa.String(64),primary_key=True),sa.Column("order_id",sa.String(64),nullable=False),sa.Column("prebook_id",sa.String(64),nullable=False),sa.Column("stage",sa.String(32),nullable=False),sa.Column("result",sa.String(24),nullable=False),sa.Column("reason_codes",sa.JSON(),nullable=False),sa.Column("snapshot",sa.JSON(),nullable=False),sa.Column("checked_at",sa.DateTime(timezone=True),nullable=False))
    op.create_index("ix_booking_consistency_order_stage","booking_consistency_check",["order_id","stage","checked_at"])

def downgrade():
    op.drop_index("ix_booking_consistency_order_stage",table_name="booking_consistency_check"); op.drop_table("booking_consistency_check")
    op.drop_index("ix_prebook_revalidation_offer_time",table_name="prebook_revalidation"); op.drop_table("prebook_revalidation")
    with op.batch_alter_table("prebook") as b:
        for c in ["benefits_fingerprint","fare_rule_id","price_locked","inventory_held","hold_type"]: b.drop_column(c)
