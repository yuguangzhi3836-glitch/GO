"""Index the payment-intent lookup on every catalog money movement."""
from alembic import op

revision = '0144_credit_source_intent_index'
down_revision = '0143_registration_privacy'
branch_labels = None
depends_on = None

TABLE = 'catalog_credit_source'
INDEX = 'ix_catalog_credit_source_payment_intent_id'


def upgrade():
    if op.get_bind().dialect.name == 'postgresql':
        # Existing credit histories may be large; avoid a long write-blocking
        # index build. Alembic commits its migration transaction for online DDL.
        with op.get_context().autocommit_block():
            op.execute(f'CREATE INDEX CONCURRENTLY IF NOT EXISTS {INDEX} ON {TABLE} (payment_intent_id)')
    else:
        op.create_index(INDEX, TABLE, ['payment_intent_id'])


def downgrade():
    if op.get_bind().dialect.name == 'postgresql':
        with op.get_context().autocommit_block():
            op.execute(f'DROP INDEX CONCURRENTLY IF EXISTS {INDEX}')
    else:
        op.drop_index(INDEX, table_name=TABLE)
