"""Sprint 3F journey intelligence and disruption orchestration
Revision ID: 0027_sprint3f
Revises: 0026_sprint3e
"""
from alembic import op
import sqlalchemy as sa
revision="0027_sprint3f"
down_revision="0026_sprint3e"
branch_labels=None
depends_on=None

def upgrade():
    op.create_table('journey_disruption_signal',
        sa.Column('signal_id',sa.String(64),primary_key=True),sa.Column('journey_id',sa.String(64),nullable=False),sa.Column('account_id',sa.String(64),nullable=False),
        sa.Column('source_item_id',sa.String(64),nullable=False),sa.Column('source_vertical',sa.String(24),nullable=False),sa.Column('source_order_id',sa.String(64),nullable=False),
        sa.Column('event_type',sa.String(64),nullable=False),sa.Column('severity',sa.String(16),nullable=False),sa.Column('event_at',sa.String(40),nullable=False),
        sa.Column('facts_json',sa.JSON,nullable=False),sa.Column('status',sa.String(24),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False))
    for c in ['journey_id','account_id','source_item_id','source_vertical','source_order_id','event_type','severity','status']:
        op.create_index('ix_jds_'+c,'journey_disruption_signal',[c])
    op.create_table('journey_impact_runtime',
        sa.Column('impact_id',sa.String(64),primary_key=True),sa.Column('signal_id',sa.String(64),nullable=False),sa.Column('journey_id',sa.String(64),nullable=False),sa.Column('account_id',sa.String(64),nullable=False),
        sa.Column('affected_item_id',sa.String(64),nullable=False),sa.Column('affected_vertical',sa.String(24),nullable=False),sa.Column('affected_order_id',sa.String(64),nullable=False),
        sa.Column('impact_type',sa.String(64),nullable=False),sa.Column('severity',sa.String(16),nullable=False),sa.Column('reason',sa.Text,nullable=False),sa.Column('confidence_milli',sa.Integer,nullable=False),
        sa.Column('status',sa.String(24),nullable=False),sa.Column('recommended_action_json',sa.JSON,nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False))
    for c in ['signal_id','journey_id','account_id','affected_item_id','affected_vertical','affected_order_id','impact_type','severity','status']:
        op.create_index('ix_jim_'+c,'journey_impact_runtime',[c])
    op.create_table('journey_advice_runtime',
        sa.Column('advice_id',sa.String(64),primary_key=True),sa.Column('journey_id',sa.String(64),nullable=False),sa.Column('account_id',sa.String(64),nullable=False),sa.Column('signal_id',sa.String(64),nullable=False),
        sa.Column('status',sa.String(24),nullable=False),sa.Column('summary',sa.Text,nullable=False),sa.Column('recommended_actions_json',sa.JSON,nullable=False),sa.Column('execution_boundary',sa.String(96),nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.Column('acknowledged_at',sa.DateTime(timezone=True)))
    for c in ['journey_id','account_id','signal_id','status']:
        op.create_index('ix_jad_'+c,'journey_advice_runtime',[c])

def downgrade():
    op.drop_table('journey_advice_runtime');op.drop_table('journey_impact_runtime');op.drop_table('journey_disruption_signal')
