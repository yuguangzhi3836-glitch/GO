"""Durable rental reprice quotes and original-payment refund plans.

The original 114 migrations remain unchanged.
"""
from alembic import op
import sqlalchemy as sa

revision = '0115_rental_change_settlement'
down_revision = '0114_ext_truth_incident_hard'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('rental_change_quote',
        sa.Column('quote_id', sa.String(64), primary_key=True),
        sa.Column('order_id', sa.String(64), nullable=False),
        *[sa.Column(name, sa.String(40), nullable=False) for name in
          ('old_pickup_at','old_return_at','new_pickup_at','new_return_at')],
        *[sa.Column(name, sa.BigInteger(), nullable=False) for name in
          ('old_amount_minor','new_amount_minor','difference_minor','daily_rate_minor')],
        sa.Column('currency',sa.String(3),nullable=False),
        sa.Column('order_revision',sa.String(64),nullable=False),
        sa.Column('status',sa.String(32),nullable=False),
        sa.Column('refund_plan_json',sa.JSON(),nullable=False),
        *[sa.Column(name,sa.DateTime(),nullable=False) for name in ('expires_at','created_at','updated_at')])
    op.create_index('ix_rental_change_quote_order_id','rental_change_quote',['order_id'])
    op.create_index('ix_rental_change_quote_status','rental_change_quote',['status'])
    op.add_column('mobility_refund_runtime',sa.Column('settlement_plan_json',sa.JSON(),nullable=False,server_default='[]'))


def downgrade():
    op.drop_column('mobility_refund_runtime','settlement_plan_json')
    op.drop_table('rental_change_quote')
