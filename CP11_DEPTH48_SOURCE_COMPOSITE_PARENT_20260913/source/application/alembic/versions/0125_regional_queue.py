"""Durable regional queue; retain old Redis data until reviewed import."""
from alembic import op
import sqlalchemy as sa

revision = '0125_regional_queue'
down_revision = '0124_autonomy_durable'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('regional_build_queue',
        sa.Column('message_id', sa.String(64), primary_key=True, nullable=False),
        sa.Column('topic', sa.String(96), nullable=False),
        sa.Column('run_id', sa.String(64), nullable=False),
        sa.Column('payload_hash', sa.String(64), nullable=False),
        sa.Column('payload_json', sa.JSON(), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('attempt', sa.Integer(), nullable=False),
        sa.Column('max_attempts', sa.Integer(), nullable=False),
        sa.Column('available_ms', sa.BigInteger(), nullable=False),
        sa.Column('lease_until_ms', sa.BigInteger()),
        sa.Column('lease_token', sa.String(64)),
        sa.Column('last_code', sa.String(96)),
        sa.Column('result_json', sa.JSON()),
        sa.Column('created_ms', sa.BigInteger(), nullable=False),
        sa.Column('updated_ms', sa.BigInteger(), nullable=False),
        sa.CheckConstraint('attempt >= 0 AND max_attempts BETWEEN 1 AND 20', name='ck_regional_queue_bounds'),
        sa.CheckConstraint("status IN ('QUEUED','RUNNING','SUCCEEDED','DEAD','SUPERSEDED')", name='ck_regional_queue_status'))
    op.create_index('ix_regional_queue_ready', 'regional_build_queue', ['topic','status','available_ms'])
    op.create_index('ix_regional_queue_run', 'regional_build_queue', ['run_id','status'])


def downgrade():
    if op.get_bind().scalar(sa.text('SELECT count(*) FROM regional_build_queue')):
        raise RuntimeError('REGIONAL_QUEUE_DATA_PRESENT_RESTORE_BACKUP_FOR_DOWNGRADE')
    op.drop_table('regional_build_queue')
