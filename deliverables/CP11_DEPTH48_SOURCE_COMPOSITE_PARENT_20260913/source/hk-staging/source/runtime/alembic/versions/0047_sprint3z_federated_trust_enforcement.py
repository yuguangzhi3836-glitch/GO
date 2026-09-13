"""Sprint 3Z certificate transparency, status distribution and federated trust enforcement.

Revision ID: 0047_sprint3z
Revises: 0046_sprint3y
"""
from alembic import op
import sqlalchemy as sa

revision='0047_sprint3z'
down_revision='0046_sprint3y'
branch_labels=None
depends_on=None

def _immutable(table):
    bind=op.get_bind();dialect=bind.dialect.name
    if dialect=='sqlite':
        op.execute(f"CREATE TRIGGER {table}_deny_update BEFORE UPDATE ON {table} BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_TRUST_DISTRIBUTION_EVIDENCE'); END;")
        op.execute(f"CREATE TRIGGER {table}_deny_delete BEFORE DELETE ON {table} BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_TRUST_DISTRIBUTION_EVIDENCE'); END;")
    elif dialect=='postgresql':
        op.execute("""CREATE OR REPLACE FUNCTION deny_trust_distribution_evidence_mutation() RETURNS trigger AS $$ BEGIN RAISE EXCEPTION 'IMMUTABLE_TRUST_DISTRIBUTION_EVIDENCE'; END; $$ LANGUAGE plpgsql;""")
        op.execute(f"CREATE TRIGGER {table}_deny_update BEFORE UPDATE ON {table} FOR EACH ROW EXECUTE FUNCTION deny_trust_distribution_evidence_mutation();")
        op.execute(f"CREATE TRIGGER {table}_deny_delete BEFORE DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION deny_trust_distribution_evidence_mutation();")

def upgrade():
    op.create_table('journey_recovery_trust_federation',
        sa.Column('trust_federation_id',sa.String(64),primary_key=True),sa.Column('federation_key',sa.String(128),nullable=False,unique=True),sa.Column('environment',sa.String(16),nullable=False),sa.Column('cluster_scope',sa.String(128),nullable=False),sa.Column('hardware_trust_root_id',sa.String(64),nullable=False),sa.Column('state',sa.String(24),nullable=False),sa.Column('peer_fingerprint',sa.String(64),nullable=False),sa.Column('policy_version',sa.Integer(),nullable=False),sa.Column('last_synchronized_at',sa.DateTime(timezone=True)),sa.Column('created_by',sa.String(64),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False),sa.Column('supplier_fact_unchanged',sa.Boolean(),nullable=False,server_default=sa.true()))
    op.create_table('journey_recovery_credential_status_distribution',
        sa.Column('credential_status_distribution_id',sa.String(64),primary_key=True),sa.Column('credential_id',sa.String(128),nullable=False),sa.Column('environment',sa.String(16),nullable=False),sa.Column('status',sa.String(24),nullable=False),sa.Column('status_version',sa.Integer(),nullable=False),sa.Column('this_update_at',sa.DateTime(timezone=True),nullable=False),sa.Column('next_update_at',sa.DateTime(timezone=True),nullable=False),sa.Column('issuer_id',sa.String(64),nullable=False),sa.Column('root_id',sa.String(64),nullable=False),sa.Column('status_hash',sa.String(64),nullable=False),sa.Column('publication_state',sa.String(24),nullable=False),sa.Column('evidence_reference',sa.String(256),nullable=False),sa.Column('published_by',sa.String(64),nullable=False),sa.Column('published_at',sa.DateTime(timezone=True),nullable=False),sa.Column('supplier_fact_unchanged',sa.Boolean(),nullable=False,server_default=sa.true()))
    op.create_table('journey_recovery_trust_transparency_log',
        sa.Column('transparency_log_id',sa.String(64),primary_key=True),sa.Column('sequence_no',sa.Integer(),nullable=False,unique=True),sa.Column('event_type',sa.String(48),nullable=False),sa.Column('subject_type',sa.String(32),nullable=False),sa.Column('subject_id',sa.String(128),nullable=False),sa.Column('environment',sa.String(16),nullable=False),sa.Column('payload_hash',sa.String(64),nullable=False),sa.Column('previous_hash',sa.String(64)),sa.Column('entry_hash',sa.String(64),nullable=False),sa.Column('evidence_reference',sa.String(256),nullable=False),sa.Column('created_by',sa.String(64),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.Column('supplier_fact_unchanged',sa.Boolean(),nullable=False,server_default=sa.true()))
    op.create_table('journey_recovery_issuer_compromise',
        sa.Column('issuer_compromise_id',sa.String(64),primary_key=True),sa.Column('credential_issuer_id',sa.String(64),nullable=False),sa.Column('environment',sa.String(16),nullable=False),sa.Column('severity',sa.String(16),nullable=False),sa.Column('state',sa.String(24),nullable=False),sa.Column('affected_credential_ids_json',sa.JSON(),nullable=False),sa.Column('fanout_count',sa.Integer(),nullable=False),sa.Column('evidence_reference',sa.String(256),nullable=False),sa.Column('opened_by',sa.String(64),nullable=False),sa.Column('opened_at',sa.DateTime(timezone=True),nullable=False),sa.Column('contained_at',sa.DateTime(timezone=True)),sa.Column('supplier_fact_unchanged',sa.Boolean(),nullable=False,server_default=sa.true()))
    op.create_table('journey_recovery_federated_admission_policy',
        sa.Column('federated_admission_policy_id',sa.String(64),primary_key=True),sa.Column('policy_key',sa.String(128),nullable=False),sa.Column('version_no',sa.Integer(),nullable=False),sa.Column('environment',sa.String(16),nullable=False),sa.Column('cluster_scope',sa.String(128),nullable=False),sa.Column('state',sa.String(24),nullable=False),sa.Column('min_status_freshness_seconds',sa.Integer(),nullable=False),sa.Column('allowed_federation_ids_json',sa.JSON(),nullable=False),sa.Column('require_transparency_log',sa.Boolean(),nullable=False),sa.Column('policy_json',sa.JSON(),nullable=False),sa.Column('created_by',sa.String(64),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.Column('supplier_fact_unchanged',sa.Boolean(),nullable=False,server_default=sa.true()))
    op.create_table('journey_recovery_federated_admission_decision',
        sa.Column('federated_admission_decision_id',sa.String(64),primary_key=True),sa.Column('runtime_identity_id',sa.String(64),nullable=False),sa.Column('credential_id',sa.String(128),nullable=False),sa.Column('environment',sa.String(16),nullable=False),sa.Column('cluster_id',sa.String(128),nullable=False),sa.Column('policy_id',sa.String(64),nullable=False),sa.Column('decision',sa.String(24),nullable=False),sa.Column('reason_codes_json',sa.JSON(),nullable=False),sa.Column('status_distribution_id',sa.String(64)),sa.Column('transparency_log_id',sa.String(64)),sa.Column('decided_by',sa.String(64),nullable=False),sa.Column('decided_at',sa.DateTime(timezone=True),nullable=False),sa.Column('supplier_fact_unchanged',sa.Boolean(),nullable=False,server_default=sa.true()))
    for t in ['journey_recovery_credential_status_distribution','journey_recovery_trust_transparency_log','journey_recovery_federated_admission_decision']:_immutable(t)

def downgrade():
    for t in ['journey_recovery_federated_admission_decision','journey_recovery_federated_admission_policy','journey_recovery_issuer_compromise','journey_recovery_trust_transparency_log','journey_recovery_credential_status_distribution','journey_recovery_trust_federation']:
        op.drop_table(t)
