"""Sprint 3Y credential issuance authority attestation policy registry and hardware trust federation
Revision ID: 0046_sprint3y
Revises: 0045_sprint3x
"""
from alembic import op
import sqlalchemy as sa
revision='0046_sprint3y';down_revision='0045_sprint3x';branch_labels=None;depends_on=None

def upgrade():
    op.create_table('journey_recovery_hardware_trust_root',
        sa.Column('hardware_trust_root_id',sa.String(64),primary_key=True),sa.Column('root_key',sa.String(128),nullable=False,unique=True),sa.Column('provider',sa.String(64),nullable=False),sa.Column('trust_class',sa.String(32),nullable=False),sa.Column('state',sa.String(24),nullable=False),sa.Column('root_fingerprint',sa.String(64),nullable=False),sa.Column('valid_from',sa.DateTime(timezone=True),nullable=False),sa.Column('valid_until',sa.DateTime(timezone=True)),sa.Column('metadata_json',sa.JSON(),nullable=False),sa.Column('created_by',sa.String(64),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False),sa.Column('supplier_fact_unchanged',sa.Boolean(),nullable=False))
    op.create_table('journey_recovery_credential_issuer',
        sa.Column('credential_issuer_id',sa.String(64),primary_key=True),sa.Column('issuer_key',sa.String(128),nullable=False,unique=True),sa.Column('issuer_type',sa.String(32),nullable=False),sa.Column('environment',sa.String(16),nullable=False),sa.Column('hardware_trust_root_id',sa.String(64),nullable=False),sa.Column('state',sa.String(24),nullable=False),sa.Column('issuer_fingerprint',sa.String(64),nullable=False),sa.Column('verification_key_ref',sa.String(128),nullable=False),sa.Column('created_by',sa.String(64),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False),sa.Column('supplier_fact_unchanged',sa.Boolean(),nullable=False))
    op.create_table('journey_recovery_attestation_policy',
        sa.Column('attestation_policy_id',sa.String(64),primary_key=True),sa.Column('policy_key',sa.String(128),nullable=False),sa.Column('version_no',sa.Integer(),nullable=False),sa.Column('environment',sa.String(16),nullable=False),sa.Column('identity_type',sa.String(24),nullable=False),sa.Column('state',sa.String(24),nullable=False),sa.Column('min_trust_class',sa.String(32),nullable=False),sa.Column('allowed_attestation_types_json',sa.JSON(),nullable=False),sa.Column('allowed_issuer_ids_json',sa.JSON(),nullable=False),sa.Column('min_verifier_quorum',sa.Integer(),nullable=False),sa.Column('policy_json',sa.JSON(),nullable=False),sa.Column('created_by',sa.String(64),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.Column('activated_at',sa.DateTime(timezone=True)),sa.Column('supplier_fact_unchanged',sa.Boolean(),nullable=False),sa.UniqueConstraint('policy_key','version_no',name='uq_jrap_policy_version'))
    op.create_table('journey_recovery_credential_issuance',
        sa.Column('credential_issuance_id',sa.String(64),primary_key=True),sa.Column('runtime_identity_id',sa.String(64),nullable=False),sa.Column('attestation_policy_id',sa.String(64),nullable=False),sa.Column('credential_issuer_id',sa.String(64),nullable=False),sa.Column('hardware_trust_root_id',sa.String(64),nullable=False),sa.Column('runtime_attestation_evidence_id',sa.String(64),nullable=False),sa.Column('environment',sa.String(16),nullable=False),sa.Column('state',sa.String(32),nullable=False),sa.Column('credential_id',sa.String(128),unique=True),sa.Column('credential_fingerprint',sa.String(64)),sa.Column('eligibility_state',sa.String(32),nullable=False),sa.Column('predecessor_credential_id',sa.String(128)),sa.Column('requested_by',sa.String(64),nullable=False),sa.Column('requested_at',sa.DateTime(timezone=True),nullable=False),sa.Column('issued_by',sa.String(64)),sa.Column('issued_at',sa.DateTime(timezone=True)),sa.Column('revoked_at',sa.DateTime(timezone=True)),sa.Column('supplier_fact_unchanged',sa.Boolean(),nullable=False))
    op.create_table('journey_recovery_attestation_verification',
        sa.Column('attestation_verification_id',sa.String(64),primary_key=True),sa.Column('credential_issuance_id',sa.String(64),nullable=False),sa.Column('verifier_id',sa.String(128),nullable=False),sa.Column('verdict',sa.String(16),nullable=False),sa.Column('evidence_reference',sa.String(256),nullable=False),sa.Column('verification_hash',sa.String(64),nullable=False),sa.Column('verified_at',sa.DateTime(timezone=True),nullable=False),sa.Column('supplier_fact_unchanged',sa.Boolean(),nullable=False),sa.UniqueConstraint('credential_issuance_id','verifier_id',name='uq_jrav_issuance_verifier'))
    op.create_table('journey_recovery_credential_lineage',
        sa.Column('credential_lineage_id',sa.String(64),primary_key=True),sa.Column('credential_issuance_id',sa.String(64),nullable=False,unique=True),sa.Column('runtime_identity_id',sa.String(64),nullable=False),sa.Column('predecessor_credential_id',sa.String(128)),sa.Column('credential_id',sa.String(128),nullable=False,unique=True),sa.Column('lineage_hash',sa.String(64),nullable=False),sa.Column('created_by',sa.String(64),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.Column('supplier_fact_unchanged',sa.Boolean(),nullable=False))
    op.create_table('journey_recovery_revocation_sync',
        sa.Column('revocation_sync_id',sa.String(64),primary_key=True),sa.Column('authority_type',sa.String(24),nullable=False),sa.Column('authority_id',sa.String(64),nullable=False),sa.Column('environment',sa.String(16),nullable=False),sa.Column('revocation_version',sa.Integer(),nullable=False),sa.Column('revoked_credential_ids_json',sa.JSON(),nullable=False),sa.Column('propagation_state',sa.String(32),nullable=False),sa.Column('evidence_reference',sa.String(256),nullable=False),sa.Column('synchronized_by',sa.String(64),nullable=False),sa.Column('synchronized_at',sa.DateTime(timezone=True),nullable=False),sa.Column('supplier_fact_unchanged',sa.Boolean(),nullable=False),sa.UniqueConstraint('authority_type','authority_id','revocation_version',name='uq_jrrs_authority_version'))
    tables={
      'journey_recovery_hardware_trust_root':('jrhtr',['provider','trust_class','state','root_fingerprint','valid_from','valid_until']),
      'journey_recovery_credential_issuer':('jrci',['issuer_type','environment','hardware_trust_root_id','state','issuer_fingerprint']),
      'journey_recovery_attestation_policy':('jrap',['policy_key','version_no','environment','identity_type','state','min_trust_class','created_at','activated_at']),
      'journey_recovery_credential_issuance':('jrciu',['runtime_identity_id','attestation_policy_id','credential_issuer_id','hardware_trust_root_id','runtime_attestation_evidence_id','environment','state','credential_id','credential_fingerprint','eligibility_state','predecessor_credential_id','requested_at','issued_at','revoked_at']),
      'journey_recovery_attestation_verification':('jrav',['credential_issuance_id','verifier_id','verdict','verification_hash','verified_at']),
      'journey_recovery_credential_lineage':('jrcl',['runtime_identity_id','predecessor_credential_id','credential_id','lineage_hash','created_at']),
      'journey_recovery_revocation_sync':('jrrs',['authority_type','authority_id','environment','revocation_version','propagation_state','synchronized_at'])}
    for t,(prefix,cols) in tables.items():
        for c in cols: op.create_index(f'ix_s3y_{prefix}_{c}',t,[c])
    bind=op.get_bind();dialect=bind.dialect.name
    imm=['journey_recovery_credential_lineage','journey_recovery_attestation_verification','journey_recovery_revocation_sync']
    if dialect=='sqlite':
        for table in imm:
            op.execute(f"CREATE TRIGGER {table}_deny_update BEFORE UPDATE ON {table} BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_CREDENTIAL_AUTHORITY_EVIDENCE'); END;")
            op.execute(f"CREATE TRIGGER {table}_deny_delete BEFORE DELETE ON {table} BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_CREDENTIAL_AUTHORITY_EVIDENCE'); END;")
    elif dialect=='postgresql':
        op.execute("CREATE OR REPLACE FUNCTION deny_credential_authority_evidence_mutation() RETURNS trigger AS $$ BEGIN RAISE EXCEPTION 'IMMUTABLE_CREDENTIAL_AUTHORITY_EVIDENCE'; END; $$ LANGUAGE plpgsql;")
        for table in imm:
            op.execute(f"CREATE TRIGGER {table}_deny_update BEFORE UPDATE ON {table} FOR EACH ROW EXECUTE FUNCTION deny_credential_authority_evidence_mutation();")
            op.execute(f"CREATE TRIGGER {table}_deny_delete BEFORE DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION deny_credential_authority_evidence_mutation();")

def downgrade():
    for t in ['journey_recovery_revocation_sync','journey_recovery_credential_lineage','journey_recovery_attestation_verification','journey_recovery_credential_issuance','journey_recovery_attestation_policy','journey_recovery_credential_issuer','journey_recovery_hardware_trust_root']:
        op.drop_table(t)
