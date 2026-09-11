"""Funded property credit, allocation/value ledger and original-source refund plans."""
from alembic import op
import sqlalchemy as sa

revision='0117_hosted_stay_credit'
down_revision='0116_hosted_fare_snapshot'
branch_labels=None
depends_on=None


def upgrade():
    op.create_table('hosted_stay_credit',
        sa.Column('credit_id',sa.String(64),primary_key=True),
        sa.Column('original_reservation_id',sa.String(64),nullable=False,unique=True),
        sa.Column('account_id',sa.String(64),nullable=False),
        sa.Column('hosted_hotel_id',sa.String(64),nullable=False),
        sa.Column('currency',sa.String(8),nullable=False),
        sa.Column('source_capture_id',sa.String(64),nullable=False,unique=True),
        sa.Column('issued_minor',sa.BigInteger(),nullable=False),
        sa.Column('available_minor',sa.BigInteger(),nullable=False),
        sa.Column('state',sa.String(32),nullable=False),
        sa.Column('ledger_head_hash',sa.String(64)),
        *[sa.Column(x,sa.DateTime(timezone=True),nullable=False) for x in ['expires_at','created_at','updated_at']])
    op.create_index('ix_hosted_stay_credit_account_id','hosted_stay_credit',['account_id'])
    op.create_table('hosted_credit_allocation',
        sa.Column('hosted_reservation_id',sa.String(64),primary_key=True),
        sa.Column('credit_id',sa.String(64),nullable=False),
        sa.Column('quote_id',sa.String(64),nullable=False,unique=True),
        *[sa.Column(x,sa.BigInteger(),nullable=False) for x in ['applied_minor','forfeited_minor','fulfilled_minor','fee_consumed_minor','restored_minor']],
        sa.Column('state',sa.String(24),nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False))
    op.create_index('ix_hosted_credit_allocation_credit_id','hosted_credit_allocation',['credit_id'])
    op.create_table('hosted_credit_value_event',
        sa.Column('event_id',sa.String(64),primary_key=True),
        sa.Column('credit_id',sa.String(64),nullable=False),
        sa.Column('generation',sa.Integer(),nullable=False),
        sa.Column('event_type',sa.String(32),nullable=False),
        sa.Column('delta_minor',sa.BigInteger(),nullable=False),
        sa.Column('balance_after_minor',sa.BigInteger(),nullable=False),
        sa.Column('reservation_id',sa.String(64)),
        sa.Column('evidence_json',sa.JSON(),nullable=False),
        sa.Column('previous_hash',sa.String(64)),
        sa.Column('event_hash',sa.String(64),nullable=False,unique=True),
        sa.Column('actor_id',sa.String(64),nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.UniqueConstraint('credit_id','generation',name='uq_hosted_credit_event_generation'))
    op.create_index('ix_hosted_credit_value_event_credit_id','hosted_credit_value_event',['credit_id'])
    op.create_table('hosted_credit_refund_plan',
        sa.Column('refund_eligibility_id',sa.String(64),primary_key=True),
        sa.Column('hosted_reservation_id',sa.String(64),nullable=False),
        sa.Column('plan_json',sa.JSON(),nullable=False),
        sa.Column('plan_hash',sa.String(64),nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False))
    op.create_index('ix_hosted_credit_refund_plan_hosted_reservation_id','hosted_credit_refund_plan',['hosted_reservation_id'])


def downgrade():
    for name in ['hosted_credit_refund_plan','hosted_credit_value_event','hosted_credit_allocation','hosted_stay_credit']:op.drop_table(name)
