"""Private applicant documents: business licence, operation proof, signed contract.

Two scopes in one table (frozen decision CHANGE 2), expressed with partial unique
indexes rather than a polymorphic scope framework:

  * entity level     -> ``onboarding_case_id IS NULL``
  * onboarding level -> ``onboarding_case_id`` = the case it belongs to

Each scope keeps at most one *current* revision per document type, while the full
revision history is retained (``status='SUPERSEDED'`` rows stay).

These rows are private evidence. They are never written into the public hotel
media cache and are reachable only by the owning applicant and an authorised
onboarding reviewer.
"""
from alembic import op
import sqlalchemy as sa

revision = '0147_legal_entity_document'
down_revision = '0146_legal_entity'
branch_labels = None
depends_on = None

TABLE = 'legal_entity_document'
ENTITY_CURRENT = "onboarding_case_id IS NULL AND status <> 'SUPERSEDED'"
CASE_CURRENT = "onboarding_case_id IS NOT NULL AND status <> 'SUPERSEDED'"


def upgrade():
    op.create_table(
        TABLE,
        sa.Column('document_id', sa.String(64), primary_key=True),
        sa.Column('legal_entity_id', sa.String(64), nullable=False),
        sa.Column('onboarding_case_id', sa.String(64)),
        sa.Column('document_type', sa.String(40), nullable=False),
        sa.Column('storage_key', sa.String(255), nullable=False),
        sa.Column('original_filename', sa.String(255), nullable=False),
        sa.Column('mime_type', sa.String(64), nullable=False),
        sa.Column('size_bytes', sa.Integer(), nullable=False),
        sa.Column('sha256', sa.String(64), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(24), nullable=False),
        sa.Column('uploaded_by', sa.String(64), nullable=False),
        sa.Column('uploaded_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('replaced_at', sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(['legal_entity_id'], ['legal_entity.legal_entity_id'],
                                name='fk_led_legal_entity'),
        sa.ForeignKeyConstraint(['onboarding_case_id'], ['commercial_case.commercial_case_id'],
                                name='fk_led_onboarding_case'),
        sa.CheckConstraint(
            "document_type IN ('BUSINESS_LICENSE','LEGAL_REP_ID','AGENT_ID','STOREFRONT_PHOTO',"
            "'HOTEL_OPERATION_PROOF','FRANCHISE_OR_MANAGEMENT_CONTRACT','SIGNED_CONTRACT')",
            name='ck_legal_entity_document_type'),
        sa.CheckConstraint(
            "status IN ('UPLOADED','ACCEPTED','REJECTED','SUPERSEDED')",
            name='ck_legal_entity_document_status'),
        sa.CheckConstraint('size_bytes > 0 AND revision >= 1', name='ck_legal_entity_document_bounds'),
    )
    op.create_index('ix_legal_entity_document_legal_entity_id', TABLE, ['legal_entity_id'])
    op.create_index('ix_legal_entity_document_onboarding_case_id', TABLE, ['onboarding_case_id'])
    op.create_index('ix_legal_entity_document_document_type', TABLE, ['document_type'])
    op.create_index('ix_legal_entity_document_sha256', TABLE, ['sha256'])
    op.create_index('ix_legal_entity_document_status', TABLE, ['status'])
    # at most one current revision per (scope, type)
    op.create_index('uq_led_entity_current', TABLE, ['legal_entity_id', 'document_type'],
                    unique=True, postgresql_where=sa.text(ENTITY_CURRENT), sqlite_where=sa.text(ENTITY_CURRENT))
    op.create_index('uq_led_case_current', TABLE, ['legal_entity_id', 'onboarding_case_id', 'document_type'],
                    unique=True, postgresql_where=sa.text(CASE_CURRENT), sqlite_where=sa.text(CASE_CURRENT))
    # revision numbers are unique inside a scope
    op.create_index('uq_led_entity_revision', TABLE, ['legal_entity_id', 'document_type', 'revision'],
                    unique=True, postgresql_where=sa.text('onboarding_case_id IS NULL'),
                    sqlite_where=sa.text('onboarding_case_id IS NULL'))
    op.create_index('uq_led_case_revision', TABLE,
                    ['legal_entity_id', 'onboarding_case_id', 'document_type', 'revision'],
                    unique=True, postgresql_where=sa.text('onboarding_case_id IS NOT NULL'),
                    sqlite_where=sa.text('onboarding_case_id IS NOT NULL'))


def downgrade():
    # File bytes live on the volume, not in the database: dropping the table
    # without first exporting the document manifest would strand them.
    if op.get_bind().scalar(sa.text('SELECT count(*) FROM ' + TABLE)):
        raise RuntimeError('LEGAL_ENTITY_DOCUMENT_DATA_PRESENT_EXPORT_MANIFEST_FOR_DOWNGRADE')
    for index in ('uq_led_case_revision', 'uq_led_entity_revision', 'uq_led_case_current',
                  'uq_led_entity_current', 'ix_legal_entity_document_status',
                  'ix_legal_entity_document_sha256', 'ix_legal_entity_document_document_type',
                  'ix_legal_entity_document_onboarding_case_id', 'ix_legal_entity_document_legal_entity_id'):
        op.drop_index(index, table_name=TABLE)
    op.drop_table(TABLE)
