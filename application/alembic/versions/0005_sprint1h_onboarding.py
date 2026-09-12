"""Sprint 1H supplier onboarding, credential vault metadata, property mapping and activation workflow.

Revision ID: 0005_sprint1h
Revises: 0004_sprint1g
"""
from alembic import op
import sqlalchemy as sa

revision="0005_sprint1h"
down_revision="0004_sprint1g"
branch_labels=None
depends_on=None

def upgrade():
    op.create_table("supplier_connector_onboarding",
        sa.Column("onboarding_id",sa.String(64),primary_key=True),sa.Column("supplier_id",sa.String(64),nullable=False),sa.Column("connector_id",sa.String(64),nullable=False),sa.Column("environment",sa.String(24),nullable=False),sa.Column("status",sa.String(40),nullable=False),sa.Column("rollout_percent",sa.Integer(),nullable=False,server_default="0"),sa.Column("last_certification_id",sa.Integer()),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False),sa.Column("updated_at",sa.DateTime(timezone=True),nullable=False),sa.Column("activated_at",sa.DateTime(timezone=True)),sa.Column("suspended_at",sa.DateTime(timezone=True)),sa.UniqueConstraint("supplier_id","connector_id","environment",name="uq_supplier_connector_onboarding"))
    op.create_index("ix_supplier_connector_onboarding_supplier_id","supplier_connector_onboarding",["supplier_id"]); op.create_index("ix_supplier_connector_onboarding_connector_id","supplier_connector_onboarding",["connector_id"]); op.create_index("ix_supplier_connector_onboarding_status","supplier_connector_onboarding",["status"]); op.create_index("ix_onboarding_status","supplier_connector_onboarding",["status","updated_at"])
    op.create_table("connector_credential",
        sa.Column("credential_id",sa.String(64),primary_key=True),sa.Column("onboarding_id",sa.String(64),nullable=False),sa.Column("connector_id",sa.String(64),nullable=False),sa.Column("environment",sa.String(24),nullable=False),sa.Column("secret_ciphertext",sa.Text(),nullable=False),sa.Column("secret_fingerprint",sa.String(64),nullable=False),sa.Column("field_names",sa.JSON(),nullable=False),sa.Column("vault_provider",sa.String(32),nullable=False),sa.Column("key_version",sa.String(32),nullable=False),sa.Column("status",sa.String(24),nullable=False),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False),sa.Column("rotated_at",sa.DateTime(timezone=True)),sa.Column("revoked_at",sa.DateTime(timezone=True)))
    op.create_index("ix_connector_credential_onboarding_id","connector_credential",["onboarding_id"]); op.create_index("ix_connector_credential_connector_id","connector_credential",["connector_id"]); op.create_index("ix_connector_credential_status","connector_credential",["status"])
    op.create_table("property_mapping_candidate",
        sa.Column("mapping_id",sa.String(64),primary_key=True),sa.Column("onboarding_id",sa.String(64),nullable=False),sa.Column("connector_id",sa.String(64),nullable=False),sa.Column("external_hotel_id",sa.String(160),nullable=False),sa.Column("proposed_hotel_id",sa.String(64)),sa.Column("external_name",sa.String(240)),sa.Column("external_address",sa.Text()),sa.Column("confidence_bps",sa.Integer(),nullable=False),sa.Column("match_method",sa.String(64),nullable=False),sa.Column("status",sa.String(24),nullable=False),sa.Column("reviewed_by",sa.String(64)),sa.Column("review_note",sa.Text()),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False),sa.Column("reviewed_at",sa.DateTime(timezone=True)),sa.UniqueConstraint("onboarding_id","external_hotel_id",name="uq_onboarding_external_hotel"))
    op.create_index("ix_property_mapping_candidate_onboarding_id","property_mapping_candidate",["onboarding_id"]); op.create_index("ix_property_mapping_candidate_connector_id","property_mapping_candidate",["connector_id"]); op.create_index("ix_property_mapping_candidate_proposed_hotel_id","property_mapping_candidate",["proposed_hotel_id"]); op.create_index("ix_property_mapping_candidate_status","property_mapping_candidate",["status"]); op.create_index("ix_property_mapping_review","property_mapping_candidate",["onboarding_id","status"])
    op.create_table("connector_activation_audit",
        sa.Column("audit_id",sa.Integer(),primary_key=True,autoincrement=True),sa.Column("onboarding_id",sa.String(64),nullable=False),sa.Column("from_status",sa.String(40),nullable=False),sa.Column("to_status",sa.String(40),nullable=False),sa.Column("reason",sa.String(160),nullable=False),sa.Column("actor_id",sa.String(64),nullable=False),sa.Column("detail",sa.JSON(),nullable=False),sa.Column("occurred_at",sa.DateTime(timezone=True),nullable=False))
    op.create_index("ix_connector_activation_audit_onboarding_id","connector_activation_audit",["onboarding_id"])

def downgrade():
    op.drop_table("connector_activation_audit"); op.drop_table("property_mapping_candidate"); op.drop_table("connector_credential"); op.drop_table("supplier_connector_onboarding")
