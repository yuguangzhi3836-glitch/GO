"""Separate previously forfeited cash value from prepaid credit source budgets."""
from alembic import op
import sqlalchemy as sa

revision = '0123_catalog_credit_exclusion'
down_revision = '0122_catalog_cash_fare'
branch_labels = None
depends_on = None

def upgrade():
    op.add_column('catalog_credit_source', sa.Column('excluded_minor', sa.BigInteger(), nullable=False, server_default='0'))

def downgrade():
    # Older executors cannot represent split source budgets; never silently drop them.
    if op.get_bind().execute(sa.text('SELECT count(*) FROM catalog_credit_source WHERE excluded_minor != 0')).scalar():
        raise RuntimeError('CREDIT_EXCLUSION_DATA_REQUIRES_RECONCILED_ROLLBACK')
    op.drop_column('catalog_credit_source', 'excluded_minor')
