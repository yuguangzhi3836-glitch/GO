"""Frozen deadlines for newly created unpaid rail and attraction reservations."""
from alembic import op
import sqlalchemy as sa

revision = '0131_vertical_payment_deadline'
down_revision = '0130_vertical_capacity'
branch_labels = None
depends_on = None


def upgrade():
    # Existing orders receive no invented deadline and retain their claims.
    op.create_table('vertical_payment_deadline',
        sa.Column('vertical', sa.String(16), primary_key=True),
        sa.Column('order_id', sa.String(64), primary_key=True),
        sa.Column('account_id', sa.String(64), nullable=False),
        sa.Column('created_ms', sa.BigInteger(), nullable=False),
        sa.Column('expires_ms', sa.BigInteger(), nullable=False),
        sa.Column('terms_hash', sa.String(64), nullable=False),
        sa.Column('state', sa.String(24), nullable=False),
        sa.Column('finalized_ms', sa.BigInteger()),
        sa.Column('reason', sa.String(96)),
        sa.CheckConstraint("vertical IN ('RAIL','ATTRACTION')", name='ck_payment_deadline_vertical'),
        sa.CheckConstraint("state IN ('OPEN','PAYMENT_STARTED','CANCELLED','EXPIRED','REVIEW')", name='ck_payment_deadline_state'),
        sa.CheckConstraint('created_ms >= 0 AND expires_ms > created_ms', name='ck_payment_deadline_bounds'))
    op.create_index('ix_payment_deadline_due', 'vertical_payment_deadline', ['state', 'expires_ms', 'vertical', 'order_id'])


def downgrade():
    if op.get_bind().scalar(sa.text('SELECT count(*) FROM vertical_payment_deadline')):
        raise RuntimeError('PAYMENT_DEADLINE_DATA_PRESENT_RESTORE_BACKUP_FOR_DOWNGRADE')
    op.drop_index('ix_payment_deadline_due', table_name='vertical_payment_deadline')
    op.drop_table('vertical_payment_deadline')
