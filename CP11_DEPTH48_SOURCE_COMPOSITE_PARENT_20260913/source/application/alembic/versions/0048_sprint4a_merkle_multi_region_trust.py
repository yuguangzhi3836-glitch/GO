"""Sprint 4A Merkle transparency, external witness, multi-region trust consensus.

Revision ID: 0048_sprint4a
Revises: 0047_sprint3z
"""
from alembic import op
import sqlalchemy as sa
revision='0048_sprint4a';down_revision='0047_sprint3z';branch_labels=None;depends_on=None

def _immutable(table):
    d=op.get_bind().dialect.name
    if d=='sqlite':
        op.execute(f"CREATE TRIGGER {table}_deny_update BEFORE UPDATE ON {table} BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_EXTERNAL_TRUST_EVIDENCE'); END;")
        op.execute(f"CREATE TRIGGER {table}_deny_delete BEFORE DELETE ON {table} BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_EXTERNAL_TRUST_EVIDENCE'); END;")
    elif d=='postgresql':
        op.execute("""CREATE OR REPLACE FUNCTION deny_external_trust_evidence_mutation() RETURNS trigger AS $$ BEGIN RAISE EXCEPTION 'IMMUTABLE_EXTERNAL_TRUST_EVIDENCE'; END; $$ LANGUAGE plpgsql;""")
        op.execute(f"CREATE TRIGGER {table}_deny_update BEFORE UPDATE ON {table} FOR EACH ROW EXECUTE FUNCTION deny_external_trust_evidence_mutation();")
        op.execute(f"CREATE TRIGGER {table}_deny_delete BEFORE DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION deny_external_trust_evidence_mutation();")

def upgrade():
    op.create_table('journey_recovery_merkle_checkpoint',
      sa.Column('merkle_checkpoint_id',sa.String(64),primary_key=True),sa.Column('environment',sa.String(16),nullable=False),sa.Column('tree_size',sa.Integer(),nullable=False),sa.Column('root_hash',sa.String(64),nullable=False),sa.Column('first_sequence_no',sa.Integer(),nullable=False),sa.Column('last_sequence_no',sa.Integer(),nullable=False),sa.Column('checkpoint_hash',sa.String(64),nullable=False,unique=True),sa.Column('state',sa.String(24),nullable=False),sa.Column('created_by',sa.String(64),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.Column('supplier_fact_unchanged',sa.Boolean(),nullable=False,server_default=sa.true()))
    op.create_table('journey_recovery_external_trust_witness',
      sa.Column('external_trust_witness_id',sa.String(64),primary_key=True),sa.Column('witness_key',sa.String(128),nullable=False,unique=True),sa.Column('environment',sa.String(16),nullable=False),sa.Column('verification_key_ref',sa.String(256),nullable=False),sa.Column('witness_fingerprint',sa.String(64),nullable=False),sa.Column('state',sa.String(24),nullable=False),sa.Column('created_by',sa.String(64),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.Column('supplier_fact_unchanged',sa.Boolean(),nullable=False,server_default=sa.true()))
    op.create_table('journey_recovery_witness_cosignature',
      sa.Column('witness_cosignature_id',sa.String(64),primary_key=True),sa.Column('merkle_checkpoint_id',sa.String(64),nullable=False),sa.Column('external_trust_witness_id',sa.String(64),nullable=False),sa.Column('checkpoint_hash',sa.String(64),nullable=False),sa.Column('signature',sa.String(128),nullable=False),sa.Column('evidence_reference',sa.String(256),nullable=False),sa.Column('verification_state',sa.String(24),nullable=False),sa.Column('signed_at',sa.DateTime(timezone=True),nullable=False),sa.Column('supplier_fact_unchanged',sa.Boolean(),nullable=False,server_default=sa.true()))
    op.create_table('journey_recovery_region_trust_replica',
      sa.Column('region_trust_replica_id',sa.String(64),primary_key=True),sa.Column('environment',sa.String(16),nullable=False),sa.Column('region_key',sa.String(64),nullable=False),sa.Column('credential_id',sa.String(128),nullable=False),sa.Column('credential_status',sa.String(24),nullable=False),sa.Column('status_version',sa.Integer(),nullable=False),sa.Column('checkpoint_hash',sa.String(64),nullable=False),sa.Column('tree_size',sa.Integer(),nullable=False),sa.Column('replica_digest',sa.String(64),nullable=False),sa.Column('observed_at',sa.DateTime(timezone=True),nullable=False),sa.Column('expires_at',sa.DateTime(timezone=True),nullable=False),sa.Column('evidence_reference',sa.String(256),nullable=False),sa.Column('published_by',sa.String(64),nullable=False),sa.Column('supplier_fact_unchanged',sa.Boolean(),nullable=False,server_default=sa.true()))
    op.create_table('journey_recovery_multi_region_admission_policy',
      sa.Column('multi_region_admission_policy_id',sa.String(64),primary_key=True),sa.Column('policy_key',sa.String(128),nullable=False),sa.Column('version_no',sa.Integer(),nullable=False),sa.Column('environment',sa.String(16),nullable=False),sa.Column('required_regions_json',sa.JSON(),nullable=False),sa.Column('minimum_witness_cosignatures',sa.Integer(),nullable=False),sa.Column('max_replica_age_seconds',sa.Integer(),nullable=False),sa.Column('split_view_action',sa.String(32),nullable=False),sa.Column('state',sa.String(24),nullable=False),sa.Column('created_by',sa.String(64),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.Column('supplier_fact_unchanged',sa.Boolean(),nullable=False,server_default=sa.true()))
    op.create_table('journey_recovery_multi_region_admission_decision',
      sa.Column('multi_region_admission_decision_id',sa.String(64),primary_key=True),sa.Column('runtime_identity_id',sa.String(64),nullable=False),sa.Column('credential_id',sa.String(128),nullable=False),sa.Column('environment',sa.String(16),nullable=False),sa.Column('cluster_id',sa.String(128),nullable=False),sa.Column('policy_id',sa.String(64),nullable=False),sa.Column('decision',sa.String(32),nullable=False),sa.Column('consensus_state',sa.String(32),nullable=False),sa.Column('split_view_detected',sa.Boolean(),nullable=False),sa.Column('region_states_json',sa.JSON(),nullable=False),sa.Column('checkpoint_hash',sa.String(64)),sa.Column('witness_count',sa.Integer(),nullable=False),sa.Column('reason_codes_json',sa.JSON(),nullable=False),sa.Column('decided_by',sa.String(64),nullable=False),sa.Column('decided_at',sa.DateTime(timezone=True),nullable=False),sa.Column('supplier_fact_unchanged',sa.Boolean(),nullable=False,server_default=sa.true()))
    for t in ['journey_recovery_merkle_checkpoint','journey_recovery_witness_cosignature','journey_recovery_region_trust_replica','journey_recovery_multi_region_admission_decision']:_immutable(t)

def downgrade():
    for t in ['journey_recovery_multi_region_admission_decision','journey_recovery_multi_region_admission_policy','journey_recovery_region_trust_replica','journey_recovery_witness_cosignature','journey_recovery_external_trust_witness','journey_recovery_merkle_checkpoint']:
        op.drop_table(t)
