"""Make GO Direct the single product vocabulary for hotel registration lifecycle.

This migration changes only the Hotel AutoPage/registration product semantics.
The older internal `official_direct` offer/source truth remains a routing fact and is
not redefined by this migration. Approval yields GO_DIRECT_VERIFIED, not
GO_DIRECT_LIVE; real transaction availability still requires supplier/runtime proof.
"""
from alembic import op
import sqlalchemy as sa

revision='0108_hotel_go_direct_semantics'
down_revision='0107_166151c9cc6e'
branch_labels=None
depends_on=None

def upgrade():
    with op.batch_alter_table('hotel_canonical_profile') as b:
        b.alter_column('direct_state', new_column_name='go_direct_state', existing_type=sa.String(32), existing_nullable=False)
    with op.batch_alter_table('hotel_auto_page_version') as b:
        b.alter_column('direct_state', new_column_name='go_direct_state', existing_type=sa.String(32), existing_nullable=False)
    op.rename_table('hotel_registration_official_direct','hotel_registration_go_direct')
    bind=op.get_bind()
    bind.execute(sa.text("UPDATE hotel_canonical_profile SET go_direct_state = CASE go_direct_state WHEN 'DIRECT_VERIFIED' THEN 'GO_DIRECT_VERIFIED' WHEN 'DIRECT_LIVE' THEN 'GO_DIRECT_LIVE' ELSE go_direct_state END"))
    bind.execute(sa.text("UPDATE hotel_auto_page_version SET go_direct_state = CASE go_direct_state WHEN 'DIRECT_VERIFIED' THEN 'GO_DIRECT_VERIFIED' WHEN 'DIRECT_LIVE' THEN 'GO_DIRECT_LIVE' ELSE go_direct_state END"))

def downgrade():
    bind=op.get_bind()
    bind.execute(sa.text("UPDATE hotel_canonical_profile SET go_direct_state = CASE go_direct_state WHEN 'GO_DIRECT_VERIFIED' THEN 'DIRECT_VERIFIED' WHEN 'GO_DIRECT_LIVE' THEN 'DIRECT_LIVE' ELSE go_direct_state END"))
    bind.execute(sa.text("UPDATE hotel_auto_page_version SET go_direct_state = CASE go_direct_state WHEN 'GO_DIRECT_VERIFIED' THEN 'DIRECT_VERIFIED' WHEN 'GO_DIRECT_LIVE' THEN 'DIRECT_LIVE' ELSE go_direct_state END"))
    op.rename_table('hotel_registration_go_direct','hotel_registration_official_direct')
    with op.batch_alter_table('hotel_auto_page_version') as b:
        b.alter_column('go_direct_state', new_column_name='direct_state', existing_type=sa.String(32), existing_nullable=False)
    with op.batch_alter_table('hotel_canonical_profile') as b:
        b.alter_column('go_direct_state', new_column_name='direct_state', existing_type=sa.String(32), existing_nullable=False)
