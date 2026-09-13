"""Bound multi-leg flight plans and durable supplier decisions."""
from alembic import op
import sqlalchemy as sa

revision = '0133_flight_change_plan'
down_revision = '0132_rail_runtime_field_widths'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('flight_change_plan',
        sa.Column('quote_id', sa.String(64), primary_key=True),
        sa.Column('order_id', sa.String(64), nullable=False),
        sa.Column('account_id', sa.String(64), nullable=False),
        sa.Column('plan_json', sa.JSON(), nullable=False),
        sa.Column('plan_hash', sa.String(64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))
    op.create_index('ix_flight_change_plan_order_id', 'flight_change_plan', ['order_id'])
    op.create_table('flight_change_resolution',
        sa.Column('quote_id', sa.String(64), primary_key=True),
        sa.Column('order_id', sa.String(64), nullable=False),
        sa.Column('account_id', sa.String(64), nullable=False),
        sa.Column('actor_id', sa.String(64), nullable=False),
        sa.Column('state', sa.String(16), nullable=False),
        sa.Column('request_json', sa.JSON(), nullable=False),
        sa.Column('terms_json', sa.JSON(), nullable=False),
        sa.Column('request_hash', sa.String(64), nullable=False),
        sa.Column('result_json', sa.JSON()),
        sa.Column('lease_token', sa.String(64)),
        sa.Column('lease_until_ms', sa.BigInteger(), nullable=False),
        sa.Column('attempt', sa.Integer(), nullable=False),
        sa.Column('created_ms', sa.BigInteger(), nullable=False),
        sa.Column('completed_ms', sa.BigInteger()),
        sa.CheckConstraint("state IN ('PENDING','COMPLETED')", name='ck_flight_resolution_state'),
        sa.CheckConstraint('attempt >= 0 AND lease_until_ms >= 0', name='ck_flight_resolution_lease'))
    op.create_index('ix_flight_change_resolution_order_id', 'flight_change_resolution', ['order_id'])


def downgrade():
    if op.get_bind().scalar(sa.text('SELECT count(*) FROM flight_change_resolution')) or op.get_bind().scalar(sa.text('SELECT count(*) FROM flight_change_plan')):
        raise RuntimeError('FLIGHT_RESOLUTION_DATA_PRESENT_RESTORE_BACKUP_FOR_DOWNGRADE')
    op.drop_index('ix_flight_change_resolution_order_id', table_name='flight_change_resolution')
    op.drop_table('flight_change_resolution')

    op.drop_index('ix_flight_change_plan_order_id', table_name='flight_change_plan')
    op.drop_table('flight_change_plan')
