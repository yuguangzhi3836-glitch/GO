"""GO Personal Travel Vault + Universal Import master baseline.

Adds user-controlled profile portability, import provenance, traveler permissions,
sensitive profile facts, purpose-bound consent and data-release auditing.
This migration does not alter supplier/payment/order truth or authorize third-party
credential capture, simulated login, 2FA bypass or private-account scraping.
"""
from alembic import op
import sqlalchemy as sa

revision='0109_bf96588075fe'
down_revision='0108_hotel_go_direct_semantics'
branch_labels=None
depends_on=None

def _immutable(table, code):
    bind=op.get_bind(); dialect=bind.dialect.name
    if dialect=='sqlite':
        op.execute(f"CREATE TRIGGER {table}_deny_update BEFORE UPDATE ON {table} BEGIN SELECT RAISE(ABORT, '{code}'); END")
        op.execute(f"CREATE TRIGGER {table}_deny_delete BEFORE DELETE ON {table} BEGIN SELECT RAISE(ABORT, '{code}'); END")
    elif dialect=='postgresql':
        fn=f"deny_{table}_mutation"
        op.execute(f"CREATE OR REPLACE FUNCTION {fn}() RETURNS trigger AS $$ BEGIN RAISE EXCEPTION '{code}'; END; $$ LANGUAGE plpgsql")
        op.execute(f"CREATE TRIGGER {table}_deny_update BEFORE UPDATE ON {table} FOR EACH ROW EXECUTE FUNCTION {fn}()")
        op.execute(f"CREATE TRIGGER {table}_deny_delete BEFORE DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION {fn}()")

def _drop_immutable(table):
    bind=op.get_bind(); dialect=bind.dialect.name
    if dialect=='sqlite':
        op.execute(f"DROP TRIGGER IF EXISTS {table}_deny_update"); op.execute(f"DROP TRIGGER IF EXISTS {table}_deny_delete")
    elif dialect=='postgresql':
        fn=f"deny_{table}_mutation"
        op.execute(f"DROP TRIGGER IF EXISTS {table}_deny_update ON {table}"); op.execute(f"DROP TRIGGER IF EXISTS {table}_deny_delete ON {table}"); op.execute(f"DROP FUNCTION IF EXISTS {fn}()")

def upgrade():
    with op.batch_alter_table('consumer_traveler') as b:
        b.add_column(sa.Column('relationship_type',sa.String(32),nullable=False,server_default='SELF'))
        b.add_column(sa.Column('booking_permission',sa.Boolean(),nullable=False,server_default=sa.true()))
        b.add_column(sa.Column('guardian_traveler_id',sa.String(64),nullable=True))
        b.add_column(sa.Column('guardian_consent_status',sa.String(24),nullable=True))
        b.add_column(sa.Column('source_type',sa.String(48),nullable=False,server_default='MANUAL'))
        b.create_index('ix_consumer_traveler_guardian_traveler_id',['guardian_traveler_id'],unique=False)

    op.create_table('profile_import_job',
        sa.Column('import_job_id',sa.String(64),primary_key=True),sa.Column('user_id',sa.String(64),nullable=False),
        sa.Column('source_type',sa.String(48),nullable=False),sa.Column('source_provider',sa.String(96)),sa.Column('source_reference',sa.Text()),
        sa.Column('source_fingerprint',sa.String(128),nullable=False),sa.Column('content_hash',sa.String(64),nullable=False),
        sa.Column('status',sa.String(32),nullable=False),sa.Column('consent_id',sa.String(64)),
        sa.Column('item_count',sa.Integer(),nullable=False,server_default='0'),sa.Column('accepted_count',sa.Integer(),nullable=False,server_default='0'),
        sa.Column('rejected_count',sa.Integer(),nullable=False,server_default='0'),sa.Column('conflict_count',sa.Integer(),nullable=False,server_default='0'),
        sa.Column('metadata_json',sa.JSON(),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False),sa.Column('completed_at',sa.DateTime(timezone=True)))
    for name,cols in [('ix_profile_import_job_user_id',['user_id']),('ix_profile_import_job_source_type',['source_type']),('ix_profile_import_job_source_provider',['source_provider']),('ix_profile_import_job_source_fingerprint',['source_fingerprint']),('ix_profile_import_job_content_hash',['content_hash']),('ix_profile_import_job_status',['status']),('ix_profile_import_job_consent_id',['consent_id']),('ix_profile_import_job_created_at',['created_at']),('ix_profile_import_user_source',['user_id','source_fingerprint'])]: op.create_index(name,'profile_import_job',cols,unique=False)

    op.create_table('profile_import_item',
        sa.Column('import_item_id',sa.String(64),primary_key=True),sa.Column('import_job_id',sa.String(64),nullable=False),sa.Column('user_id',sa.String(64),nullable=False),
        sa.Column('entity_type',sa.String(32),nullable=False),sa.Column('traveler_ref',sa.String(128)),sa.Column('field_type',sa.String(64)),
        sa.Column('candidate_value_ciphertext',sa.Text()),sa.Column('normalized_value_hash',sa.String(64)),sa.Column('preview_masked',sa.Text()),
        sa.Column('sensitive',sa.Boolean(),nullable=False,server_default=sa.false()),sa.Column('confidence_bps',sa.Integer(),nullable=False,server_default='0'),
        sa.Column('source_payload_json',sa.JSON(),nullable=False),sa.Column('status',sa.String(32),nullable=False),sa.Column('resolution_traveler_id',sa.String(64)),
        sa.Column('conflict_fact_id',sa.String(64)),sa.Column('review_action',sa.String(32)),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False))
    for name,cols in [('ix_profile_import_item_import_job_id',['import_job_id']),('ix_profile_import_item_user_id',['user_id']),('ix_profile_import_item_entity_type',['entity_type']),('ix_profile_import_item_traveler_ref',['traveler_ref']),('ix_profile_import_item_field_type',['field_type']),('ix_profile_import_item_normalized_value_hash',['normalized_value_hash']),('ix_profile_import_item_status',['status']),('ix_profile_import_item_resolution_traveler_id',['resolution_traveler_id']),('ix_profile_import_item_conflict_fact_id',['conflict_fact_id']),('ix_profile_import_item_created_at',['created_at'])]: op.create_index(name,'profile_import_item',cols,unique=False)

    op.create_table('profile_fact',
        sa.Column('fact_id',sa.String(64),primary_key=True),sa.Column('user_id',sa.String(64),nullable=False),sa.Column('traveler_id',sa.String(64),nullable=False),
        sa.Column('field_type',sa.String(64),nullable=False),sa.Column('value_ciphertext',sa.Text(),nullable=False),sa.Column('normalized_value_hash',sa.String(64),nullable=False),
        sa.Column('sensitive',sa.Boolean(),nullable=False,server_default=sa.false()),sa.Column('source_type',sa.String(48),nullable=False),sa.Column('source_provider',sa.String(96)),
        sa.Column('source_reference',sa.Text()),sa.Column('source_fingerprint',sa.String(128)),sa.Column('confidence_bps',sa.Integer(),nullable=False,server_default='0'),
        sa.Column('user_confirmed',sa.Boolean(),nullable=False,server_default=sa.false()),sa.Column('trust_level',sa.String(32),nullable=False),
        sa.Column('verification_status',sa.String(32),nullable=False),sa.Column('verification_method',sa.String(64)),sa.Column('valid_from',sa.String(32)),sa.Column('valid_until',sa.String(32)),
        sa.Column('superseded_by',sa.String(64)),sa.Column('status',sa.String(24),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False))
    for name,cols in [('ix_profile_fact_user_id',['user_id']),('ix_profile_fact_traveler_id',['traveler_id']),('ix_profile_fact_field_type',['field_type']),('ix_profile_fact_normalized_value_hash',['normalized_value_hash']),('ix_profile_fact_source_type',['source_type']),('ix_profile_fact_source_provider',['source_provider']),('ix_profile_fact_source_fingerprint',['source_fingerprint']),('ix_profile_fact_trust_level',['trust_level']),('ix_profile_fact_verification_status',['verification_status']),('ix_profile_fact_valid_until',['valid_until']),('ix_profile_fact_superseded_by',['superseded_by']),('ix_profile_fact_status',['status']),('ix_profile_fact_created_at',['created_at']),('ix_profile_fact_traveler_field_status',['traveler_id','field_type','status'])]: op.create_index(name,'profile_fact',cols,unique=False)

    op.create_table('profile_consent',
        sa.Column('consent_id',sa.String(64),primary_key=True),sa.Column('user_id',sa.String(64),nullable=False),sa.Column('traveler_id',sa.String(64)),
        sa.Column('consent_type',sa.String(48),nullable=False),sa.Column('purpose',sa.String(128),nullable=False),sa.Column('scope_json',sa.JSON(),nullable=False),sa.Column('status',sa.String(24),nullable=False),
        sa.Column('granted_at',sa.DateTime(timezone=True),nullable=False),sa.Column('expires_at',sa.DateTime(timezone=True)),sa.Column('revoked_at',sa.DateTime(timezone=True)))
    for name,cols in [('ix_profile_consent_user_id',['user_id']),('ix_profile_consent_traveler_id',['traveler_id']),('ix_profile_consent_consent_type',['consent_type']),('ix_profile_consent_status',['status']),('ix_profile_consent_expires_at',['expires_at'])]: op.create_index(name,'profile_consent',cols,unique=False)

    op.create_table('profile_traveler_permission',
        sa.Column('permission_id',sa.String(64),primary_key=True),sa.Column('user_id',sa.String(64),nullable=False),sa.Column('traveler_id',sa.String(64),nullable=False),
        sa.Column('permission_type',sa.String(32),nullable=False),sa.Column('allowed',sa.Boolean(),nullable=False),sa.Column('source',sa.String(48),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False))
    for name,cols in [('ix_profile_traveler_permission_user_id',['user_id']),('ix_profile_traveler_permission_traveler_id',['traveler_id']),('ix_profile_traveler_permission_permission_type',['permission_type'])]: op.create_index(name,'profile_traveler_permission',cols,unique=False)
    op.create_index('uq_profile_traveler_permission_scope','profile_traveler_permission',['user_id','traveler_id','permission_type'],unique=True)

    op.create_table('profile_data_release_audit',
        sa.Column('release_id',sa.String(64),primary_key=True),sa.Column('user_id',sa.String(64),nullable=False),sa.Column('traveler_id',sa.String(64),nullable=False),
        sa.Column('requester_type',sa.String(32),nullable=False),sa.Column('requester_id',sa.String(96)),sa.Column('vertical',sa.String(32),nullable=False),sa.Column('purpose',sa.String(128),nullable=False),sa.Column('destination',sa.String(128),nullable=False),sa.Column('booking_id',sa.String(64)),
        sa.Column('requested_fields_json',sa.JSON(),nullable=False),sa.Column('released_fields_json',sa.JSON(),nullable=False),sa.Column('consent_id',sa.String(64)),sa.Column('decision',sa.String(24),nullable=False),sa.Column('reason_code',sa.String(64),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False))
    for name,cols in [('ix_profile_data_release_audit_user_id',['user_id']),('ix_profile_data_release_audit_traveler_id',['traveler_id']),('ix_profile_data_release_audit_requester_type',['requester_type']),('ix_profile_data_release_audit_requester_id',['requester_id']),('ix_profile_data_release_audit_vertical',['vertical']),('ix_profile_data_release_audit_destination',['destination']),('ix_profile_data_release_audit_booking_id',['booking_id']),('ix_profile_data_release_audit_consent_id',['consent_id']),('ix_profile_data_release_audit_decision',['decision']),('ix_profile_data_release_audit_created_at',['created_at']),('ix_profile_release_user_created',['user_id','created_at'])]: op.create_index(name,'profile_data_release_audit',cols,unique=False)

    op.create_table('profile_access_audit',
        sa.Column('access_id',sa.String(64),primary_key=True),sa.Column('user_id',sa.String(64),nullable=False),sa.Column('traveler_id',sa.String(64)),sa.Column('actor_id',sa.String(64),nullable=False),sa.Column('actor_type',sa.String(32),nullable=False),sa.Column('action',sa.String(48),nullable=False),sa.Column('purpose',sa.String(128)),sa.Column('fields_json',sa.JSON(),nullable=False),sa.Column('metadata_json',sa.JSON(),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False))
    for name,cols in [('ix_profile_access_audit_user_id',['user_id']),('ix_profile_access_audit_traveler_id',['traveler_id']),('ix_profile_access_audit_actor_id',['actor_id']),('ix_profile_access_audit_action',['action']),('ix_profile_access_audit_created_at',['created_at'])]: op.create_index(name,'profile_access_audit',cols,unique=False)
    _immutable('profile_data_release_audit','IMMUTABLE_PROFILE_DATA_RELEASE_AUDIT')
    _immutable('profile_access_audit','IMMUTABLE_PROFILE_ACCESS_AUDIT')

def downgrade():
    _drop_immutable('profile_access_audit')
    _drop_immutable('profile_data_release_audit')
    for t in ['profile_access_audit','profile_data_release_audit','profile_traveler_permission','profile_consent','profile_fact','profile_import_item','profile_import_job']:
        op.drop_table(t)
    with op.batch_alter_table('consumer_traveler') as b:
        b.drop_index('ix_consumer_traveler_guardian_traveler_id')
        for c in ['source_type','guardian_consent_status','guardian_traveler_id','booking_permission','relationship_type']:
            b.drop_column(c)
