"""Sprint 3W runtime identity rotation trust revocation and telemetry key lifecycle
Revision ID: 0044_sprint3w
Revises: 0043_sprint3v
"""
from alembic import op
import sqlalchemy as sa
revision='0044_sprint3w';down_revision='0043_sprint3v';branch_labels=None;depends_on=None

def upgrade():
    op.create_table('journey_recovery_telemetry_key_version',
        sa.Column('telemetry_key_version_id',sa.String(64),primary_key=True),sa.Column('runtime_identity_id',sa.String(64),nullable=False),sa.Column('version_no',sa.Integer(),nullable=False),sa.Column('key_ref',sa.String(128),nullable=False),sa.Column('state',sa.String(24),nullable=False),sa.Column('valid_from',sa.DateTime(timezone=True),nullable=False),sa.Column('valid_until',sa.DateTime(timezone=True)),sa.Column('previous_key_version_id',sa.String(64)),sa.Column('transition_payload_hash',sa.String(64)),sa.Column('transition_signature',sa.String(128)),sa.Column('evidence_json',sa.JSON(),nullable=False),sa.Column('created_by',sa.String(64),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.Column('supplier_fact_unchanged',sa.Boolean(),nullable=False))
    op.create_table('journey_recovery_identity_revocation',
        sa.Column('identity_revocation_id',sa.String(64),primary_key=True),sa.Column('runtime_identity_id',sa.String(64),nullable=False),sa.Column('environment',sa.String(16),nullable=False),sa.Column('reason_code',sa.String(64),nullable=False),sa.Column('evidence_reference',sa.String(256),nullable=False),sa.Column('effective_at',sa.DateTime(timezone=True),nullable=False),sa.Column('revoked_by',sa.String(64),nullable=False),sa.Column('propagation_state',sa.String(32),nullable=False),sa.Column('cache_epoch',sa.Integer(),nullable=False),sa.Column('supplier_fact_unchanged',sa.Boolean(),nullable=False))
    op.create_table('journey_recovery_telemetry_security_incident',
        sa.Column('telemetry_security_incident_id',sa.String(64),primary_key=True),sa.Column('runtime_identity_id',sa.String(64),nullable=False),sa.Column('environment',sa.String(16),nullable=False),sa.Column('severity',sa.String(16),nullable=False),sa.Column('state',sa.String(24),nullable=False),sa.Column('reason_code',sa.String(64),nullable=False),sa.Column('quarantine_state',sa.String(24),nullable=False),sa.Column('evidence_json',sa.JSON(),nullable=False),sa.Column('opened_by',sa.String(64),nullable=False),sa.Column('opened_at',sa.DateTime(timezone=True),nullable=False),sa.Column('contained_at',sa.DateTime(timezone=True)),sa.Column('closed_at',sa.DateTime(timezone=True)),sa.Column('supplier_fact_unchanged',sa.Boolean(),nullable=False))
    op.create_table('journey_recovery_trust_cache_invalidation',
        sa.Column('trust_cache_invalidation_id',sa.String(64),primary_key=True),sa.Column('environment',sa.String(16),nullable=False),sa.Column('runtime_identity_id',sa.String(64)),sa.Column('previous_epoch',sa.Integer(),nullable=False),sa.Column('new_epoch',sa.Integer(),nullable=False),sa.Column('reason_code',sa.String(64),nullable=False),sa.Column('invalidated_by',sa.String(64),nullable=False),sa.Column('invalidated_at',sa.DateTime(timezone=True),nullable=False),sa.Column('supplier_fact_unchanged',sa.Boolean(),nullable=False))
    for t,cols,p in [
      ('journey_recovery_telemetry_key_version',['runtime_identity_id','version_no','key_ref','state','valid_from','valid_until','previous_key_version_id','transition_payload_hash','created_by','created_at'],'jrtkv'),
      ('journey_recovery_identity_revocation',['runtime_identity_id','environment','reason_code','effective_at','revoked_by','propagation_state'],'jrir'),
      ('journey_recovery_telemetry_security_incident',['runtime_identity_id','environment','severity','state','reason_code','quarantine_state','opened_by','opened_at','contained_at','closed_at'],'jrtsi'),
      ('journey_recovery_trust_cache_invalidation',['environment','runtime_identity_id','new_epoch','reason_code','invalidated_by','invalidated_at'],'jrtci')]:
        for c in cols: op.create_index(f'ix_{p}_{c}',t,[c])

def downgrade():
    op.drop_table('journey_recovery_trust_cache_invalidation');op.drop_table('journey_recovery_telemetry_security_incident');op.drop_table('journey_recovery_identity_revocation');op.drop_table('journey_recovery_telemetry_key_version')
