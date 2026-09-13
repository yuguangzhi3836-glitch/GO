"""Sprint 4F waiver exposure budget, exception debt and remediation SLA.
Revision ID: 0053_sprint4f
Revises: 0052_sprint4e
"""
from alembic import op
import sqlalchemy as sa
revision='0053_sprint4f';down_revision='0052_sprint4e';branch_labels=None;depends_on=None

def _immutable(table):
    d=op.get_bind().dialect.name
    if d=='sqlite':
        op.execute(f"CREATE TRIGGER {table}_deny_update BEFORE UPDATE ON {table} BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_WAIVER_EXPOSURE_EVIDENCE'); END;")
        op.execute(f"CREATE TRIGGER {table}_deny_delete BEFORE DELETE ON {table} BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_WAIVER_EXPOSURE_EVIDENCE'); END;")
    elif d=='postgresql':
        op.execute("""CREATE OR REPLACE FUNCTION deny_waiver_exposure_evidence_mutation() RETURNS trigger AS $$ BEGIN RAISE EXCEPTION 'IMMUTABLE_WAIVER_EXPOSURE_EVIDENCE'; END; $$ LANGUAGE plpgsql;""")
        op.execute(f"CREATE TRIGGER {table}_deny_update BEFORE UPDATE ON {table} FOR EACH ROW EXECUTE FUNCTION deny_waiver_exposure_evidence_mutation();")
        op.execute(f"CREATE TRIGGER {table}_deny_delete BEFORE DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION deny_waiver_exposure_evidence_mutation();")

def upgrade():
    op.create_table('journey_recovery_waiver_exposure_policy',
        sa.Column('waiver_exposure_policy_id',sa.String(64),primary_key=True),sa.Column('policy_key',sa.String(128),nullable=False),sa.Column('version_no',sa.Integer(),nullable=False),sa.Column('environment',sa.String(16),nullable=False),sa.Column('rolling_window_hours',sa.Integer(),nullable=False),sa.Column('max_waiver_count',sa.Integer(),nullable=False),sa.Column('max_consecutive_waiver_releases',sa.Integer(),nullable=False),sa.Column('max_exposure_seconds',sa.Integer(),nullable=False),sa.Column('max_exception_debt_points',sa.Float(),nullable=False),sa.Column('remediation_sla_seconds',sa.Integer(),nullable=False),sa.Column('escalation_after_seconds',sa.Integer(),nullable=False),sa.Column('state',sa.String(24),nullable=False),sa.Column('created_by',sa.String(64),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.Column('supplier_fact_unchanged',sa.Boolean(),nullable=False,server_default=sa.true()))
    op.create_table('journey_recovery_exception_debt',
        sa.Column('exception_debt_id',sa.String(64),primary_key=True),sa.Column('environment',sa.String(16),nullable=False),sa.Column('waiver_exposure_policy_id',sa.String(64),nullable=False),sa.Column('rolling_window_start',sa.DateTime(timezone=True),nullable=False),sa.Column('rolling_waiver_count',sa.Integer(),nullable=False),sa.Column('consecutive_waiver_releases',sa.Integer(),nullable=False),sa.Column('exposure_seconds',sa.Integer(),nullable=False),sa.Column('open_remediation_count',sa.Integer(),nullable=False),sa.Column('overdue_remediation_count',sa.Integer(),nullable=False),sa.Column('debt_points',sa.Float(),nullable=False),sa.Column('debt_state',sa.String(24),nullable=False),sa.Column('reason_codes_json',sa.JSON(),nullable=False),sa.Column('evaluated_by',sa.String(64),nullable=False),sa.Column('evaluated_at',sa.DateTime(timezone=True),nullable=False),sa.Column('supplier_fact_unchanged',sa.Boolean(),nullable=False,server_default=sa.true()))
    op.create_table('journey_recovery_waiver_remediation',
        sa.Column('waiver_remediation_id',sa.String(64),primary_key=True),sa.Column('environment',sa.String(16),nullable=False),sa.Column('waiver_id',sa.String(64),nullable=False),sa.Column('remediation_owner',sa.String(64),nullable=False),sa.Column('remediation_summary',sa.String(1024),nullable=False),sa.Column('opened_at',sa.DateTime(timezone=True),nullable=False),sa.Column('due_at',sa.DateTime(timezone=True),nullable=False),sa.Column('acknowledged_at',sa.DateTime(timezone=True)),sa.Column('resolved_at',sa.DateTime(timezone=True)),sa.Column('resolution_evidence_reference',sa.String(256)),sa.Column('escalation_level',sa.Integer(),nullable=False,server_default='0'),sa.Column('last_escalated_at',sa.DateTime(timezone=True)),sa.Column('state',sa.String(24),nullable=False),sa.Column('supplier_fact_unchanged',sa.Boolean(),nullable=False,server_default=sa.true()))
    op.create_table('journey_recovery_waiver_exposure_event',
        sa.Column('waiver_exposure_event_id',sa.String(64),primary_key=True),sa.Column('environment',sa.String(16),nullable=False),sa.Column('waiver_id',sa.String(64)),sa.Column('remediation_id',sa.String(64)),sa.Column('event_type',sa.String(64),nullable=False),sa.Column('evidence_json',sa.JSON(),nullable=False),sa.Column('actor',sa.String(64),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.Column('supplier_fact_unchanged',sa.Boolean(),nullable=False,server_default=sa.true()))
    for t in ['journey_recovery_exception_debt','journey_recovery_waiver_exposure_event']:_immutable(t)

def downgrade():
    for t in ['journey_recovery_waiver_exposure_event','journey_recovery_waiver_remediation','journey_recovery_exception_debt','journey_recovery_waiver_exposure_policy']:op.drop_table(t)
