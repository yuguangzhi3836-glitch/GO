"""Sprint 3X runtime identity reissuance hardware trust attestation and credential recovery governance
Revision ID: 0045_sprint3x
Revises: 0044_sprint3w
"""
from alembic import op
import sqlalchemy as sa
revision='0045_sprint3x';down_revision='0044_sprint3w';branch_labels=None;depends_on=None

def upgrade():
    op.create_table('journey_recovery_identity_reissuance_request',
        sa.Column('identity_reissuance_request_id',sa.String(64),primary_key=True),sa.Column('predecessor_identity_id',sa.String(64),nullable=False),sa.Column('replacement_identity_id',sa.String(64)),sa.Column('environment',sa.String(16),nullable=False),sa.Column('identity_type',sa.String(24),nullable=False),sa.Column('replacement_identity_key',sa.String(128),nullable=False,unique=True),sa.Column('replacement_subject_ref',sa.String(256),nullable=False),sa.Column('replacement_key_ref',sa.String(128),nullable=False),sa.Column('state',sa.String(32),nullable=False),sa.Column('break_glass',sa.Boolean(),nullable=False),sa.Column('reason_code',sa.String(64),nullable=False),sa.Column('request_evidence_reference',sa.String(256),nullable=False),sa.Column('attestation_key_ref',sa.String(128),nullable=False),sa.Column('requested_by',sa.String(64),nullable=False),sa.Column('approved_by',sa.String(64)),sa.Column('approval_evidence_reference',sa.String(256)),sa.Column('requested_at',sa.DateTime(timezone=True),nullable=False),sa.Column('approved_at',sa.DateTime(timezone=True)),sa.Column('issued_at',sa.DateTime(timezone=True)),sa.Column('supplier_fact_unchanged',sa.Boolean(),nullable=False))
    op.create_table('journey_recovery_runtime_attestation_evidence',
        sa.Column('runtime_attestation_evidence_id',sa.String(64),primary_key=True),sa.Column('identity_reissuance_request_id',sa.String(64),nullable=False),sa.Column('predecessor_identity_id',sa.String(64),nullable=False),sa.Column('environment',sa.String(16),nullable=False),sa.Column('attestation_type',sa.String(32),nullable=False),sa.Column('challenge_nonce',sa.String(128),nullable=False,unique=True),sa.Column('workload_measurement',sa.String(256),nullable=False),sa.Column('evidence_reference',sa.String(256),nullable=False),sa.Column('evidence_hash',sa.String(64),nullable=False),sa.Column('attestation_signature',sa.String(128),nullable=False),sa.Column('verification_state',sa.String(24),nullable=False),sa.Column('verification_json',sa.JSON(),nullable=False),sa.Column('verified_by',sa.String(64),nullable=False),sa.Column('verified_at',sa.DateTime(timezone=True),nullable=False),sa.Column('supplier_fact_unchanged',sa.Boolean(),nullable=False))
    op.create_table('journey_recovery_runtime_identity_lineage',
        sa.Column('runtime_identity_lineage_id',sa.String(64),primary_key=True),sa.Column('predecessor_identity_id',sa.String(64),nullable=False),sa.Column('replacement_identity_id',sa.String(64),nullable=False,unique=True),sa.Column('identity_reissuance_request_id',sa.String(64),nullable=False,unique=True),sa.Column('environment',sa.String(16),nullable=False),sa.Column('lineage_hash',sa.String(64),nullable=False),sa.Column('created_by',sa.String(64),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.Column('supplier_fact_unchanged',sa.Boolean(),nullable=False))
    op.create_table('journey_recovery_revoked_identity_tombstone',
        sa.Column('revoked_identity_tombstone_id',sa.String(64),primary_key=True),sa.Column('runtime_identity_id',sa.String(64),nullable=False,unique=True),sa.Column('environment',sa.String(16),nullable=False),sa.Column('identity_fingerprint',sa.String(64),nullable=False),sa.Column('terminal_state',sa.String(24),nullable=False),sa.Column('reason_code',sa.String(64),nullable=False),sa.Column('evidence_reference',sa.String(256),nullable=False),sa.Column('tombstone_hash',sa.String(64),nullable=False),sa.Column('replacement_identity_id',sa.String(64)),sa.Column('created_by',sa.String(64),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.Column('supplier_fact_unchanged',sa.Boolean(),nullable=False))
    for t,cols,p in [
      ('journey_recovery_identity_reissuance_request',['predecessor_identity_id','replacement_identity_id','environment','identity_type','replacement_identity_key','state','break_glass','reason_code','requested_by','approved_by','requested_at','approved_at','issued_at'],'jrirr'),
      ('journey_recovery_runtime_attestation_evidence',['identity_reissuance_request_id','predecessor_identity_id','environment','attestation_type','challenge_nonce','workload_measurement','evidence_hash','verification_state','verified_by','verified_at'],'jrrae'),
      ('journey_recovery_runtime_identity_lineage',['predecessor_identity_id','replacement_identity_id','identity_reissuance_request_id','environment','lineage_hash','created_by','created_at'],'jrril'),
      ('journey_recovery_revoked_identity_tombstone',['runtime_identity_id','environment','identity_fingerprint','terminal_state','reason_code','tombstone_hash','replacement_identity_id','created_by','created_at'],'jrrit')]:
        for c in cols: op.create_index(f'ix_{p}_{c}',t,[c])
    # Tombstones and lineage are append-only recovery/security evidence.
    bind=op.get_bind();dialect=bind.dialect.name
    if dialect=='sqlite':
        for table in ['journey_recovery_runtime_identity_lineage','journey_recovery_revoked_identity_tombstone']:
            op.execute(f"CREATE TRIGGER {table}_deny_update BEFORE UPDATE ON {table} BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_IDENTITY_RECOVERY_EVIDENCE'); END;")
            op.execute(f"CREATE TRIGGER {table}_deny_delete BEFORE DELETE ON {table} BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_IDENTITY_RECOVERY_EVIDENCE'); END;")
    elif dialect=='postgresql':
        op.execute("CREATE OR REPLACE FUNCTION deny_identity_recovery_evidence_mutation() RETURNS trigger AS $$ BEGIN RAISE EXCEPTION 'IMMUTABLE_IDENTITY_RECOVERY_EVIDENCE'; END; $$ LANGUAGE plpgsql;")
        for table in ['journey_recovery_runtime_identity_lineage','journey_recovery_revoked_identity_tombstone']:
            op.execute(f"CREATE TRIGGER {table}_deny_update BEFORE UPDATE ON {table} FOR EACH ROW EXECUTE FUNCTION deny_identity_recovery_evidence_mutation();")
            op.execute(f"CREATE TRIGGER {table}_deny_delete BEFORE DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION deny_identity_recovery_evidence_mutation();")

def downgrade():
    op.drop_table('journey_recovery_revoked_identity_tombstone');op.drop_table('journey_recovery_runtime_identity_lineage');op.drop_table('journey_recovery_runtime_attestation_evidence');op.drop_table('journey_recovery_identity_reissuance_request')
