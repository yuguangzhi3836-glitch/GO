"""Versioned hotel rules, immutable order snapshots and executable fare quotes."""
from alembic import op
import sqlalchemy as sa

revision = '0116_hosted_fare_snapshot'
down_revision = '0115_rental_change_settlement'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('hosted_fare_rule_version',
        sa.Column('rule_version_id',sa.String(64),primary_key=True),
        sa.Column('hosted_offer_id',sa.String(64),nullable=False),
        sa.Column('version',sa.Integer(),nullable=False),
        sa.Column('rules_json',sa.JSON(),nullable=False),
        sa.Column('rule_hash',sa.String(64),nullable=False),
        sa.Column('authority_reference',sa.String(512),nullable=False),
        sa.Column('published_by',sa.String(64),nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.UniqueConstraint('hosted_offer_id','version',name='uq_hosted_fare_version'))
    op.create_index('ix_hosted_fare_rule_version_hosted_offer_id','hosted_fare_rule_version',['hosted_offer_id'])
    op.create_table('hosted_order_fare_snapshot',
        sa.Column('hosted_reservation_id',sa.String(64),primary_key=True),
        sa.Column('rule_version_id',sa.String(64),nullable=False),
        sa.Column('rules_json',sa.JSON(),nullable=False),
        sa.Column('rule_hash',sa.String(64),nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False))
    op.create_table('hosted_fare_quote',
        sa.Column('quote_id',sa.String(64),primary_key=True),
        sa.Column('hosted_reservation_id',sa.String(64),nullable=False),
        sa.Column('action',sa.String(32),nullable=False),
        sa.Column('order_revision',sa.String(64),nullable=False),
        sa.Column('quote_json',sa.JSON(),nullable=False),
        sa.Column('quote_hash',sa.String(64),nullable=False),
        sa.Column('state',sa.String(24),nullable=False),
        sa.Column('result_json',sa.JSON(),nullable=False),
        sa.Column('expires_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False))
    op.create_index('ix_hosted_fare_quote_hosted_reservation_id','hosted_fare_quote',['hosted_reservation_id'])
    op.create_table('hosted_fare_funding',
        sa.Column('quote_id',sa.String(64),primary_key=True),
        sa.Column('hosted_reservation_id',sa.String(64),nullable=False),
        sa.Column('generation',sa.Integer(),nullable=False),
        sa.Column('payment_intent_id',sa.String(64),nullable=False,unique=True),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.UniqueConstraint('hosted_reservation_id','generation',name='uq_hosted_fare_funding_generation'))
    op.create_index('ix_hosted_fare_funding_hosted_reservation_id','hosted_fare_funding',['hosted_reservation_id'])



def downgrade():
    op.drop_table('hosted_fare_funding')
    op.drop_table('hosted_fare_quote')
    op.drop_table('hosted_order_fare_snapshot')
    op.drop_table('hosted_fare_rule_version')
