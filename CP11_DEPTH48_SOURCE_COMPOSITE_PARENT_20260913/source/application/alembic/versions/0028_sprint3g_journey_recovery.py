"""Sprint 3G proactive journey recovery and option comparison
Revision ID: 0028_sprint3g
Revises: 0027_sprint3f
"""
from alembic import op
import sqlalchemy as sa
revision='0028_sprint3g';down_revision='0027_sprint3f';branch_labels=None;depends_on=None
def upgrade():
    op.create_table('journey_recovery_plan',
      sa.Column('plan_id',sa.String(64),primary_key=True),sa.Column('journey_id',sa.String(64),nullable=False),sa.Column('account_id',sa.String(64),nullable=False),sa.Column('advice_id',sa.String(64),nullable=False),sa.Column('status',sa.String(24),nullable=False),sa.Column('currency',sa.String(8),nullable=False),sa.Column('summary',sa.Text(),nullable=False),sa.Column('selected_option_ids_json',sa.JSON(),nullable=False),sa.Column('execution_boundary',sa.String(96),nullable=False),sa.Column('expires_at',sa.DateTime(timezone=True),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False))
    for c in ('journey_id','account_id','advice_id','status','expires_at'):op.create_index(f'ix_jrp_{c}','journey_recovery_plan',[c])
    op.create_table('journey_recovery_option',
      sa.Column('option_id',sa.String(64),primary_key=True),sa.Column('plan_id',sa.String(64),nullable=False),sa.Column('journey_id',sa.String(64),nullable=False),sa.Column('account_id',sa.String(64),nullable=False),sa.Column('impact_id',sa.String(64),nullable=False),sa.Column('vertical',sa.String(24),nullable=False),sa.Column('order_id',sa.String(64),nullable=False),sa.Column('option_type',sa.String(48),nullable=False),sa.Column('title',sa.String(255),nullable=False),sa.Column('subtitle',sa.Text(),nullable=False),sa.Column('total_delta_minor',sa.Integer(),nullable=False),sa.Column('currency',sa.String(8),nullable=False),sa.Column('rank_score',sa.Integer(),nullable=False),sa.Column('status',sa.String(24),nullable=False),sa.Column('execution_route',sa.String(96),nullable=False),sa.Column('requires_user_confirmation',sa.Boolean(),nullable=False),sa.Column('quote_facts_json',sa.JSON(),nullable=False),sa.Column('expires_at',sa.DateTime(timezone=True),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False))
    for c in ('plan_id','journey_id','account_id','impact_id','vertical','order_id','option_type','rank_score','status','expires_at'):op.create_index(f'ix_jro_{c}','journey_recovery_option',[c])
def downgrade():
    op.drop_table('journey_recovery_option');op.drop_table('journey_recovery_plan')
