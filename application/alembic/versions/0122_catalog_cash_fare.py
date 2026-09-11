"""Durable ordinary cash after-sales; historical quotes remain unaccepted."""
from alembic import op
import sqlalchemy as sa

revision = '0122_catalog_cash_fare'
down_revision = '0121_catalog_fare_snapshot'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('catalog_cash_fare_quote',
        sa.Column('quote_id', sa.String(64), primary_key=True),
        sa.Column('order_id', sa.String(64), nullable=False),
        sa.Column('action', sa.String(16), nullable=False),
        sa.Column('payload_json', sa.JSON(), nullable=False),
        sa.Column('quote_hash', sa.String(64), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))
    op.create_index('ix_catalog_cash_fare_quote_order_id', 'catalog_cash_fare_quote', ['order_id'])
    op.create_table('catalog_cash_fare_operation',
        sa.Column('operation_id', sa.String(64), primary_key=True),
        sa.Column('order_id', sa.String(64), nullable=False),
        sa.Column('quote_id', sa.String(64), nullable=False, unique=True),
        sa.Column('state', sa.String(40), nullable=False),
        sa.Column('plan_json', sa.JSON(), nullable=False),
        sa.Column('plan_hash', sa.String(64), nullable=False),
        sa.Column('payment_json', sa.JSON()),
        sa.Column('supplier_reference', sa.String(128)),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False))
    op.create_index('ix_catalog_cash_fare_operation_order_id', 'catalog_cash_fare_operation', ['order_id'])
    op.create_table('catalog_cash_fare_claim',
        sa.Column('order_id', sa.String(64), primary_key=True),
        sa.Column('operation_id', sa.String(64), nullable=False, unique=True))

def downgrade():
    for table in ['catalog_cash_fare_claim', 'catalog_cash_fare_operation', 'catalog_cash_fare_quote']:
        op.drop_table(table)
