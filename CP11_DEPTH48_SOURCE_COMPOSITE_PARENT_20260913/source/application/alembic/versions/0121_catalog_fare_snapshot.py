"""Versioned catalog rules and new order acceptance; no invented historical acceptance."""
from alembic import op
import sqlalchemy as sa

revision = '0121_catalog_fare_snapshot'
down_revision = '0120_catalog_stay_credit'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('catalog_fare_family',
        sa.Column('family_id', sa.String(64), primary_key=True),
        *[sa.Column(n, sa.String(64), nullable=False) for n in ['property_id', 'supplier_id', 'connector_id', 'fare_rule_id']],
        sa.Column('currency', sa.String(8), nullable=False),
        sa.Column('current_version_id', sa.String(64)), sa.Column('version', sa.Integer(), nullable=False))
    op.create_index('ix_catalog_fare_family_supplier_id', 'catalog_fare_family', ['supplier_id'])
    op.create_table('catalog_fare_rule_version',
        sa.Column('version_id', sa.String(64), primary_key=True),
        sa.Column('family_id', sa.String(64), nullable=False), sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('contract_json', sa.JSON(), nullable=False), sa.Column('contract_hash', sa.String(64), nullable=False),
        sa.Column('published_by', sa.String(64), nullable=False), sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('family_id', 'version', name='uq_catalog_fare_version'))
    op.create_index('ix_catalog_fare_rule_version_family_id', 'catalog_fare_rule_version', ['family_id'])
    for table, key in [('catalog_offer_fare_snapshot', 'offer_id'), ('catalog_order_fare_snapshot', 'order_id')]:
        extra = [] if key == 'offer_id' else [sa.Column('accepted_by', sa.String(64), nullable=False), sa.Column('acceptance_kind', sa.String(40), nullable=False)]
        op.create_table(table, sa.Column(key, sa.String(64), primary_key=True),
            sa.Column('version_id', sa.String(64), nullable=False),
            sa.Column('snapshot_json', sa.JSON(), nullable=False), sa.Column('snapshot_hash', sa.String(64), nullable=False),
            *extra, sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))


def downgrade():
    for table in ['catalog_order_fare_snapshot', 'catalog_offer_fare_snapshot', 'catalog_fare_rule_version', 'catalog_fare_family']:
        op.drop_table(table)
