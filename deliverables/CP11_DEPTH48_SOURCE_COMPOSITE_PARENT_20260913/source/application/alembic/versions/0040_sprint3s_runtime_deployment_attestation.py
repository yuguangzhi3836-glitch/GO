"""Sprint 3S runtime deployment attestation and health gate
Revision ID: 0040_sprint3s
Revises: 0039_sprint3r
"""
from alembic import op
import sqlalchemy as sa
revision='0040_sprint3s';down_revision='0039_sprint3r';branch_labels=None;depends_on=None
def upgrade():
    op.create_table('journey_recovery_deployment_attestation',sa.Column('deployment_attestation_id',sa.String(64),primary_key=True),sa.Column('release_manifest_id',sa.String(64),nullable=False),sa.Column('environment',sa.String(16),nullable=False),sa.Column('runtime_instance',sa.String(128),nullable=False),sa.Column('expected_fingerprint',sa.String(64),nullable=False),sa.Column('observed_fingerprint',sa.String(64),nullable=False),sa.Column('state',sa.String(32),nullable=False),sa.Column('attested_by',sa.String(64),nullable=False),sa.Column('attested_at',sa.DateTime(timezone=True),nullable=False),sa.Column('payload_json',sa.JSON(),nullable=False),sa.Column('supplier_fact_unchanged',sa.Boolean(),nullable=False))
    op.create_table('journey_recovery_release_verification',sa.Column('release_verification_id',sa.String(64),primary_key=True),sa.Column('release_manifest_id',sa.String(64),nullable=False),sa.Column('environment',sa.String(16),nullable=False),sa.Column('attestation_id',sa.String(64),nullable=False),sa.Column('smoke_test_json',sa.JSON(),nullable=False),sa.Column('health_slo_json',sa.JSON(),nullable=False),sa.Column('state',sa.String(32),nullable=False),sa.Column('action',sa.String(48),nullable=False),sa.Column('verified_by',sa.String(64),nullable=False),sa.Column('verified_at',sa.DateTime(timezone=True),nullable=False),sa.Column('supplier_fact_unchanged',sa.Boolean(),nullable=False))
    op.create_table('journey_recovery_release_evidence_seal',sa.Column('release_evidence_seal_id',sa.String(64),primary_key=True),sa.Column('release_manifest_id',sa.String(64),nullable=False),sa.Column('attestation_id',sa.String(64),nullable=False),sa.Column('verification_id',sa.String(64),nullable=False),sa.Column('evidence_hash',sa.String(64),nullable=False),sa.Column('previous_hash',sa.String(64)),sa.Column('seal_hash',sa.String(64),nullable=False),sa.Column('sealed_by',sa.String(64),nullable=False),sa.Column('sealed_at',sa.DateTime(timezone=True),nullable=False),sa.Column('supplier_fact_unchanged',sa.Boolean(),nullable=False))
    for t,cols,p in [('journey_recovery_deployment_attestation',['release_manifest_id','environment','runtime_instance','state','attested_at'],'jrda'),('journey_recovery_release_verification',['release_manifest_id','environment','attestation_id','state','action','verified_at'],'jrrv'),('journey_recovery_release_evidence_seal',['release_manifest_id','attestation_id','verification_id','evidence_hash','seal_hash','sealed_at'],'jrres')]:
        for c in cols: op.create_index(f'ix_{p}_{c}',t,[c])
    bind=op.get_bind();d=bind.dialect.name
    if d=='sqlite':
        op.execute("CREATE TRIGGER trg_jrres_no_update BEFORE UPDATE ON journey_recovery_release_evidence_seal BEGIN SELECT RAISE(ABORT,'IMMUTABLE_RELEASE_EVIDENCE_SEAL'); END");op.execute("CREATE TRIGGER trg_jrres_no_delete BEFORE DELETE ON journey_recovery_release_evidence_seal BEGIN SELECT RAISE(ABORT,'IMMUTABLE_RELEASE_EVIDENCE_SEAL'); END")
    elif d=='postgresql':
        op.execute("CREATE OR REPLACE FUNCTION deny_jrres_mutation() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'IMMUTABLE_RELEASE_EVIDENCE_SEAL'; END $$");op.execute("CREATE TRIGGER trg_jrres_no_update BEFORE UPDATE ON journey_recovery_release_evidence_seal FOR EACH ROW EXECUTE FUNCTION deny_jrres_mutation()");op.execute("CREATE TRIGGER trg_jrres_no_delete BEFORE DELETE ON journey_recovery_release_evidence_seal FOR EACH ROW EXECUTE FUNCTION deny_jrres_mutation()")
def downgrade():
    op.drop_table('journey_recovery_release_evidence_seal');op.drop_table('journey_recovery_release_verification');op.drop_table('journey_recovery_deployment_attestation')
