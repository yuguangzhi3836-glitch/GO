"""Durable rail/attraction refund claims; preserve existing order history."""
from alembic import op
import sqlalchemy as sa

revision = '0128_vertical_refund_recovery'
down_revision = '0127_vertical_prebook_contract'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('vertical_refund_operation',
        sa.Column('vertical', sa.String(16), primary_key=True),
        sa.Column('order_id', sa.String(64), primary_key=True),
        sa.Column('account_id', sa.String(64), nullable=False),
        sa.Column('state', sa.String(16), nullable=False),
        sa.Column('quote_json', sa.JSON(), nullable=False),
        sa.Column('adjustment_ids_json', sa.JSON(), nullable=False),
        sa.Column('request_hash', sa.String(64), nullable=False),
        sa.Column('result_json', sa.JSON()),
        sa.Column('lease_token', sa.String(64)),
        sa.Column('lease_until_ms', sa.BigInteger(), nullable=False),
        sa.Column('attempt', sa.Integer(), nullable=False),
        sa.Column('created_ms', sa.BigInteger(), nullable=False),
        sa.Column('completed_ms', sa.BigInteger()),
        sa.CheckConstraint("vertical IN ('RAIL','ATTRACTION')", name='ck_refund_operation_vertical'),
        sa.CheckConstraint("state IN ('PENDING','COMPLETED')", name='ck_refund_operation_state'),
        sa.CheckConstraint('attempt >= 0 AND lease_until_ms >= 0', name='ck_refund_operation_lease'))


def downgrade():
    if op.get_bind().scalar(sa.text('SELECT count(*) FROM vertical_refund_operation')):
        raise RuntimeError('REFUND_OPERATION_DATA_PRESENT_RESTORE_BACKUP_FOR_DOWNGRADE')
    op.drop_table('vertical_refund_operation')
