"""Sprint 3H one-click recovery orchestrator and atomic user intent
Revision ID: 0029_sprint3h
Revises: 0028_sprint3g
"""
from alembic import op
import sqlalchemy as sa
revision='0029_sprint3h';down_revision='0028_sprint3g';branch_labels=None;depends_on=None

def upgrade():
    op.create_table('journey_recovery_execution',
      sa.Column('execution_id',sa.String(64),primary_key=True),sa.Column('journey_id',sa.String(64),nullable=False),sa.Column('account_id',sa.String(64),nullable=False),sa.Column('plan_id',sa.String(64),nullable=False),sa.Column('intent_id',sa.String(64),nullable=False),sa.Column('intent_hash',sa.String(64),nullable=False),sa.Column('status',sa.String(32),nullable=False),sa.Column('currency',sa.String(8),nullable=False),sa.Column('quoted_delta_minor',sa.Integer(),nullable=False),sa.Column('authorized_delta_minor',sa.Integer(),nullable=False),sa.Column('completed_items',sa.Integer(),nullable=False),sa.Column('action_required_items',sa.Integer(),nullable=False),sa.Column('failed_items',sa.Integer(),nullable=False),sa.Column('intent_json',sa.JSON(),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.Column('confirmed_at',sa.DateTime(timezone=True)),sa.Column('completed_at',sa.DateTime(timezone=True)),sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False))
    for c in ('journey_id','account_id','plan_id','intent_id','status'):op.create_index(f'ix_jre_{c}','journey_recovery_execution',[c])
    op.create_index('uq_jre_plan_intent_hash','journey_recovery_execution',['plan_id','intent_hash'],unique=True)
    op.create_table('journey_recovery_execution_item',
      sa.Column('execution_item_id',sa.String(64),primary_key=True),sa.Column('execution_id',sa.String(64),nullable=False),sa.Column('option_id',sa.String(64),nullable=False),sa.Column('journey_id',sa.String(64),nullable=False),sa.Column('account_id',sa.String(64),nullable=False),sa.Column('vertical',sa.String(24),nullable=False),sa.Column('order_id',sa.String(64),nullable=False),sa.Column('rule_version',sa.String(64),nullable=False),sa.Column('quote_id',sa.String(64),nullable=False),sa.Column('quoted_delta_minor',sa.Integer(),nullable=False),sa.Column('revalidated_delta_minor',sa.Integer(),nullable=False),sa.Column('currency',sa.String(8),nullable=False),sa.Column('payment_action_json',sa.JSON(),nullable=False),sa.Column('supplier_command_id',sa.String(96)),sa.Column('supplier_confirmation_id',sa.String(96)),sa.Column('status',sa.String(40),nullable=False),sa.Column('failure_reason',sa.String(96)),sa.Column('reconciliation_state',sa.String(40),nullable=False),sa.Column('attempt_count',sa.Integer(),nullable=False),sa.Column('facts_json',sa.JSON(),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False))
    for c in ('execution_id','option_id','journey_id','account_id','vertical','order_id','status','reconciliation_state'):op.create_index(f'ix_jrei_{c}','journey_recovery_execution_item',[c])
    op.create_index('uq_jrei_execution_option','journey_recovery_execution_item',['execution_id','option_id'],unique=True)
    op.create_table('journey_recovery_execution_event',
      sa.Column('event_id',sa.String(64),primary_key=True),sa.Column('execution_id',sa.String(64),nullable=False),sa.Column('execution_item_id',sa.String(64)),sa.Column('event_type',sa.String(64),nullable=False),sa.Column('status',sa.String(32),nullable=False),sa.Column('request_id',sa.String(96)),sa.Column('evidence_json',sa.JSON(),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False))
    for c in ('execution_id','execution_item_id','event_type','status','created_at'):op.create_index(f'ix_jree_{c}','journey_recovery_execution_event',[c])

def downgrade():
    op.drop_table('journey_recovery_execution_event');op.drop_table('journey_recovery_execution_item');op.drop_table('journey_recovery_execution')
