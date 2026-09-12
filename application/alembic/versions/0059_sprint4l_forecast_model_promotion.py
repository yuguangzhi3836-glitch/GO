"""Sprint 4L forecast champion/challenger, backtesting and promotion governance.
Revision ID: 0059_sprint4l
Revises: 0058_sprint4k
"""
from alembic import op
import sqlalchemy as sa
revision='0059_sprint4l';down_revision='0058_sprint4k';branch_labels=None;depends_on=None

def imm(table):
    d=op.get_bind().dialect.name
    if d=='sqlite':
        op.execute(f"CREATE TRIGGER {table}_deny_update BEFORE UPDATE ON {table} BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_FORECAST_MODEL_GOVERNANCE_EVIDENCE'); END;")
        op.execute(f"CREATE TRIGGER {table}_deny_delete BEFORE DELETE ON {table} BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_FORECAST_MODEL_GOVERNANCE_EVIDENCE'); END;")
    elif d=='postgresql':
        op.execute("""CREATE OR REPLACE FUNCTION deny_forecast_model_governance_evidence_mutation() RETURNS trigger AS $$ BEGIN RAISE EXCEPTION 'IMMUTABLE_FORECAST_MODEL_GOVERNANCE_EVIDENCE'; END; $$ LANGUAGE plpgsql;""")
        op.execute(f"CREATE TRIGGER {table}_deny_update BEFORE UPDATE ON {table} FOR EACH ROW EXECUTE FUNCTION deny_forecast_model_governance_evidence_mutation();")
        op.execute(f"CREATE TRIGGER {table}_deny_delete BEFORE DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION deny_forecast_model_governance_evidence_mutation();")
def upgrade():
    op.create_table('journey_recovery_forecast_model_role',sa.Column('forecast_model_role_id',sa.String(64),primary_key=True),sa.Column('environment',sa.String(16),nullable=False),sa.Column('model_version_id',sa.String(64),nullable=False),sa.Column('role',sa.String(24),nullable=False),sa.Column('state',sa.String(24),nullable=False),sa.Column('assigned_at',sa.DateTime(timezone=True),nullable=False),sa.Column('supplier_fact_unchanged',sa.Boolean(),nullable=False,server_default=sa.true()))
    op.create_table('journey_recovery_forecast_backtest_run',sa.Column('forecast_backtest_run_id',sa.String(64),primary_key=True),sa.Column('environment',sa.String(16),nullable=False),sa.Column('champion_model_version_id',sa.String(64),nullable=False),sa.Column('challenger_model_version_id',sa.String(64),nullable=False),sa.Column('window_key',sa.String(64),nullable=False),sa.Column('horizons_json',sa.JSON(),nullable=False),sa.Column('segments_json',sa.JSON(),nullable=False),sa.Column('state',sa.String(24),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.Column('supplier_fact_unchanged',sa.Boolean(),nullable=False,server_default=sa.true()))
    op.create_table('journey_recovery_forecast_backtest_metric',sa.Column('forecast_backtest_metric_id',sa.String(64),primary_key=True),sa.Column('forecast_backtest_run_id',sa.String(64),nullable=False),sa.Column('model_version_id',sa.String(64),nullable=False),sa.Column('horizon_hours',sa.Integer(),nullable=False),sa.Column('segment_key',sa.String(128),nullable=False),sa.Column('sample_count',sa.Integer(),nullable=False),sa.Column('mae_points',sa.Float(),nullable=False),sa.Column('brier_score',sa.Float(),nullable=False),sa.Column('false_positive_rate',sa.Float(),nullable=False),sa.Column('false_negative_rate',sa.Float(),nullable=False),sa.Column('capacity_drift_pct',sa.Float(),nullable=False),sa.Column('supplier_fact_unchanged',sa.Boolean(),nullable=False,server_default=sa.true()))
    op.create_table('journey_recovery_forecast_shadow_evaluation',sa.Column('forecast_shadow_evaluation_id',sa.String(64),primary_key=True),sa.Column('environment',sa.String(16),nullable=False),sa.Column('challenger_model_version_id',sa.String(64),nullable=False),sa.Column('horizon_hours',sa.Integer(),nullable=False),sa.Column('segment_key',sa.String(128),nullable=False),sa.Column('sample_count',sa.Integer(),nullable=False),sa.Column('improvement_pct',sa.Float(),nullable=False),sa.Column('safety_delta_pct',sa.Float(),nullable=False),sa.Column('evaluation_state',sa.String(24),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.Column('supplier_fact_unchanged',sa.Boolean(),nullable=False,server_default=sa.true()))
    op.create_table('journey_recovery_forecast_promotion_decision',sa.Column('forecast_promotion_decision_id',sa.String(64),primary_key=True),sa.Column('environment',sa.String(16),nullable=False),sa.Column('champion_model_version_id',sa.String(64),nullable=False),sa.Column('challenger_model_version_id',sa.String(64),nullable=False),sa.Column('decision',sa.String(24),nullable=False),sa.Column('reason_codes_json',sa.JSON(),nullable=False),sa.Column('evidence_json',sa.JSON(),nullable=False),sa.Column('decided_at',sa.DateTime(timezone=True),nullable=False),sa.Column('supplier_fact_unchanged',sa.Boolean(),nullable=False,server_default=sa.true()))
    for t in ['journey_recovery_forecast_backtest_metric','journey_recovery_forecast_shadow_evaluation','journey_recovery_forecast_promotion_decision']: imm(t)
def downgrade():
    for t in ['journey_recovery_forecast_promotion_decision','journey_recovery_forecast_shadow_evaluation','journey_recovery_forecast_backtest_metric','journey_recovery_forecast_backtest_run','journey_recovery_forecast_model_role']: op.drop_table(t)
