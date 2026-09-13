"""Sprint 1G first supplier identity mapping

Revision ID: 0004_sprint1g
Revises: 0003_sprint1f
"""
from alembic import op
import sqlalchemy as sa
revision="0004_sprint1g"; down_revision="0003_sprint1f"; branch_labels=None; depends_on=None

def upgrade():
    op.create_table("hotel_external_identity_runtime",
        sa.Column("identity_id",sa.Integer(),primary_key=True,autoincrement=True),
        sa.Column("connector_id",sa.String(64),nullable=False),sa.Column("external_hotel_id",sa.String(160),nullable=False),
        sa.Column("hotel_id",sa.String(64),nullable=False),sa.Column("match_confidence_bps",sa.Integer(),nullable=False,server_default="10000"),
        sa.Column("match_method",sa.String(64),nullable=False,server_default="CONTRACTED_MAPPING"),sa.Column("status",sa.String(24),nullable=False,server_default="ACTIVE"),
        sa.Column("created_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),sa.Column("updated_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),
        sa.UniqueConstraint("connector_id","external_hotel_id",name="uq_runtime_connector_external_hotel"))
    op.create_index("ix_runtime_identity_hotel","hotel_external_identity_runtime",["hotel_id"])
    op.create_index("ix_runtime_identity_status","hotel_external_identity_runtime",["status"])
    op.create_table("connector_property_mapping_audit",
        sa.Column("audit_id",sa.Integer(),primary_key=True,autoincrement=True),sa.Column("connector_id",sa.String(64),nullable=False),
        sa.Column("external_hotel_id",sa.String(160),nullable=False),sa.Column("hotel_id",sa.String(64),nullable=True),
        sa.Column("decision",sa.String(32),nullable=False),sa.Column("detail",sa.JSON(),nullable=False),sa.Column("checked_at",sa.DateTime(timezone=True),nullable=False))
    op.create_index("ix_mapping_audit_connector","connector_property_mapping_audit",["connector_id"])
    op.create_index("ix_mapping_audit_hotel","connector_property_mapping_audit",["hotel_id"])

def downgrade():
    op.drop_table("connector_property_mapping_audit"); op.drop_table("hotel_external_identity_runtime")
