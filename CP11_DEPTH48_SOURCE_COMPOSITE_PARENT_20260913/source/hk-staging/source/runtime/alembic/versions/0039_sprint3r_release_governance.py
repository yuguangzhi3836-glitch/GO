"""Sprint 3R recovery production release governance and environment promotion
Revision ID: 0039_sprint3r
Revises: 0038_sprint3q
"""
from alembic import op
import sqlalchemy as sa
revision='0039_sprint3r';down_revision='0038_sprint3q';branch_labels=None;depends_on=None

def upgrade():
    op.create_table('journey_recovery_config_version',
        sa.Column('config_version_id',sa.String(64),primary_key=True),sa.Column('config_key',sa.String(128),nullable=False),sa.Column('version_number',sa.Integer(),nullable=False),sa.Column('config_type',sa.String(32),nullable=False),sa.Column('scope_type',sa.String(24),nullable=False),sa.Column('scope_key',sa.String(128),nullable=False),sa.Column('source_ref_kind',sa.String(48)),sa.Column('source_ref_id',sa.String(96)),sa.Column('payload_json',sa.JSON(),nullable=False),sa.Column('content_hash',sa.String(64),nullable=False),sa.Column('created_by',sa.String(64),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.Column('supplier_fact_unchanged',sa.Boolean(),nullable=False),sa.UniqueConstraint('config_key','version_number',name='uq_recovery_config_key_version'))
    for c in ('config_key','config_type','scope_type','scope_key','source_ref_kind','source_ref_id','content_hash','created_by','created_at'):op.create_index(f'ix_jrcv_{c}','journey_recovery_config_version',[c])
    op.create_table('journey_recovery_environment_binding',
        sa.Column('environment_binding_id',sa.String(64),primary_key=True),sa.Column('environment',sa.String(16),nullable=False),sa.Column('config_key',sa.String(128),nullable=False),sa.Column('active_config_version_id',sa.String(64),nullable=False),sa.Column('previous_config_version_id',sa.String(64)),sa.Column('release_manifest_id',sa.String(64)),sa.Column('binding_hash',sa.String(64),nullable=False),sa.Column('drift_status',sa.String(24),nullable=False),sa.Column('promoted_by',sa.String(64)),sa.Column('promoted_at',sa.DateTime(timezone=True)),sa.Column('last_verified_at',sa.DateTime(timezone=True)),sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False),sa.Column('supplier_fact_unchanged',sa.Boolean(),nullable=False),sa.UniqueConstraint('environment','config_key',name='uq_recovery_environment_config_key'))
    for c in ('environment','config_key','active_config_version_id','previous_config_version_id','release_manifest_id','binding_hash','drift_status','promoted_by','promoted_at','last_verified_at'):op.create_index(f'ix_jreb_{c}','journey_recovery_environment_binding',[c])
    op.create_table('journey_recovery_release_manifest',
        sa.Column('release_manifest_id',sa.String(64),primary_key=True),sa.Column('source_environment',sa.String(16),nullable=False),sa.Column('target_environment',sa.String(16),nullable=False),sa.Column('state',sa.String(32),nullable=False),sa.Column('entries_json',sa.JSON(),nullable=False),sa.Column('manifest_hash',sa.String(64),nullable=False),sa.Column('dry_run_json',sa.JSON(),nullable=False),sa.Column('staging_evidence_json',sa.JSON(),nullable=False),sa.Column('rollback_target_manifest_id',sa.String(64)),sa.Column('requested_by',sa.String(64),nullable=False),sa.Column('requested_at',sa.DateTime(timezone=True),nullable=False),sa.Column('approved_by',sa.String(64)),sa.Column('approved_at',sa.DateTime(timezone=True)),sa.Column('promoted_by',sa.String(64)),sa.Column('promoted_at',sa.DateTime(timezone=True)),sa.Column('rolled_back_by',sa.String(64)),sa.Column('rolled_back_at',sa.DateTime(timezone=True)),sa.Column('promotion_result_json',sa.JSON(),nullable=False),sa.Column('supplier_fact_unchanged',sa.Boolean(),nullable=False))
    for c in ('source_environment','target_environment','state','manifest_hash','rollback_target_manifest_id','requested_by','approved_by','promoted_by','rolled_back_by'):op.create_index(f'ix_jrrm_{c}','journey_recovery_release_manifest',[c])
    op.create_table('journey_recovery_config_drift_assessment',
        sa.Column('drift_assessment_id',sa.String(64),primary_key=True),sa.Column('environment',sa.String(16),nullable=False),sa.Column('observed_bindings_json',sa.JSON(),nullable=False),sa.Column('expected_bindings_json',sa.JSON(),nullable=False),sa.Column('drift_json',sa.JSON(),nullable=False),sa.Column('drift_detected',sa.Boolean(),nullable=False),sa.Column('action',sa.String(32),nullable=False),sa.Column('created_by',sa.String(64),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.Column('supplier_fact_unchanged',sa.Boolean(),nullable=False))
    for c in ('environment','drift_detected','action','created_by','created_at'):op.create_index(f'ix_jrcda_{c}','journey_recovery_config_drift_assessment',[c])
    op.create_table('journey_recovery_release_event',
        sa.Column('release_event_id',sa.String(64),primary_key=True),sa.Column('release_manifest_id',sa.String(64)),sa.Column('event_type',sa.String(48),nullable=False),sa.Column('actor_id',sa.String(64)),sa.Column('payload_json',sa.JSON(),nullable=False),sa.Column('supplier_fact_unchanged',sa.Boolean(),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False))
    for c in ('release_manifest_id','event_type','actor_id','created_at'):op.create_index(f'ix_jrre_{c}','journey_recovery_release_event',[c])
    # Immutable config versions: no UPDATE/DELETE after creation.
    bind=op.get_bind();dialect=bind.dialect.name
    if dialect=='sqlite':
        op.execute("CREATE TRIGGER trg_jrcv_no_update BEFORE UPDATE ON journey_recovery_config_version BEGIN SELECT RAISE(ABORT,'IMMUTABLE_CONFIG_VERSION'); END")
        op.execute("CREATE TRIGGER trg_jrcv_no_delete BEFORE DELETE ON journey_recovery_config_version BEGIN SELECT RAISE(ABORT,'IMMUTABLE_CONFIG_VERSION'); END")
    elif dialect=='postgresql':
        op.execute("CREATE OR REPLACE FUNCTION deny_jrcv_mutation() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'IMMUTABLE_CONFIG_VERSION'; END $$")
        op.execute("CREATE TRIGGER trg_jrcv_no_update BEFORE UPDATE ON journey_recovery_config_version FOR EACH ROW EXECUTE FUNCTION deny_jrcv_mutation()")
        op.execute("CREATE TRIGGER trg_jrcv_no_delete BEFORE DELETE ON journey_recovery_config_version FOR EACH ROW EXECUTE FUNCTION deny_jrcv_mutation()")

def downgrade():
    bind=op.get_bind();dialect=bind.dialect.name
    if dialect=='sqlite':
        op.execute('DROP TRIGGER IF EXISTS trg_jrcv_no_update');op.execute('DROP TRIGGER IF EXISTS trg_jrcv_no_delete')
    elif dialect=='postgresql':
        op.execute('DROP TRIGGER IF EXISTS trg_jrcv_no_update ON journey_recovery_config_version');op.execute('DROP TRIGGER IF EXISTS trg_jrcv_no_delete ON journey_recovery_config_version');op.execute('DROP FUNCTION IF EXISTS deny_jrcv_mutation()')
    op.drop_table('journey_recovery_release_event');op.drop_table('journey_recovery_config_drift_assessment');op.drop_table('journey_recovery_release_manifest');op.drop_table('journey_recovery_environment_binding');op.drop_table('journey_recovery_config_version')
