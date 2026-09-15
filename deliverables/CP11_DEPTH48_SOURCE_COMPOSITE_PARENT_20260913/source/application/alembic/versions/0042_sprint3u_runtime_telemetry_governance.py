"""Sprint 3U runtime telemetry provenance multi-window SLO and incident correlation
Revision ID: 0042_sprint3u
Revises: 0041_sprint3t
"""
from alembic import op
import sqlalchemy as sa
revision='0042_sprint3u';down_revision='0041_sprint3t';branch_labels=None;depends_on=None

def upgrade():
    op.create_table('journey_recovery_telemetry_source',
        sa.Column('telemetry_source_id',sa.String(64),primary_key=True),sa.Column('source_key',sa.String(128),nullable=False,unique=True),sa.Column('source_type',sa.String(32),nullable=False),sa.Column('environment',sa.String(16),nullable=False),sa.Column('state',sa.String(24),nullable=False),sa.Column('trust_level',sa.String(24),nullable=False),sa.Column('endpoint_ref',sa.String(256)),sa.Column('config_json',sa.JSON(),nullable=False),sa.Column('source_fingerprint',sa.String(64),nullable=False),sa.Column('created_by',sa.String(64),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False),sa.Column('supplier_fact_unchanged',sa.Boolean(),nullable=False))
    op.create_table('journey_recovery_telemetry_quality_assessment',
        sa.Column('telemetry_quality_assessment_id',sa.String(64),primary_key=True),sa.Column('runtime_observation_id',sa.String(64),nullable=False),sa.Column('telemetry_source_id',sa.String(64),nullable=False),sa.Column('environment',sa.String(16),nullable=False),sa.Column('state',sa.String(24),nullable=False),sa.Column('freshness_seconds',sa.Float(),nullable=False),sa.Column('quality_score',sa.Float(),nullable=False),sa.Column('checks_json',sa.JSON(),nullable=False),sa.Column('assessed_at',sa.DateTime(timezone=True),nullable=False),sa.Column('supplier_fact_unchanged',sa.Boolean(),nullable=False))
    op.create_table('journey_recovery_slo_policy',
        sa.Column('slo_policy_id',sa.String(64),primary_key=True),sa.Column('policy_key',sa.String(128),nullable=False,unique=True),sa.Column('environment',sa.String(16),nullable=False),sa.Column('state',sa.String(24),nullable=False),sa.Column('slo_target',sa.Float(),nullable=False),sa.Column('windows_json',sa.JSON(),nullable=False),sa.Column('min_quality_score',sa.Float(),nullable=False),sa.Column('min_sources',sa.Integer(),nullable=False),sa.Column('created_by',sa.String(64),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False),sa.Column('supplier_fact_unchanged',sa.Boolean(),nullable=False))
    op.create_table('journey_recovery_runtime_incident_correlation',
        sa.Column('runtime_incident_correlation_id',sa.String(64),primary_key=True),sa.Column('safety_assessment_id',sa.String(64)),sa.Column('release_manifest_id',sa.String(64)),sa.Column('deployment_attestation_id',sa.String(64)),sa.Column('release_verification_id',sa.String(64)),sa.Column('learning_incident_id',sa.String(64)),sa.Column('environment',sa.String(16),nullable=False),sa.Column('correlation_state',sa.String(32),nullable=False),sa.Column('confidence',sa.String(16),nullable=False),sa.Column('evidence_json',sa.JSON(),nullable=False),sa.Column('correlated_at',sa.DateTime(timezone=True),nullable=False),sa.Column('supplier_fact_unchanged',sa.Boolean(),nullable=False))
    idx=[('journey_recovery_telemetry_source',['source_key','source_type','environment','state','trust_level','source_fingerprint'],'jrtsp'),('journey_recovery_telemetry_quality_assessment',['runtime_observation_id','telemetry_source_id','environment','state','assessed_at'],'jrtqa'),('journey_recovery_slo_policy',['policy_key','environment','state','created_at'],'jrslo'),('journey_recovery_runtime_incident_correlation',['safety_assessment_id','release_manifest_id','deployment_attestation_id','release_verification_id','learning_incident_id','environment','correlation_state','confidence','correlated_at'],'jrric')]
    for t,cols,p in idx:
        for c in cols: op.create_index(f'ix_{p}_{c}',t,[c])

def downgrade():
    op.drop_table('journey_recovery_runtime_incident_correlation');op.drop_table('journey_recovery_slo_policy');op.drop_table('journey_recovery_telemetry_quality_assessment');op.drop_table('journey_recovery_telemetry_source')
