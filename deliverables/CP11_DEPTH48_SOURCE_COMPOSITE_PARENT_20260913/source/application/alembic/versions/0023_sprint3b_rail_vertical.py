"""Sprint 3B rail complete golden path.

Revision ID: 0023_sprint3b
Revises: 0022_sprint3a
"""
from alembic import op
import sqlalchemy as sa
revision='0023_sprint3b'; down_revision='0022_sprint3a'; branch_labels=None; depends_on=None

def upgrade():
    op.create_table('rail_offer_runtime',
        sa.Column('offer_id',sa.String(64),primary_key=True),sa.Column('origin_station',sa.String(16),nullable=False),sa.Column('destination_station',sa.String(16),nullable=False),sa.Column('travel_date',sa.String(10),nullable=False),sa.Column('train_no',sa.String(16),nullable=False),sa.Column('seat_class',sa.String(32),nullable=False),sa.Column('total_amount_minor',sa.BigInteger(),nullable=False),sa.Column('currency',sa.String(3),nullable=False),sa.Column('departure_time',sa.String(8),nullable=False),sa.Column('arrival_time',sa.String(8),nullable=False),sa.Column('duration_minutes',sa.Integer(),nullable=False),sa.Column('stations',sa.JSON(),nullable=False),sa.Column('change_policy',sa.JSON(),nullable=False),sa.Column('refund_policy',sa.JSON(),nullable=False),sa.Column('inventory_left',sa.Integer(),nullable=False),sa.Column('expires_at',sa.DateTime(timezone=True),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False))
    op.create_table('rail_prebook_runtime',sa.Column('prebook_id',sa.String(64),primary_key=True),sa.Column('offer_id',sa.String(64),nullable=False),sa.Column('total_amount_minor',sa.BigInteger(),nullable=False),sa.Column('currency',sa.String(3),nullable=False),sa.Column('status',sa.String(32),nullable=False),sa.Column('price_locked',sa.Boolean(),nullable=False),sa.Column('inventory_confirmed',sa.Boolean(),nullable=False),sa.Column('expires_at',sa.DateTime(timezone=True),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False))
    op.create_table('rail_order_runtime',sa.Column('order_id',sa.String(64),primary_key=True),sa.Column('account_id',sa.String(64),nullable=False),sa.Column('prebook_id',sa.String(64),nullable=False),sa.Column('status',sa.String(32),nullable=False),sa.Column('total_amount_minor',sa.BigInteger(),nullable=False),sa.Column('currency',sa.String(3),nullable=False),sa.Column('passengers',sa.JSON(),nullable=False),sa.Column('payment_method_id',sa.String(64)),sa.Column('booking_reference',sa.String(24)),sa.Column('ticket_numbers',sa.JSON(),nullable=False),sa.Column('current_journey',sa.JSON(),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False))
    op.create_table('rail_change_quote_runtime',sa.Column('quote_id',sa.String(64),primary_key=True),sa.Column('order_id',sa.String(64),nullable=False),sa.Column('new_travel_date',sa.String(10),nullable=False),sa.Column('new_train_no',sa.String(16),nullable=False),sa.Column('new_seat_class',sa.String(32),nullable=False),sa.Column('fare_difference_minor',sa.BigInteger(),nullable=False),sa.Column('change_fee_minor',sa.BigInteger(),nullable=False),sa.Column('total_due_minor',sa.BigInteger(),nullable=False),sa.Column('currency',sa.String(3),nullable=False),sa.Column('status',sa.String(24),nullable=False),sa.Column('expires_at',sa.DateTime(timezone=True),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False))
    op.create_table('rail_refund_runtime',sa.Column('refund_id',sa.String(64),primary_key=True),sa.Column('order_id',sa.String(64),nullable=False),sa.Column('refund_fee_minor',sa.BigInteger(),nullable=False),sa.Column('refund_amount_minor',sa.BigInteger(),nullable=False),sa.Column('currency',sa.String(3),nullable=False),sa.Column('status',sa.String(32),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.Column('completed_at',sa.DateTime(timezone=True)))

def downgrade():
    for t in ['rail_refund_runtime','rail_change_quote_runtime','rail_order_runtime','rail_prebook_runtime','rail_offer_runtime']:
        op.drop_table(t)
