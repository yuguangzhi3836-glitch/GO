"""Sprint 3L recovery incident intelligence and reliability memory
Revision ID: 0033_sprint3l
Revises: 0032_sprint3k
"""
from alembic import op
import sqlalchemy as sa
revision='0033_sprint3l';down_revision='0032_sprint3k';branch_labels=None;depends_on=None

def upgrade():
    op.create_table('journey_recovery_reliability_profile',
      sa.Column('reliability_profile_id',sa.String(96),primary_key=True),sa.Column('vertical',sa.String(32),nullable=False),sa.Column('adapter_key',sa.String(96),nullable=False),sa.Column('sample_count',sa.Integer(),nullable=False),sa.Column('async_count',sa.Integer(),nullable=False),sa.Column('unknown_count',sa.Integer(),nullable=False),sa.Column('confirmed_count',sa.Integer(),nullable=False),sa.Column('failed_count',sa.Integer(),nullable=False),sa.Column('manual_review_count',sa.Integer(),nullable=False),sa.Column('avg_confirmation_seconds',sa.Float()),sa.Column('avg_webhook_lag_seconds',sa.Float()),sa.Column('avg_poll_attempts',sa.Float()),sa.Column('timeout_rate',sa.Float(),nullable=False),sa.Column('manual_review_rate',sa.Float(),nullable=False),sa.Column('confirmation_rate',sa.Float(),nullable=False),sa.Column('confidence',sa.Float(),nullable=False),sa.Column('risk_band',sa.String(16),nullable=False),sa.Column('recommended_initial_poll_seconds',sa.Integer(),nullable=False),sa.Column('recommended_max_poll_seconds',sa.Integer(),nullable=False),sa.Column('recommended_max_attempts',sa.Integer(),nullable=False),sa.Column('recommended_ack_multiplier',sa.Float(),nullable=False),sa.Column('recommended_resolution_multiplier',sa.Float(),nullable=False),sa.Column('metrics_json',sa.JSON(),nullable=False),sa.Column('calculated_at',sa.DateTime(timezone=True),nullable=False))
    for c in ('vertical','adapter_key','risk_band','calculated_at'):op.create_index(f'ix_jrrp_{c}','journey_recovery_reliability_profile',[c])
    op.create_table('journey_recovery_reliability_decision',
      sa.Column('reliability_decision_id',sa.String(64),primary_key=True),sa.Column('execution_item_id',sa.String(64),nullable=False),sa.Column('supplier_operation_id',sa.String(64)),sa.Column('reliability_profile_id',sa.String(96)),sa.Column('decision_kind',sa.String(48),nullable=False),sa.Column('risk_band',sa.String(16),nullable=False),sa.Column('parameters_json',sa.JSON(),nullable=False),sa.Column('explanation_json',sa.JSON(),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False))
    for c in ('execution_item_id','supplier_operation_id','reliability_profile_id','decision_kind','created_at'):op.create_index(f'ix_jrrd_{c}','journey_recovery_reliability_decision',[c])

def downgrade():
    op.drop_table('journey_recovery_reliability_decision');op.drop_table('journey_recovery_reliability_profile')
