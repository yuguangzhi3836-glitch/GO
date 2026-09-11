"""Sprint 3Q recovery learning incident response safe rollback change control
Revision ID: 0038_sprint3q
Revises: 0037_sprint3p
"""
from alembic import op
import sqlalchemy as sa
revision='0038_sprint3q';down_revision='0037_sprint3p';branch_labels=None;depends_on=None

def upgrade():
    op.create_table('journey_recovery_learning_incident',
        sa.Column('incident_id',sa.String(64),primary_key=True),sa.Column('scope_type',sa.String(24),nullable=False),sa.Column('scope_key',sa.String(128),nullable=False),sa.Column('severity',sa.String(16),nullable=False),sa.Column('state',sa.String(32),nullable=False),sa.Column('reason',sa.String(512),nullable=False),sa.Column('opened_by',sa.String(64),nullable=False),sa.Column('opened_at',sa.DateTime(timezone=True),nullable=False),sa.Column('kill_switch_id',sa.String(64)),sa.Column('rollback_snapshot_id',sa.String(64)),sa.Column('affected_objects_json',sa.JSON(),nullable=False),sa.Column('postmortem_evidence_json',sa.JSON(),nullable=False),sa.Column('approved_resume_change_id',sa.String(64)),sa.Column('closed_by',sa.String(64)),sa.Column('closed_at',sa.DateTime(timezone=True)),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False))
    for c in ('scope_type','scope_key','severity','state','opened_by','opened_at','kill_switch_id','rollback_snapshot_id','approved_resume_change_id','closed_by','closed_at'):op.create_index(f'ix_jrli_{c}','journey_recovery_learning_incident',[c])
    op.create_table('journey_recovery_rollback_snapshot',
        sa.Column('rollback_snapshot_id',sa.String(64),primary_key=True),sa.Column('incident_id',sa.String(64),nullable=False),sa.Column('scope_type',sa.String(24),nullable=False),sa.Column('scope_key',sa.String(128),nullable=False),sa.Column('baseline_parameters_json',sa.JSON(),nullable=False),sa.Column('strategy_snapshot_json',sa.JSON(),nullable=False),sa.Column('experiment_snapshot_json',sa.JSON(),nullable=False),sa.Column('calibration_snapshot_json',sa.JSON(),nullable=False),sa.Column('learning_registry_snapshot_json',sa.JSON(),nullable=False),sa.Column('snapshot_hash',sa.String(64),nullable=False),sa.Column('created_by',sa.String(64),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False))
    for c in ('incident_id','scope_type','scope_key','snapshot_hash','created_by','created_at'):op.create_index(f'ix_jrrs_{c}','journey_recovery_rollback_snapshot',[c])
    op.create_table('journey_recovery_learning_change_request',
        sa.Column('change_request_id',sa.String(64),primary_key=True),sa.Column('incident_id',sa.String(64),nullable=False),sa.Column('change_type',sa.String(32),nullable=False),sa.Column('state',sa.String(24),nullable=False),sa.Column('requested_scope_json',sa.JSON(),nullable=False),sa.Column('resume_plan_json',sa.JSON(),nullable=False),sa.Column('change_window_start',sa.DateTime(timezone=True),nullable=False),sa.Column('change_window_end',sa.DateTime(timezone=True),nullable=False),sa.Column('requested_by',sa.String(64),nullable=False),sa.Column('requested_at',sa.DateTime(timezone=True),nullable=False),sa.Column('approved_by',sa.String(64)),sa.Column('approved_at',sa.DateTime(timezone=True)),sa.Column('executed_by',sa.String(64)),sa.Column('executed_at',sa.DateTime(timezone=True)),sa.Column('execution_result_json',sa.JSON(),nullable=False),sa.Column('supplier_fact_unchanged',sa.Boolean(),nullable=False))
    for c in ('incident_id','change_type','state','change_window_start','change_window_end','requested_by','approved_by','executed_by'):op.create_index(f'ix_jrlcr_{c}','journey_recovery_learning_change_request',[c])
    op.create_table('journey_recovery_learning_incident_event',
        sa.Column('event_id',sa.String(64),primary_key=True),sa.Column('incident_id',sa.String(64),nullable=False),sa.Column('event_type',sa.String(48),nullable=False),sa.Column('actor_id',sa.String(64)),sa.Column('payload_json',sa.JSON(),nullable=False),sa.Column('supplier_fact_unchanged',sa.Boolean(),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False))
    for c in ('incident_id','event_type','actor_id','created_at'):op.create_index(f'ix_jrlie_{c}','journey_recovery_learning_incident_event',[c])

def downgrade():
    op.drop_table('journey_recovery_learning_incident_event');op.drop_table('journey_recovery_learning_change_request');op.drop_table('journey_recovery_rollback_snapshot');op.drop_table('journey_recovery_learning_incident')
