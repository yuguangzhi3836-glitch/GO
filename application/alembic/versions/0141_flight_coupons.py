"""Durable coupon identity, exact allocations and recoverable partial refunds."""
from alembic import op
import sqlalchemy as sa

revision='0141_flight_coupons'
down_revision='0140_ledger_account_width'
branch_labels=None
depends_on=None


def upgrade():
    op.create_table('flight_coupon',
        sa.Column('coupon_id',sa.String(64),primary_key=True),
        sa.Column('order_id',sa.String(64),nullable=False),
        sa.Column('account_id',sa.String(64),nullable=False),
        sa.Column('leg_index',sa.Integer(),nullable=False),
        sa.Column('passenger_index',sa.Integer(),nullable=False),
        sa.Column('state',sa.String(24),nullable=False),
        sa.Column('version',sa.Integer(),nullable=False),
        sa.Column('ticket_number',sa.String(64)),sa.Column('supplier_reference',sa.String(16)),
        sa.Column('currency',sa.String(3),nullable=False),
        sa.Column('paid_amount_minor',sa.BigInteger(),nullable=False),
        sa.Column('refunded_amount_minor',sa.BigInteger(),nullable=False),
        sa.Column('leg_json',sa.JSON(),nullable=False),
        sa.Column('change_policy',sa.JSON(),nullable=False),
        sa.Column('refund_policy',sa.JSON(),nullable=False),
        sa.UniqueConstraint('order_id','leg_index','passenger_index',name='uq_flight_coupon_position'),
        sa.CheckConstraint("state IN ('UNISSUED','ISSUED','REFUND_PENDING','REFUNDED')",name='ck_flight_coupon_state'),
        sa.CheckConstraint('leg_index >= 0 AND passenger_index >= 0 AND version >= 0',name='ck_flight_coupon_position'),
        sa.CheckConstraint('paid_amount_minor >= 0 AND refunded_amount_minor >= 0 AND refunded_amount_minor <= paid_amount_minor',name='ck_flight_coupon_money'))
    op.create_index('ix_flight_coupon_order_id','flight_coupon',['order_id'])
    op.create_table('flight_coupon_refund',
        sa.Column('refund_id',sa.String(64),primary_key=True),
        sa.Column('order_id',sa.String(64),nullable=False),
        sa.Column('account_id',sa.String(64),nullable=False),
        sa.Column('state',sa.String(16),nullable=False),
        sa.Column('quote_json',sa.JSON(),nullable=False),
        sa.Column('quote_hash',sa.String(64),nullable=False),
        sa.Column('money_plan_json',sa.JSON()),sa.Column('execution_hash',sa.String(64)),
        sa.Column('result_json',sa.JSON()),sa.Column('lease_token',sa.String(64)),
        sa.Column('lease_until_ms',sa.BigInteger(),nullable=False),
        sa.Column('created_ms',sa.BigInteger(),nullable=False),
        sa.Column('expires_ms',sa.BigInteger(),nullable=False),
        sa.CheckConstraint("state IN ('QUOTED','PREPARED','COMPLETED')",name='ck_flight_coupon_refund_state'),
        sa.CheckConstraint('lease_until_ms >= 0 AND expires_ms > created_ms',name='ck_flight_coupon_refund_time'))
    op.create_index('ix_flight_coupon_refund_order_id','flight_coupon_refund',['order_id'])


def downgrade():
    for table in ['flight_coupon_refund','flight_coupon']:
        if op.get_bind().scalar(sa.text('SELECT count(*) FROM '+table)):
            raise RuntimeError('FLIGHT_COUPON_DATA_PRESENT_RESTORE_BACKUP_FOR_DOWNGRADE')
    op.drop_index('ix_flight_coupon_refund_order_id',table_name='flight_coupon_refund')
    op.drop_table('flight_coupon_refund')
    op.drop_index('ix_flight_coupon_order_id',table_name='flight_coupon')
    op.drop_table('flight_coupon')
