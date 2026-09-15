"""Sprint 1V observability and incident control.
Revision ID: 0017_sprint1v
Revises: 0016_sprint1u
"""
from alembic import op
import sqlalchemy as sa
revision="0017_sprint1v"; down_revision="0016_sprint1u"; branch_labels=None; depends_on=None

def upgrade():
    op.create_table("incident_control",
      sa.Column("control_id",sa.String(64),primary_key=True),sa.Column("scope",sa.String(64),nullable=False,unique=True),sa.Column("status",sa.String(24),nullable=False,server_default="INACTIVE"),sa.Column("reason",sa.Text()),sa.Column("activated_by",sa.String(64)),sa.Column("activated_at",sa.DateTime(timezone=True)),sa.Column("expires_at",sa.DateTime(timezone=True)),sa.Column("updated_at",sa.DateTime(timezone=True),nullable=False))
    op.create_index("ix_incident_scope","incident_control",["scope"],unique=True); op.create_index("ix_incident_status","incident_control",["status"])
    op.create_table("security_signal",
      sa.Column("signal_id",sa.String(64),primary_key=True),sa.Column("signal_type",sa.String(64),nullable=False),sa.Column("severity",sa.String(16),nullable=False),sa.Column("status",sa.String(24),nullable=False,server_default="OPEN"),sa.Column("request_id",sa.String(128)),sa.Column("actor_id",sa.String(64)),sa.Column("client_ip",sa.String(128)),sa.Column("metadata_json",sa.JSON(),nullable=False),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False))
    op.create_index("ix_security_type","security_signal",["signal_type"]); op.create_index("ix_security_created","security_signal",["created_at"])
    op.create_table("readiness_gate_run",
      sa.Column("run_id",sa.String(64),primary_key=True),sa.Column("environment",sa.String(32),nullable=False),sa.Column("status",sa.String(24),nullable=False),sa.Column("checks_json",sa.JSON(),nullable=False),sa.Column("blocker_count",sa.Integer(),nullable=False,server_default="0"),sa.Column("executed_by",sa.String(64)),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False))
    op.create_index("ix_readiness_created","readiness_gate_run",["created_at"])

def downgrade():
    op.drop_table("readiness_gate_run"); op.drop_table("security_signal"); op.drop_table("incident_control")
