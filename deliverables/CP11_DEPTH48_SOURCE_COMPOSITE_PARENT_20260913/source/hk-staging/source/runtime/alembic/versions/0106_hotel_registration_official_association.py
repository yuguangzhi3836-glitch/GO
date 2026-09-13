"""Replace hotel claim terminology with registration + official association.

GO pages exist independently of hotel registration. Registration establishes the
supplier identity and, after evidence review, an official association to the
canonical GO Hotel ID. Hotel-submitted profile data is an evidence source, not
ownership of the GO page or authority to overwrite GO truth without provenance.
"""
from alembic import op
import sqlalchemy as sa

revision='0106_449aeedcd91d'
down_revision='0105_hotel_autopage_factory'
branch_labels=None
depends_on=None


def upgrade():
    # Preserve 0105 data while replacing the product/domain vocabulary.
    with op.batch_alter_table('hotel_canonical_profile') as b:
        b.alter_column('claim_state', new_column_name='association_state', existing_type=sa.String(32), existing_nullable=False)
    with op.batch_alter_table('hotel_auto_page_version') as b:
        b.alter_column('claim_state', new_column_name='association_state', existing_type=sa.String(32), existing_nullable=False)

    op.rename_table('hotel_page_claim','hotel_registration_association')
    with op.batch_alter_table('hotel_registration_association') as b:
        b.alter_column('hotel_page_claim_id', new_column_name='hotel_registration_association_id', existing_type=sa.String(64), existing_nullable=False)

    # Normalize any records created by 0105 terminology.
    bind=op.get_bind()
    bind.execute(sa.text("UPDATE hotel_canonical_profile SET association_state = CASE association_state WHEN 'UNCLAIMED' THEN 'NOT_REGISTERED' WHEN 'CLAIM_PENDING' THEN 'REGISTRATION_PENDING' WHEN 'CLAIMED' THEN 'OFFICIAL_ASSOCIATED' ELSE association_state END"))
    bind.execute(sa.text("UPDATE hotel_auto_page_version SET association_state = CASE association_state WHEN 'UNCLAIMED' THEN 'NOT_REGISTERED' WHEN 'CLAIM_PENDING' THEN 'REGISTRATION_PENDING' WHEN 'CLAIMED' THEN 'OFFICIAL_ASSOCIATED' ELSE association_state END"))


def downgrade():
    bind=op.get_bind()
    bind.execute(sa.text("UPDATE hotel_canonical_profile SET association_state = CASE association_state WHEN 'NOT_REGISTERED' THEN 'UNCLAIMED' WHEN 'REGISTRATION_PENDING' THEN 'CLAIM_PENDING' WHEN 'OFFICIAL_ASSOCIATED' THEN 'CLAIMED' ELSE association_state END"))
    bind.execute(sa.text("UPDATE hotel_auto_page_version SET association_state = CASE association_state WHEN 'NOT_REGISTERED' THEN 'UNCLAIMED' WHEN 'REGISTRATION_PENDING' THEN 'CLAIM_PENDING' WHEN 'OFFICIAL_ASSOCIATED' THEN 'CLAIMED' ELSE association_state END"))
    with op.batch_alter_table('hotel_registration_association') as b:
        b.alter_column('hotel_registration_association_id', new_column_name='hotel_page_claim_id', existing_type=sa.String(64), existing_nullable=False)
    op.rename_table('hotel_registration_association','hotel_page_claim')
    with op.batch_alter_table('hotel_auto_page_version') as b:
        b.alter_column('association_state', new_column_name='claim_state', existing_type=sa.String(32), existing_nullable=False)
    with op.batch_alter_table('hotel_canonical_profile') as b:
        b.alter_column('association_state', new_column_name='claim_state', existing_type=sa.String(32), existing_nullable=False)
