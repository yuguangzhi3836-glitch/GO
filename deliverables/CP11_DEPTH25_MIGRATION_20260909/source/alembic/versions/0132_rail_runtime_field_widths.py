"""Allow complete canonical rail payment states and provider references.

Revision ID: 0132_rail_runtime_field_widths
Revises: 0131_vertical_payment_deadline
"""
from alembic import op
import sqlalchemy as sa

revision = '0132_rail_runtime_field_widths'
down_revision = '0131_vertical_payment_deadline'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('rail_order_runtime') as batch:
        batch.alter_column('status', existing_type=sa.String(32), type_=sa.String(64), existing_nullable=False)
        batch.alter_column('booking_reference', existing_type=sa.String(24), type_=sa.String(128), existing_nullable=True)


def downgrade():
    # PostgreSQL casts can silently truncate on narrowing: refuse before any DDL.
    count = op.get_bind().execute(sa.text(
        'SELECT count(*) FROM rail_order_runtime '
        'WHERE length(status)>32 OR length(booking_reference)>24'
    )).scalar_one()
    if count:
        raise RuntimeError('RAIL_RUNTIME_DOWNGRADE_WOULD_TRUNCATE_HISTORY')
    with op.batch_alter_table('rail_order_runtime') as batch:
        batch.alter_column('status', existing_type=sa.String(64), type_=sa.String(32), existing_nullable=False)
        batch.alter_column('booking_reference', existing_type=sa.String(128), type_=sa.String(24), existing_nullable=True)
