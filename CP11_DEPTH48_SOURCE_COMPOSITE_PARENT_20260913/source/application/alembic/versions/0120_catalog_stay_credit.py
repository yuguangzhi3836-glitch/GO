"""Funded catalog credit contracts; do not manufacture facts for historical credits."""
from alembic import op
import sqlalchemy as sa
revision = '0120_catalog_stay_credit'
down_revision = '0119_catalog_supplier_remedy'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('catalog_credit_contract',
        sa.Column('credit_id',sa.String(64),primary_key=True),
        sa.Column('original_order_id',sa.String(64),nullable=False,unique=True),
        sa.Column('quote_id',sa.String(64),nullable=False,unique=True),
        sa.Column('contract_json',sa.JSON(),nullable=False),sa.Column('contract_hash',sa.String(64),nullable=False),
        sa.Column('available_minor',sa.BigInteger(),nullable=False),sa.Column('expired_minor',sa.BigInteger(),nullable=False),
        sa.Column('ledger_head_hash',sa.String(64)),sa.Column('accepted_by',sa.String(64),nullable=False),
        *[sa.Column(n,sa.DateTime(timezone=True),nullable=False) for n in ['accepted_at','updated_at']])
    op.create_table('catalog_credit_source',sa.Column('capture_id',sa.String(64),primary_key=True),
        sa.Column('credit_id',sa.String(64),nullable=False),sa.Column('payment_intent_id',sa.String(64),nullable=False),
        sa.Column('funded_minor',sa.BigInteger(),nullable=False),sa.Column('prior_refund_minor',sa.BigInteger(),nullable=False))
    op.create_index('ix_catalog_credit_source_credit_id','catalog_credit_source',['credit_id'])
    op.create_table('catalog_credit_quote',sa.Column('quote_id',sa.String(64),primary_key=True),
        sa.Column('kind',sa.String(24),nullable=False),sa.Column('order_id',sa.String(64),nullable=False),
        sa.Column('credit_id',sa.String(64)),sa.Column('payload_json',sa.JSON(),nullable=False),
        sa.Column('payload_hash',sa.String(64),nullable=False),
        *[sa.Column(n,sa.DateTime(timezone=True),nullable=False) for n in ['expires_at','created_at']])
    for n in ['order_id','credit_id']:op.create_index('ix_catalog_credit_quote_'+n,'catalog_credit_quote',[n])
    op.create_table('catalog_credit_allocation',sa.Column('order_id',sa.String(64),primary_key=True),
        sa.Column('credit_id',sa.String(64),nullable=False),sa.Column('quote_id',sa.String(64),nullable=False,unique=True),
        sa.Column('state',sa.String(40),nullable=False),sa.Column('request_json',sa.JSON(),nullable=False),
        sa.Column('request_hash',sa.String(64),nullable=False),
        *[sa.Column(n,sa.BigInteger(),nullable=False) for n in ['applied_minor','forfeited_minor','restored_minor','refunded_minor','cash_due_minor']],
        sa.Column('supplier_confirmation_no',sa.String(128)),sa.Column('payment_json',sa.JSON()),
        sa.Column('after_sales_json',sa.JSON()),sa.Column('after_sales_hash',sa.String(64)),
        *[sa.Column(n,sa.DateTime(timezone=True),nullable=False) for n in ['created_at','updated_at']])
    for n in ['credit_id','state']:op.create_index('ix_catalog_credit_allocation_'+n,'catalog_credit_allocation',[n])
    op.create_table('catalog_credit_value_event',sa.Column('event_id',sa.String(64),primary_key=True),
        sa.Column('credit_id',sa.String(64),nullable=False),sa.Column('generation',sa.Integer(),nullable=False),
        sa.Column('event_type',sa.String(48),nullable=False),sa.Column('delta_minor',sa.BigInteger(),nullable=False),
        sa.Column('balance_after_minor',sa.BigInteger(),nullable=False),sa.Column('order_id',sa.String(64)),
        sa.Column('evidence_json',sa.JSON(),nullable=False),sa.Column('previous_hash',sa.String(64)),
        sa.Column('event_hash',sa.String(64),nullable=False),sa.Column('actor_id',sa.String(64),nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.UniqueConstraint('credit_id','generation',name='uq_catalog_credit_generation'))
    op.create_index('ix_catalog_credit_value_event_credit_id','catalog_credit_value_event',['credit_id'])


def downgrade():
    for n in ['catalog_credit_value_event','catalog_credit_allocation','catalog_credit_quote','catalog_credit_source','catalog_credit_contract']:
        op.drop_table(n)
