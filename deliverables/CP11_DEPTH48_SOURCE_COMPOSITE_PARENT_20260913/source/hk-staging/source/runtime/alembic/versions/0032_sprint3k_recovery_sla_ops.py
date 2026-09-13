"""Sprint 3K recovery SLA engine, escalation policy and human ops workflow
Revision ID: 0032_sprint3k
Revises: 0031_sprint3j
"""
from alembic import op
import sqlalchemy as sa
revision='0032_sprint3k';down_revision='0031_sprint3j';branch_labels=None;depends_on=None

def upgrade():
    for name,typ in [
      ('sla_policy_id',sa.String(64)),('queue_key',sa.String(64)),('current_escalation_level',sa.Integer()),
      ('acknowledge_due_at',sa.DateTime(timezone=True)),('resolution_due_at',sa.DateTime(timezone=True)),
      ('next_escalation_at',sa.DateTime(timezone=True)),('last_escalated_at',sa.DateTime(timezone=True)),
      ('playbook_key',sa.String(64)),('closure_evidence_status',sa.String(32))]:
        op.add_column('journey_recovery_operational_case',sa.Column(name,typ,nullable=True))
    op.execute("UPDATE journey_recovery_operational_case SET current_escalation_level=0 WHERE current_escalation_level IS NULL")
    for c in ('sla_policy_id','queue_key','acknowledge_due_at','resolution_due_at','next_escalation_at','closure_evidence_status'):
        op.create_index(f'ix_jroc_{c}','journey_recovery_operational_case',[c])
    op.create_table('journey_recovery_sla_policy',
      sa.Column('sla_policy_id',sa.String(64),primary_key=True),sa.Column('name',sa.String(128),nullable=False),sa.Column('vertical',sa.String(32)),sa.Column('adapter_key',sa.String(96)),sa.Column('severity',sa.String(16),nullable=False),sa.Column('queue_key',sa.String(64),nullable=False),sa.Column('acknowledge_sla_seconds',sa.Integer(),nullable=False),sa.Column('resolution_sla_seconds',sa.Integer(),nullable=False),sa.Column('escalation_steps_json',sa.JSON(),nullable=False),sa.Column('playbook_key',sa.String(64),nullable=False),sa.Column('playbook_json',sa.JSON(),nullable=False),sa.Column('required_evidence_kinds_json',sa.JSON(),nullable=False),sa.Column('enabled',sa.Boolean(),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False))
    for c in ('vertical','adapter_key','severity','queue_key'):op.create_index(f'ix_jrsp_{c}','journey_recovery_sla_policy',[c])
    op.create_table('journey_recovery_ops_queue',
      sa.Column('queue_key',sa.String(64),primary_key=True),sa.Column('name',sa.String(128),nullable=False),sa.Column('timezone_name',sa.String(64),nullable=False),sa.Column('on_call_owner',sa.String(64)),sa.Column('backup_owner',sa.String(64)),sa.Column('enabled',sa.Boolean(),nullable=False),sa.Column('metadata_json',sa.JSON(),nullable=False),sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False))
    for c in ('on_call_owner','backup_owner'):op.create_index(f'ix_jroq_{c}','journey_recovery_ops_queue',[c])
    op.create_table('journey_recovery_operational_event',
      sa.Column('operational_event_id',sa.String(64),primary_key=True),sa.Column('operational_case_id',sa.String(64),nullable=False),sa.Column('event_type',sa.String(48),nullable=False),sa.Column('actor_type',sa.String(32),nullable=False),sa.Column('actor_id',sa.String(64)),sa.Column('from_queue_key',sa.String(64)),sa.Column('to_queue_key',sa.String(64)),sa.Column('escalation_level',sa.Integer()),sa.Column('payload_json',sa.JSON(),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False))
    for c in ('operational_case_id','event_type','actor_id','to_queue_key','created_at'):op.create_index(f'ix_jroe_{c}','journey_recovery_operational_event',[c])

def downgrade():
    op.drop_table('journey_recovery_operational_event');op.drop_table('journey_recovery_ops_queue');op.drop_table('journey_recovery_sla_policy')
    for c in ('closure_evidence_status','playbook_key','last_escalated_at','next_escalation_at','resolution_due_at','acknowledge_due_at','current_escalation_level','queue_key','sla_policy_id'):
        op.drop_column('journey_recovery_operational_case',c)
