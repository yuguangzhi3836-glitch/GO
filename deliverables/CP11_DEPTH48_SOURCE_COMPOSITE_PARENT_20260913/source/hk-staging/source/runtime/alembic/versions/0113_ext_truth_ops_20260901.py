"""External truth operator workflow governance.

Revision ID: 0113_ext_truth_ops_20260901
Revises: 0112_ti_p0_20260829
"""
from alembic import op
import sqlalchemy as sa

revision = "0113_ext_truth_ops_20260901"
down_revision = "0112_ti_p0_20260829"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("connector_runtime_reconciliation", sa.Column("claimed_by", sa.String(64), nullable=True))
    op.add_column("connector_runtime_reconciliation", sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("connector_runtime_reconciliation", sa.Column("evidence_due_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("connector_runtime_reconciliation", sa.Column("resolution_requested_by", sa.String(64), nullable=True))
    op.add_column("connector_runtime_reconciliation", sa.Column("checker_id", sa.String(64), nullable=True))
    op.add_column("connector_runtime_reconciliation", sa.Column("escalation_level", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("connector_runtime_reconciliation", sa.Column("operator_sla_due_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("connector_runtime_reconciliation", sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_connector_runtime_recon_lease", "connector_runtime_reconciliation", ["state", "lease_expires_at"])


def downgrade():
    op.drop_index("ix_connector_runtime_recon_lease", table_name="connector_runtime_reconciliation")
    for col in ("resolved_at","operator_sla_due_at","escalation_level","checker_id","resolution_requested_by","evidence_due_at","lease_expires_at","claimed_by"):
        op.drop_column("connector_runtime_reconciliation", col)
