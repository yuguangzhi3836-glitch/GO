"""Sprint 3M adaptive strategy governance
Revision ID: 0034_sprint3m
Revises: 0033_sprint3l
"""
from alembic import op
import sqlalchemy as sa
revision='0034_sprint3m';down_revision='0033_sprint3l';branch_labels=None;depends_on=None

def upgrade():
    op.create_table('journey_recovery_strategy_version',
      sa.Column('strategy_version_id',sa.String(64),primary_key=True),sa.Column('name',sa.String(128),nullable=False),sa.Column('state',sa.String(24),nullable=False),sa.Column('min_sample_count',sa.Integer(),nullable=False),sa.Column('min_confidence',sa.Float(),nullable=False),sa.Column('confidence_level',sa.Float(),nullable=False),sa.Column('rollout_percent',sa.Integer(),nullable=False),sa.Column('parameter_bounds_json',sa.JSON(),nullable=False),sa.Column('rollback_thresholds_json',sa.JSON(),nullable=False),sa.Column('requires_approval',sa.Boolean(),nullable=False),sa.Column('approved_by',sa.String(64)),sa.Column('approved_at',sa.DateTime(timezone=True)),sa.Column('activated_at',sa.DateTime(timezone=True)),sa.Column('rolled_back_at',sa.DateTime(timezone=True)),sa.Column('rollback_reason',sa.String(255)),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False))
    for c in ('state','approved_by'):op.create_index(f'ix_jrsv_{c}','journey_recovery_strategy_version',[c])
    op.create_table('journey_recovery_strategy_evaluation',
      sa.Column('strategy_evaluation_id',sa.String(64),primary_key=True),sa.Column('strategy_version_id',sa.String(64),nullable=False),sa.Column('reliability_profile_id',sa.String(96)),sa.Column('execution_item_id',sa.String(64)),sa.Column('mode',sa.String(24),nullable=False),sa.Column('eligible',sa.Boolean(),nullable=False),sa.Column('cohort_bucket',sa.Integer()),sa.Column('confidence_intervals_json',sa.JSON(),nullable=False),sa.Column('proposed_parameters_json',sa.JSON(),nullable=False),sa.Column('applied_parameters_json',sa.JSON(),nullable=False),sa.Column('clamp_events_json',sa.JSON(),nullable=False),sa.Column('reason_codes_json',sa.JSON(),nullable=False),sa.Column('supplier_fact_unchanged',sa.Boolean(),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False))
    for c in ('strategy_version_id','reliability_profile_id','execution_item_id','mode','created_at'):op.create_index(f'ix_jrse_{c}','journey_recovery_strategy_evaluation',[c])

def downgrade():
    op.drop_table('journey_recovery_strategy_evaluation');op.drop_table('journey_recovery_strategy_version')
