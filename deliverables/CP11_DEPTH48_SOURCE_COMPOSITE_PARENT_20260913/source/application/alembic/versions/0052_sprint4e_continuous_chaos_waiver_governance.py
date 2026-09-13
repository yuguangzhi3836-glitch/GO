"""Sprint 4E continuous chaos scheduler, readiness trend and waiver governance.
Revision ID: 0052_sprint4e
Revises: 0051_sprint4d
"""
from alembic import op
import sqlalchemy as sa
revision='0052_sprint4e';down_revision='0051_sprint4d';branch_labels=None;depends_on=None

def _immutable(table):
    d=op.get_bind().dialect.name
    if d=='sqlite':
        op.execute(f"CREATE TRIGGER {table}_deny_update BEFORE UPDATE ON {table} BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_CONTINUOUS_READINESS_EVIDENCE'); END;")
        op.execute(f"CREATE TRIGGER {table}_deny_delete BEFORE DELETE ON {table} BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_CONTINUOUS_READINESS_EVIDENCE'); END;")
    elif d=='postgresql':
        op.execute("""CREATE OR REPLACE FUNCTION deny_continuous_readiness_evidence_mutation() RETURNS trigger AS $$ BEGIN RAISE EXCEPTION 'IMMUTABLE_CONTINUOUS_READINESS_EVIDENCE'; END; $$ LANGUAGE plpgsql;""")
        op.execute(f"CREATE TRIGGER {table}_deny_update BEFORE UPDATE ON {table} FOR EACH ROW EXECUTE FUNCTION deny_continuous_readiness_evidence_mutation();")
        op.execute(f"CREATE TRIGGER {table}_deny_delete BEFORE DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION deny_continuous_readiness_evidence_mutation();")

def upgrade():
    op.create_table('journey_recovery_chaos_schedule',sa.Column('chaos_schedule_id',sa.String(64),primary_key=True),sa.Column('environment',sa.String(16),nullable=False),sa.Column('chaos_policy_id',sa.String(64),nullable=False),sa.Column('schedule_key',sa.String(128),nullable=False),sa.Column('cadence_seconds',sa.Integer(),nullable=False),sa.Column('scenarios_json',sa.JSON(),nullable=False),sa.Column('state',sa.String(24),nullable=False),sa.Column('last_run_at',sa.DateTime(timezone=True)),sa.Column('next_run_at',sa.DateTime(timezone=True),nullable=False),sa.Column('created_by',sa.String(64),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.Column('supplier_fact_unchanged',sa.Boolean(),nullable=False,server_default=sa.true()))
    op.create_table('journey_recovery_readiness_trend',sa.Column('readiness_trend_id',sa.String(64),primary_key=True),sa.Column('environment',sa.String(16),nullable=False),sa.Column('chaos_policy_id',sa.String(64),nullable=False),sa.Column('latest_assessment_id',sa.String(64),nullable=False),sa.Column('previous_assessment_id',sa.String(64)),sa.Column('score_delta',sa.Float(),nullable=False),sa.Column('rto_delta_seconds',sa.Integer(),nullable=False),sa.Column('rpo_delta_seconds',sa.Integer(),nullable=False),sa.Column('evidence_age_seconds',sa.Integer(),nullable=False),sa.Column('trend_state',sa.String(24),nullable=False),sa.Column('reason_codes_json',sa.JSON(),nullable=False),sa.Column('evaluated_by',sa.String(64),nullable=False),sa.Column('evaluated_at',sa.DateTime(timezone=True),nullable=False),sa.Column('supplier_fact_unchanged',sa.Boolean(),nullable=False,server_default=sa.true()))
    op.create_table('journey_recovery_production_release_waiver',sa.Column('production_release_waiver_id',sa.String(64),primary_key=True),sa.Column('environment',sa.String(16),nullable=False),sa.Column('reason',sa.String(512),nullable=False),sa.Column('risk_summary',sa.String(1024),nullable=False),sa.Column('evidence_reference',sa.String(256),nullable=False),sa.Column('risk_acceptor',sa.String(64),nullable=False),sa.Column('requested_by',sa.String(64),nullable=False),sa.Column('requested_at',sa.DateTime(timezone=True),nullable=False),sa.Column('starts_at',sa.DateTime(timezone=True),nullable=False),sa.Column('expires_at',sa.DateTime(timezone=True),nullable=False),sa.Column('approver_one',sa.String(64)),sa.Column('approver_one_at',sa.DateTime(timezone=True)),sa.Column('approver_two',sa.String(64)),sa.Column('approver_two_at',sa.DateTime(timezone=True)),sa.Column('state',sa.String(24),nullable=False),sa.Column('supplier_fact_unchanged',sa.Boolean(),nullable=False,server_default=sa.true()))
    op.create_table('journey_recovery_release_gate_history',sa.Column('release_gate_history_id',sa.String(64),primary_key=True),sa.Column('environment',sa.String(16),nullable=False),sa.Column('release_manifest_id',sa.String(64)),sa.Column('gate_id',sa.String(64)),sa.Column('waiver_id',sa.String(64)),sa.Column('decision',sa.String(24),nullable=False),sa.Column('decision_reason',sa.String(128),nullable=False),sa.Column('evidence_json',sa.JSON(),nullable=False),sa.Column('actor',sa.String(64),nullable=False),sa.Column('evaluated_at',sa.DateTime(timezone=True),nullable=False),sa.Column('supplier_fact_unchanged',sa.Boolean(),nullable=False,server_default=sa.true()))
    for t in ['journey_recovery_readiness_trend','journey_recovery_release_gate_history']:_immutable(t)

def downgrade():
    for t in ['journey_recovery_release_gate_history','journey_recovery_production_release_waiver','journey_recovery_readiness_trend','journey_recovery_chaos_schedule']:op.drop_table(t)
