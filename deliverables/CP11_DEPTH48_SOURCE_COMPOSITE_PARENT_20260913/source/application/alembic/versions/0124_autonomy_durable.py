"""Durable governed task execution; existing business schema remains intact."""
from alembic import op
import sqlalchemy as sa

revision = "0124_autonomy_durable"
down_revision = "0123_catalog_credit_exclusion"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('autonomy_cell_control',
        sa.Column('environment', sa.String(length=24), primary_key=True, nullable=False),
        sa.Column('cell_id', sa.String(length=8), primary_key=True, nullable=False),
        sa.Column('paused', sa.Boolean(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('updated_by', sa.String(length=64), nullable=False),
        sa.Column('updated_ms', sa.BigInteger(), nullable=False))
    op.create_table('autonomy_qualification',
        sa.Column('qualification_id', sa.String(length=64), primary_key=True, nullable=False),
        sa.Column('record_json', sa.JSON(), nullable=False),
        sa.Column('expires_ms', sa.BigInteger(), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('updated_ms', sa.BigInteger(), nullable=False))
    op.create_table('autonomy_task',
        sa.Column('task_id', sa.String(length=64), primary_key=True, nullable=False),
        sa.Column('environment', sa.String(length=24), nullable=False),
        sa.Column('cell_id', sa.String(length=8), nullable=False),
        sa.Column('operation', sa.String(length=96), nullable=False),
        sa.Column('handler_version', sa.String(length=64), nullable=False),
        sa.Column('request_hash', sa.String(length=64), nullable=False),
        sa.Column('submitted_by', sa.String(length=64), nullable=False),
        sa.Column('payload_json', sa.JSON(), nullable=False),
        sa.Column('status', sa.String(length=24), nullable=False),
        sa.Column('attempt', sa.Integer(), nullable=False),
        sa.Column('max_attempts', sa.Integer(), nullable=False),
        sa.Column('next_step', sa.Integer(), nullable=False),
        sa.Column('event_seq', sa.Integer(), nullable=False),
        sa.Column('available_ms', sa.BigInteger(), nullable=False),
        sa.Column('lease_until_ms', sa.BigInteger(), nullable=True),
        sa.Column('lease_token', sa.String(length=64), nullable=True),
        sa.Column('worker_id', sa.String(length=128), nullable=True),
        sa.Column('external_started', sa.Boolean(), nullable=False),
        sa.Column('last_code', sa.String(length=128), nullable=True),
        sa.Column('result_json', sa.JSON(), nullable=True),
        sa.Column('created_ms', sa.BigInteger(), nullable=False),
        sa.Column('updated_ms', sa.BigInteger(), nullable=False),
        sa.CheckConstraint('attempt >= 0 AND max_attempts BETWEEN 1 AND 20 AND next_step >= 0', name='ck_autonomy_task_bounds'),
        sa.CheckConstraint("status IN ('QUEUED','RUNNING','RETRY_WAIT','HOLD','SUCCEEDED','FAILED','DEAD','UNCERTAIN','CANCELLED')", name='ck_autonomy_task_status'))
    op.create_index('ix_autonomy_task_cell', 'autonomy_task', ['environment', 'cell_id', 'created_ms'], unique=False)
    op.create_index('ix_autonomy_task_queue', 'autonomy_task', ['environment', 'status', 'available_ms'], unique=False)
    op.create_table('autonomy_step',
        sa.Column('task_id', sa.String(length=64), sa.ForeignKey('autonomy_task.task_id'), primary_key=True, nullable=False),
        sa.Column('step_no', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('result_json', sa.JSON(), nullable=False),
        sa.Column('result_hash', sa.String(length=64), nullable=False),
        sa.Column('completed_ms', sa.BigInteger(), nullable=False))
    op.create_table('autonomy_event',
        sa.Column('event_id', sa.String(length=64), primary_key=True, nullable=False),
        sa.Column('task_id', sa.String(length=64), sa.ForeignKey('autonomy_task.task_id'), nullable=True),
        sa.Column('environment', sa.String(length=24), nullable=False),
        sa.Column('cell_id', sa.String(length=8), nullable=False),
        sa.Column('event_type', sa.String(length=48), nullable=False),
        sa.Column('actor_id', sa.String(length=128), nullable=False),
        sa.Column('details_json', sa.JSON(), nullable=False),
        sa.Column('created_ms', sa.BigInteger(), nullable=False),
        sa.Column('sequence', sa.Integer(), nullable=False),
        sa.UniqueConstraint('task_id', 'sequence', name='uq_autonomy_event_sequence'))
    op.create_index('ix_autonomy_event_task_id', 'autonomy_event', ['task_id'], unique=False)


def downgrade():
    conn = op.get_bind()
    # Queue/evidence deletion is not an application rollback. Export or restore a
    # verified database backup before explicitly removing populated tables.
    for name in ['autonomy_cell_control', 'autonomy_qualification', 'autonomy_task', 'autonomy_step', 'autonomy_event']:
        if conn.scalar(sa.text('SELECT count(*) FROM ' + name)):
            raise RuntimeError('AUTONOMY_DATA_PRESENT_RESTORE_BACKUP_FOR_DOWNGRADE')
    op.drop_table('autonomy_event')
    op.drop_table('autonomy_step')
    op.drop_table('autonomy_task')
    op.drop_table('autonomy_qualification')
    op.drop_table('autonomy_cell_control')
