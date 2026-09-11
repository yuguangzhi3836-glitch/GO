"""Replace official-association vocabulary with official-direct lifecycle.

Registration verifies the hotel/supplier identity and binds it to the specified
Canonical Hotel ID. Approval yields DIRECT_VERIFIED, not DIRECT_LIVE. Real
GO Direct transaction availability remains an external supplier/route fact.
"""
from alembic import op
import sqlalchemy as sa

revision='0107_166151c9cc6e'
down_revision='0106_449aeedcd91d'
branch_labels=None
depends_on=None

def upgrade():
    with op.batch_alter_table('hotel_canonical_profile') as b:
        b.alter_column('association_state', new_column_name='direct_state', existing_type=sa.String(32), existing_nullable=False)
    with op.batch_alter_table('hotel_auto_page_version') as b:
        b.alter_column('association_state', new_column_name='direct_state', existing_type=sa.String(32), existing_nullable=False)
    op.rename_table('hotel_registration_association','hotel_registration_official_direct')
    with op.batch_alter_table('hotel_registration_official_direct') as b:
        b.alter_column('hotel_registration_association_id', new_column_name='hotel_registration_direct_id', existing_type=sa.String(64), existing_nullable=False)
    bind=op.get_bind()
    bind.execute(sa.text("UPDATE hotel_canonical_profile SET direct_state = CASE direct_state WHEN 'OFFICIAL_ASSOCIATED' THEN 'DIRECT_VERIFIED' ELSE direct_state END"))
    bind.execute(sa.text("UPDATE hotel_auto_page_version SET direct_state = CASE direct_state WHEN 'OFFICIAL_ASSOCIATED' THEN 'DIRECT_VERIFIED' ELSE direct_state END"))

def downgrade():
    bind=op.get_bind()
    bind.execute(sa.text("UPDATE hotel_canonical_profile SET direct_state = CASE direct_state WHEN 'DIRECT_VERIFIED' THEN 'OFFICIAL_ASSOCIATED' WHEN 'DIRECT_LIVE' THEN 'OFFICIAL_ASSOCIATED' ELSE direct_state END"))
    bind.execute(sa.text("UPDATE hotel_auto_page_version SET direct_state = CASE direct_state WHEN 'DIRECT_VERIFIED' THEN 'OFFICIAL_ASSOCIATED' WHEN 'DIRECT_LIVE' THEN 'OFFICIAL_ASSOCIATED' ELSE direct_state END"))
    with op.batch_alter_table('hotel_registration_official_direct') as b:
        b.alter_column('hotel_registration_direct_id', new_column_name='hotel_registration_association_id', existing_type=sa.String(64), existing_nullable=False)
    op.rename_table('hotel_registration_official_direct','hotel_registration_association')
    with op.batch_alter_table('hotel_auto_page_version') as b:
        b.alter_column('direct_state', new_column_name='association_state', existing_type=sa.String(32), existing_nullable=False)
    with op.batch_alter_table('hotel_canonical_profile') as b:
        b.alter_column('direct_state', new_column_name='association_state', existing_type=sa.String(32), existing_nullable=False)
