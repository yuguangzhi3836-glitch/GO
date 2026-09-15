"""Sprint 3P recovery data quality benchmark privacy learning kill switch
Revision ID: 0037_sprint3p
Revises: 0036_sprint3o
"""
from alembic import op
import sqlalchemy as sa
revision='0037_sprint3p';down_revision='0036_sprint3o';branch_labels=None;depends_on=None

def upgrade():
    op.create_table('journey_recovery_supplier_identity_map',
        sa.Column('supplier_identity_map_id',sa.String(64),primary_key=True),
        sa.Column('vertical',sa.String(32),nullable=False),sa.Column('adapter_key',sa.String(96),nullable=False),
        sa.Column('supplier_id',sa.String(64),nullable=False),sa.Column('mapping_state',sa.String(24),nullable=False),
        sa.Column('evidence_json',sa.JSON(),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False),
        sa.UniqueConstraint('vertical','adapter_key',name='uq_recovery_supplier_identity_vertical_adapter'))
    for c in ('vertical','adapter_key','supplier_id','mapping_state'):op.create_index(f'ix_jrsim_{c}','journey_recovery_supplier_identity_map',[c])
    op.create_table('journey_recovery_data_quality_assessment',
        sa.Column('data_quality_assessment_id',sa.String(64),primary_key=True),sa.Column('vertical',sa.String(32),nullable=False),sa.Column('adapter_key',sa.String(96),nullable=False),sa.Column('supplier_id',sa.String(64)),sa.Column('sample_count',sa.Integer(),nullable=False),sa.Column('quality_state',sa.String(24),nullable=False),sa.Column('contamination_detected',sa.Boolean(),nullable=False),sa.Column('anomaly_rate',sa.Float(),nullable=False),sa.Column('checks_json',sa.JSON(),nullable=False),sa.Column('action',sa.String(32),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False))
    for c in ('vertical','adapter_key','supplier_id','quality_state','contamination_detected','action','created_at'):op.create_index(f'ix_jrdqa_{c}','journey_recovery_data_quality_assessment',[c])
    op.create_table('journey_recovery_sample_quarantine',
        sa.Column('quarantine_id',sa.String(64),primary_key=True),sa.Column('vertical',sa.String(32),nullable=False),sa.Column('adapter_key',sa.String(96),nullable=False),sa.Column('source_kind',sa.String(48),nullable=False),sa.Column('source_id',sa.String(96),nullable=False),sa.Column('reason_code',sa.String(64),nullable=False),sa.Column('released',sa.Boolean(),nullable=False),sa.Column('released_by',sa.String(64)),sa.Column('released_at',sa.DateTime(timezone=True)),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False))
    for c in ('vertical','adapter_key','source_kind','source_id','reason_code','released','created_at'):op.create_index(f'ix_jrsq_{c}','journey_recovery_sample_quarantine',[c])
    op.create_table('journey_recovery_privacy_budget',
        sa.Column('privacy_budget_id',sa.String(64),primary_key=True),sa.Column('scope_key',sa.String(128),nullable=False,unique=True),sa.Column('epsilon_budget',sa.Float(),nullable=False),sa.Column('epsilon_used',sa.Float(),nullable=False),sa.Column('release_count',sa.Integer(),nullable=False),sa.Column('state',sa.String(24),nullable=False),sa.Column('reset_at',sa.DateTime(timezone=True)),sa.Column('governance_json',sa.JSON(),nullable=False),sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False))
    for c in ('scope_key','state','reset_at'):op.create_index(f'ix_jrpb_{c}','journey_recovery_privacy_budget',[c])
    op.create_table('journey_recovery_learning_kill_switch',
        sa.Column('kill_switch_id',sa.String(64),primary_key=True),sa.Column('scope_type',sa.String(24),nullable=False),sa.Column('scope_key',sa.String(128),nullable=False),sa.Column('enabled',sa.Boolean(),nullable=False),sa.Column('reason',sa.String(512)),sa.Column('activated_by',sa.String(64)),sa.Column('activated_at',sa.DateTime(timezone=True)),sa.Column('deactivated_by',sa.String(64)),sa.Column('deactivated_at',sa.DateTime(timezone=True)),sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False),sa.UniqueConstraint('scope_type','scope_key',name='uq_recovery_learning_kill_scope'))
    for c in ('scope_type','scope_key','enabled','activated_by','activated_at','deactivated_by','deactivated_at'):op.create_index(f'ix_jrlks_{c}','journey_recovery_learning_kill_switch',[c])

def downgrade():
    op.drop_table('journey_recovery_learning_kill_switch');op.drop_table('journey_recovery_privacy_budget');op.drop_table('journey_recovery_sample_quarantine');op.drop_table('journey_recovery_data_quality_assessment');op.drop_table('journey_recovery_supplier_identity_map')
