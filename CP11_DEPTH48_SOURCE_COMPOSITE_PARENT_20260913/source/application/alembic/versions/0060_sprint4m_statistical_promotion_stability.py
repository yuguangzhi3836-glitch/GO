"""Sprint 4M statistical significance, promotion stability and automated rollback governance.
Revision ID: 0060_sprint4m
Revises: 0059_sprint4l
"""
from alembic import op
import sqlalchemy as sa
revision='0060_sprint4m';down_revision='0059_sprint4l';branch_labels=None;depends_on=None

def imm(table):
    d=op.get_bind().dialect.name
    if d=='sqlite':
        op.execute(f"CREATE TRIGGER {table}_deny_update BEFORE UPDATE ON {table} BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_STATISTICAL_MODEL_GOVERNANCE_EVIDENCE'); END;")
        op.execute(f"CREATE TRIGGER {table}_deny_delete BEFORE DELETE ON {table} BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_STATISTICAL_MODEL_GOVERNANCE_EVIDENCE'); END;")
    elif d=='postgresql':
        op.execute("""CREATE OR REPLACE FUNCTION deny_statistical_model_governance_mutation() RETURNS trigger AS $$ BEGIN RAISE EXCEPTION 'IMMUTABLE_STATISTICAL_MODEL_GOVERNANCE_EVIDENCE'; END; $$ LANGUAGE plpgsql;""")
        op.execute(f"CREATE TRIGGER {table}_deny_update BEFORE UPDATE ON {table} FOR EACH ROW EXECUTE FUNCTION deny_statistical_model_governance_mutation();")
        op.execute(f"CREATE TRIGGER {table}_deny_delete BEFORE DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION deny_statistical_model_governance_mutation();")

def upgrade():
    op.create_table('journey_recovery_forecast_promotion_policy',sa.Column('forecast_promotion_policy_id',sa.String(64),primary_key=True),sa.Column('environment',sa.String(16),nullable=False),sa.Column('version_no',sa.Integer(),nullable=False),sa.Column('minimum_sample_count',sa.Integer(),nullable=False),sa.Column('significance_alpha',sa.Float(),nullable=False),sa.Column('minimum_effect_size_pct',sa.Float(),nullable=False),sa.Column('stability_evaluations_required',sa.Integer(),nullable=False),sa.Column('required_segments_json',sa.JSON(),nullable=False),sa.Column('probation_seconds',sa.Integer(),nullable=False),sa.Column('max_mae_regression_pct',sa.Float(),nullable=False),sa.Column('max_brier_regression_pct',sa.Float(),nullable=False),sa.Column('max_safety_regression_pct',sa.Float(),nullable=False),sa.Column('requested_by',sa.String(64),nullable=False),sa.Column('approver_one',sa.String(64)),sa.Column('approver_two',sa.String(64)),sa.Column('state',sa.String(24),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.Column('supplier_fact_unchanged',sa.Boolean(),nullable=False,server_default=sa.true()))
    op.create_table('journey_recovery_forecast_statistical_assessment',sa.Column('forecast_statistical_assessment_id',sa.String(64),primary_key=True),sa.Column('environment',sa.String(16),nullable=False),sa.Column('policy_id',sa.String(64),nullable=False),sa.Column('champion_model_version_id',sa.String(64),nullable=False),sa.Column('challenger_model_version_id',sa.String(64),nullable=False),sa.Column('horizon_hours',sa.Integer(),nullable=False),sa.Column('segment_key',sa.String(128),nullable=False),sa.Column('sample_count',sa.Integer(),nullable=False),sa.Column('effect_size_pct',sa.Float(),nullable=False),sa.Column('z_score',sa.Float(),nullable=False),sa.Column('p_value',sa.Float(),nullable=False),sa.Column('significance_state',sa.String(24),nullable=False),sa.Column('reason_codes_json',sa.JSON(),nullable=False),sa.Column('evaluated_at',sa.DateTime(timezone=True),nullable=False),sa.Column('supplier_fact_unchanged',sa.Boolean(),nullable=False,server_default=sa.true()))
    op.create_table('journey_recovery_forecast_promotion_probation',sa.Column('forecast_promotion_probation_id',sa.String(64),primary_key=True),sa.Column('environment',sa.String(16),nullable=False),sa.Column('policy_id',sa.String(64),nullable=False),sa.Column('promotion_decision_id',sa.String(64),nullable=False),sa.Column('previous_champion_model_version_id',sa.String(64),nullable=False),sa.Column('promoted_model_version_id',sa.String(64),nullable=False),sa.Column('started_at',sa.DateTime(timezone=True),nullable=False),sa.Column('probation_until',sa.DateTime(timezone=True),nullable=False),sa.Column('state',sa.String(24),nullable=False),sa.Column('latest_evaluation_json',sa.JSON(),nullable=False),sa.Column('rollback_reason_codes_json',sa.JSON(),nullable=False),sa.Column('completed_at',sa.DateTime(timezone=True)),sa.Column('supplier_fact_unchanged',sa.Boolean(),nullable=False,server_default=sa.true()))
    op.create_table('journey_recovery_forecast_model_rollback_event',sa.Column('forecast_model_rollback_event_id',sa.String(64),primary_key=True),sa.Column('environment',sa.String(16),nullable=False),sa.Column('probation_id',sa.String(64),nullable=False),sa.Column('from_model_version_id',sa.String(64),nullable=False),sa.Column('to_model_version_id',sa.String(64),nullable=False),sa.Column('reason_codes_json',sa.JSON(),nullable=False),sa.Column('evidence_json',sa.JSON(),nullable=False),sa.Column('rolled_back_at',sa.DateTime(timezone=True),nullable=False),sa.Column('supplier_fact_unchanged',sa.Boolean(),nullable=False,server_default=sa.true()))
    for t in ['journey_recovery_forecast_statistical_assessment','journey_recovery_forecast_promotion_probation','journey_recovery_forecast_model_rollback_event']: imm(t)

def downgrade():
    for t in ['journey_recovery_forecast_model_rollback_event','journey_recovery_forecast_promotion_probation','journey_recovery_forecast_statistical_assessment','journey_recovery_forecast_promotion_policy']: op.drop_table(t)
