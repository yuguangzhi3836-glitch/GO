"""Legal entity: the provable business subject behind one supplier tenant.

One supplier tenant owns exactly one legal entity (frozen decision D-02). The
unified social credit code is the subject's platform-wide identity and therefore
unique. Company *name* is deliberately NOT unique: distinct legal persons share
names legitimately.

Additive only: no existing table is touched, so this is safe to apply before the
code that writes it ships.
"""
from alembic import op
import sqlalchemy as sa

revision = '0146_legal_entity'
down_revision = '0145_source_latest_index'
branch_labels = None
depends_on = None

TABLE = 'legal_entity'


def upgrade():
    op.create_table(
        TABLE,
        sa.Column('legal_entity_id', sa.String(64), primary_key=True),
        sa.Column('supplier_id', sa.String(64), nullable=False),
        sa.Column('legal_name', sa.String(200), nullable=False),
        sa.Column('unified_social_credit_code', sa.String(18), nullable=False),
        sa.Column('legal_representative_name', sa.String(80), nullable=False),
        sa.Column('registered_address', sa.String(300), nullable=False),
        sa.Column('license_valid_from', sa.Date()),
        sa.Column('license_valid_until', sa.Date()),
        sa.Column('license_long_term', sa.Boolean(), nullable=False),
        sa.Column('verification_state', sa.String(24), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "verification_state IN ('UNVERIFIED','PENDING','VERIFIED','REJECTED')",
            name='ck_legal_entity_verification_state'),
        sa.CheckConstraint(
            'license_long_term OR license_valid_from IS NULL OR license_valid_until IS NULL'
            ' OR license_valid_until >= license_valid_from',
            name='ck_legal_entity_license_window'),
    )
    op.create_index('ix_legal_entity_supplier_id', TABLE, ['supplier_id'], unique=True)
    op.create_index('ix_legal_entity_unified_social_credit_code', TABLE, ['unified_social_credit_code'], unique=True)
    op.create_index('ix_legal_entity_verification_state', TABLE, ['verification_state'])


def downgrade():
    # A legal entity is referenced by signed contracts and append-only audit
    # events once onboarding completes. Refuse a silent drop that would orphan
    # that evidence; the operator must take a backup first.
    if op.get_bind().scalar(sa.text('SELECT count(*) FROM ' + TABLE)):
        raise RuntimeError('LEGAL_ENTITY_DATA_PRESENT_RESTORE_BACKUP_FOR_DOWNGRADE')
    op.drop_index('ix_legal_entity_verification_state', table_name=TABLE)
    op.drop_index('ix_legal_entity_unified_social_credit_code', table_name=TABLE)
    op.drop_index('ix_legal_entity_supplier_id', table_name=TABLE)
    op.drop_table(TABLE)
