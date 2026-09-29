"""Preserve complete ledger account identities across supported business types.

Revision ID: 0140_ledger_account_width
Revises: 0139_hosted_publication_review
"""
from alembic import op
import sqlalchemy as sa

revision = '0140_ledger_account_width'
down_revision = '0139_hosted_publication_review'
branch_labels = None
depends_on = None
TABLE = 'omnichannel_ledger_entry'


def account_column(bind):
    inspector = sa.inspect(bind)
    # Historical isolated migration tests can omit unrelated payment tables.
    if not inspector.has_table(TABLE):
        return None
    column = next((c for c in inspector.get_columns(TABLE) if c['name'] == 'account_code'), None)
    if (column is None or not isinstance(column['type'], sa.String)
            or column['type'].length not in (64, 128) or column['nullable']):
        raise RuntimeError('LEDGER_ACCOUNT_SCHEMA_MISMATCH')
    return column


def resize(column, width):
    if column is None or column['type'].length == width:
        return
    with op.batch_alter_table(TABLE) as batch:
        batch.alter_column('account_code', existing_type=column['type'],
                          type_=sa.String(width), existing_nullable=False)


def upgrade():
    # BUSINESS: + business_type VARCHAR(32) + ':' + business_id VARCHAR(64)
    # is at most 106 characters. Keep every existing account key byte-for-byte.
    resize(account_column(op.get_bind()), 128)


def downgrade():
    bind = op.get_bind()
    column = account_column(bind)
    if column is not None and bind.execute(sa.text(
            'SELECT COUNT(*) FROM omnichannel_ledger_entry WHERE length(account_code) > 64')).scalar():
        raise RuntimeError('LEDGER_ACCOUNT_DOWNGRADE_DATA_PRESENT')
    resize(column, 64)
