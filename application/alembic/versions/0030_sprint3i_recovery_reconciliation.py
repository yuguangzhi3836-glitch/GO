"""Sprint 3I durable recovery reconciliation and supplier adapter contract
Revision ID: 0030_sprint3i
Revises: 0029_sprint3h
"""
from alembic import op
import sqlalchemy as sa
revision='0030_sprint3i';down_revision='0029_sprint3h';branch_labels=None;depends_on=None

def upgrade():
    op.create_table('journey_recovery_supplier_operation',
      sa.Column('supplier_operation_id',sa.String(64),primary_key=True),sa.Column('execution_id',sa.String(64),nullable=False),sa.Column('execution_item_id',sa.String(64),nullable=False),sa.Column('vertical',sa.String(24),nullable=False),sa.Column('adapter_key',sa.String(64),nullable=False),sa.Column('supplier_idempotency_key',sa.String(128),nullable=False),sa.Column('command_type',sa.String(48),nullable=False),sa.Column('status',sa.String(40),nullable=False),sa.Column('external_operation_id',sa.String(128)),sa.Column('supplier_confirmation_id',sa.String(128)),sa.Column('request_json',sa.JSON(),nullable=False),sa.Column('response_json',sa.JSON(),nullable=False),sa.Column('last_error',sa.Text()),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.Column('sent_at',sa.DateTime(timezone=True)),sa.Column('last_observed_at',sa.DateTime(timezone=True)),sa.Column('completed_at',sa.DateTime(timezone=True)),sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False))
    for c in ('execution_id','execution_item_id','vertical','adapter_key','status','external_operation_id','supplier_confirmation_id','last_observed_at'):op.create_index(f'ix_jrso_{c}','journey_recovery_supplier_operation',[c],unique=(c=='execution_item_id'))
    op.create_index('uq_jrso_adapter_idempotency','journey_recovery_supplier_operation',['adapter_key','supplier_idempotency_key'],unique=True)
    op.create_table('journey_recovery_reconciliation_job',
      sa.Column('reconciliation_job_id',sa.String(64),primary_key=True),sa.Column('supplier_operation_id',sa.String(64),nullable=False),sa.Column('execution_id',sa.String(64),nullable=False),sa.Column('execution_item_id',sa.String(64),nullable=False),sa.Column('state',sa.String(40),nullable=False),sa.Column('trigger_source',sa.String(32),nullable=False),sa.Column('attempt_count',sa.Integer(),nullable=False),sa.Column('max_attempts',sa.Integer(),nullable=False),sa.Column('next_attempt_at',sa.DateTime(timezone=True),nullable=False),sa.Column('lease_token',sa.String(96)),sa.Column('lease_until',sa.DateTime(timezone=True)),sa.Column('last_error',sa.Text()),sa.Column('resolution_json',sa.JSON(),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False))
    for c in ('supplier_operation_id','execution_id','execution_item_id','state','next_attempt_at','lease_token','lease_until'):op.create_index(f'ix_jrrj_{c}','journey_recovery_reconciliation_job',[c])
    op.create_index('uq_jrrj_operation_active','journey_recovery_reconciliation_job',['supplier_operation_id','state'],unique=False)
    op.create_table('journey_recovery_reconciliation_observation',
      sa.Column('observation_id',sa.String(64),primary_key=True),sa.Column('supplier_operation_id',sa.String(64),nullable=False),sa.Column('execution_item_id',sa.String(64),nullable=False),sa.Column('source',sa.String(24),nullable=False),sa.Column('external_event_id',sa.String(128)),sa.Column('observed_status',sa.String(40),nullable=False),sa.Column('supplier_confirmation_id',sa.String(128)),sa.Column('evidence_json',sa.JSON(),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False))
    for c in ('supplier_operation_id','execution_item_id','source','external_event_id','observed_status','created_at'):op.create_index(f'ix_jrro_{c}','journey_recovery_reconciliation_observation',[c])
    op.create_index('uq_jrro_source_external_event','journey_recovery_reconciliation_observation',['source','external_event_id'],unique=True)

def downgrade():
    op.drop_table('journey_recovery_reconciliation_observation');op.drop_table('journey_recovery_reconciliation_job');op.drop_table('journey_recovery_supplier_operation')
