"""sprint 1j multi-source dedup merge and drift
Revision ID: 0007_sprint1j
Revises: 0006_sprint1i
"""
from alembic import op
import sqlalchemy as sa
revision="0007_sprint1j"
down_revision="0006_sprint1i"
branch_labels=None
depends_on=None

def upgrade():
    with op.batch_alter_table("offer_snapshot") as b:
        b.add_column(sa.Column("base_amount_minor",sa.BigInteger(),nullable=True))
        b.add_column(sa.Column("tax_amount_minor",sa.BigInteger(),nullable=False,server_default="0"))
        b.add_column(sa.Column("fee_amount_minor",sa.BigInteger(),nullable=False,server_default="0"))
        b.add_column(sa.Column("meal_plan",sa.String(32),nullable=False,server_default="ROOM_ONLY"))
        b.add_column(sa.Column("refundable",sa.Boolean(),nullable=False,server_default=sa.true()))
        b.add_column(sa.Column("cancellation_deadline",sa.String(64),nullable=True))
        b.add_column(sa.Column("inventory_units",sa.Integer(),nullable=True))
    op.create_table("room_external_identity_runtime",
        sa.Column("identity_id",sa.Integer(),primary_key=True,autoincrement=True),sa.Column("connector_id",sa.String(64),nullable=False),sa.Column("external_room_id",sa.String(160),nullable=False),sa.Column("canonical_room_id",sa.String(160),nullable=False),sa.Column("match_confidence_bps",sa.Integer(),nullable=False,server_default="10000"),sa.Column("match_method",sa.String(64),nullable=False,server_default="CONTRACTED_MAPPING"),sa.Column("status",sa.String(24),nullable=False,server_default="ACTIVE"),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False),sa.Column("updated_at",sa.DateTime(timezone=True),nullable=False),sa.UniqueConstraint("connector_id","external_room_id",name="uq_room_connector_external"))
    op.create_index("ix_room_external_identity_runtime_canonical_room_id","room_external_identity_runtime",["canonical_room_id"])
    op.create_table("offer_merge_decision",
        sa.Column("decision_id",sa.String(64),primary_key=True),sa.Column("hotel_id",sa.String(64),nullable=False),sa.Column("canonical_room_id",sa.String(160),nullable=False),sa.Column("selected_offer_id",sa.String(64),nullable=False),sa.Column("selected_connector_id",sa.String(64),nullable=False),sa.Column("alternate_offer_ids",sa.JSON(),nullable=False),sa.Column("reason_codes",sa.JSON(),nullable=False),sa.Column("conflicts",sa.JSON(),nullable=False),sa.Column("candidate_snapshot",sa.JSON(),nullable=False),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False))
    op.create_index("ix_offer_merge_hotel_room","offer_merge_decision",["hotel_id","canonical_room_id","created_at"])
    op.create_table("offer_drift_state",
        sa.Column("drift_key",sa.String(512),primary_key=True),sa.Column("connector_id",sa.String(64),nullable=False),sa.Column("hotel_id",sa.String(64),nullable=False),sa.Column("canonical_room_id",sa.String(160),nullable=False),sa.Column("fingerprint",sa.String(64),nullable=False),sa.Column("snapshot",sa.JSON(),nullable=False),sa.Column("updated_at",sa.DateTime(timezone=True),nullable=False))
    op.create_table("offer_drift_event",
        sa.Column("drift_id",sa.String(64),primary_key=True),sa.Column("drift_key",sa.String(512),nullable=False),sa.Column("connector_id",sa.String(64),nullable=False),sa.Column("hotel_id",sa.String(64),nullable=False),sa.Column("canonical_room_id",sa.String(160),nullable=False),sa.Column("changed_fields",sa.JSON(),nullable=False),sa.Column("before_snapshot",sa.JSON(),nullable=False),sa.Column("after_snapshot",sa.JSON(),nullable=False),sa.Column("detected_at",sa.DateTime(timezone=True),nullable=False),sa.Column("status",sa.String(24),nullable=False,server_default="OPEN"))
    op.create_index("ix_offer_drift_hotel_time","offer_drift_event",["hotel_id","detected_at"])

def downgrade():
    op.drop_table("offer_drift_event"); op.drop_table("offer_drift_state"); op.drop_table("offer_merge_decision"); op.drop_table("room_external_identity_runtime")
    with op.batch_alter_table("offer_snapshot") as b:
        for c in ["inventory_units","cancellation_deadline","refundable","meal_plan","fee_amount_minor","tax_amount_minor","base_amount_minor"]: b.drop_column(c)
