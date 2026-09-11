"""Sprint 3V telemetry trust chain signed runtime identity and automation policy
Revision ID: 0043_sprint3v
Revises: 0042_sprint3u
"""
from alembic import op
import sqlalchemy as sa
revision='0043_sprint3v';down_revision='0042_sprint3u';branch_labels=None;depends_on=None

def upgrade():
    op.create_table('journey_recovery_runtime_identity',
        sa.Column('runtime_identity_id',sa.String(64),primary_key=True),sa.Column('identity_key',sa.String(128),nullable=False,unique=True),sa.Column('identity_type',sa.String(24),nullable=False),sa.Column('environment',sa.String(16),nullable=False),sa.Column('state',sa.String(24),nullable=False),sa.Column('subject_ref',sa.String(256),nullable=False),sa.Column('verification_key_ref',sa.String(128),nullable=False),sa.Column('identity_fingerprint',sa.String(64),nullable=False),sa.Column('created_by',sa.String(64),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False),sa.Column('supplier_fact_unchanged',sa.Boolean(),nullable=False))
    op.create_table('journey_recovery_signed_telemetry_envelope',
        sa.Column('telemetry_envelope_id',sa.String(64),primary_key=True),sa.Column('telemetry_source_id',sa.String(64),nullable=False),sa.Column('workload_identity_id',sa.String(64),nullable=False),sa.Column('collector_identity_id',sa.String(64),nullable=False),sa.Column('runtime_observation_id',sa.String(64)),sa.Column('environment',sa.String(16),nullable=False),sa.Column('nonce',sa.String(128),nullable=False,unique=True),sa.Column('sequence_no',sa.Integer(),nullable=False),sa.Column('observed_at',sa.DateTime(timezone=True),nullable=False),sa.Column('received_at',sa.DateTime(timezone=True),nullable=False),sa.Column('payload_hash',sa.String(64),nullable=False),sa.Column('signature',sa.String(128),nullable=False),sa.Column('verification_state',sa.String(32),nullable=False),sa.Column('verification_json',sa.JSON(),nullable=False),sa.Column('supplier_fact_unchanged',sa.Boolean(),nullable=False))
    op.create_table('journey_recovery_telemetry_trust_assessment',
        sa.Column('telemetry_trust_assessment_id',sa.String(64),primary_key=True),sa.Column('environment',sa.String(16),nullable=False),sa.Column('state',sa.String(32),nullable=False),sa.Column('evidence_level',sa.String(16),nullable=False),sa.Column('source_quorum',sa.Integer(),nullable=False),sa.Column('verified_source_count',sa.Integer(),nullable=False),sa.Column('evidence_json',sa.JSON(),nullable=False),sa.Column('assessed_at',sa.DateTime(timezone=True),nullable=False),sa.Column('supplier_fact_unchanged',sa.Boolean(),nullable=False))
    op.create_table('journey_recovery_incident_automation_policy',
        sa.Column('incident_automation_policy_id',sa.String(64),primary_key=True),sa.Column('policy_key',sa.String(128),nullable=False,unique=True),sa.Column('environment',sa.String(16),nullable=False),sa.Column('state',sa.String(24),nullable=False),sa.Column('min_evidence_level_for_freeze',sa.String(16),nullable=False),sa.Column('min_source_quorum',sa.Integer(),nullable=False),sa.Column('max_clock_skew_seconds',sa.Integer(),nullable=False),sa.Column('envelope_freshness_seconds',sa.Integer(),nullable=False),sa.Column('allow_auto_freeze',sa.Boolean(),nullable=False),sa.Column('allow_auto_rollback_recommendation',sa.Boolean(),nullable=False),sa.Column('policy_json',sa.JSON(),nullable=False),sa.Column('created_by',sa.String(64),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False),sa.Column('supplier_fact_unchanged',sa.Boolean(),nullable=False))
    for t,cols,p in [
      ('journey_recovery_runtime_identity',['identity_key','identity_type','environment','state','identity_fingerprint'],'jrri'),
      ('journey_recovery_signed_telemetry_envelope',['telemetry_source_id','workload_identity_id','collector_identity_id','runtime_observation_id','environment','nonce','sequence_no','observed_at','verification_state'],'jrste'),
      ('journey_recovery_telemetry_trust_assessment',['environment','state','evidence_level','assessed_at'],'jrtta'),
      ('journey_recovery_incident_automation_policy',['policy_key','environment','state','created_at'],'jriap')]:
        for c in cols: op.create_index(f'ix_{p}_{c}',t,[c])

def downgrade():
    op.drop_table('journey_recovery_incident_automation_policy');op.drop_table('journey_recovery_telemetry_trust_assessment');op.drop_table('journey_recovery_signed_telemetry_envelope');op.drop_table('journey_recovery_runtime_identity')
