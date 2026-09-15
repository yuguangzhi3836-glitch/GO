"""External truth incident evidence and replay hardening.

Revision ID: 0114_ext_truth_incident_hard
Revises: 0113_ext_truth_ops_20260901
"""
from alembic import op
import sqlalchemy as sa

revision = "0114_ext_truth_incident_hard"
down_revision = "0113_ext_truth_ops_20260901"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("connector_runtime_reconciliation", sa.Column("resolution_payload_json", sa.JSON(), nullable=True))
    op.add_column("connector_runtime_reconciliation", sa.Column("resolution_evidence_digest", sa.String(64), nullable=True))
    op.add_column("connector_runtime_reconciliation", sa.Column("checker_evidence_reference", sa.String(512), nullable=True))
    op.add_column("connector_runtime_reconciliation", sa.Column("resolution_result_json", sa.JSON(), nullable=True))
    op.add_column("connector_runtime_reconciliation", sa.Column("resolved_by", sa.String(64), nullable=True))
    op.add_column("connector_runtime_reconciliation", sa.Column("superseded_reason", sa.String(256), nullable=True))


def downgrade():
    for col in ("superseded_reason","resolved_by","resolution_result_json","checker_evidence_reference","resolution_evidence_digest","resolution_payload_json"):
        op.drop_column("connector_runtime_reconciliation", col)
