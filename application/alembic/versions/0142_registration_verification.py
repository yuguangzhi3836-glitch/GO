"""Durable registration challenges and bounded delivery rates; no runtime enablement."""
from alembic import op
import sqlalchemy as sa
revision = '0142_registration_verification'
down_revision = '0141_flight_coupons'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('registration_challenge',
        sa.Column('subject_key', sa.String(64), primary_key=True),
        sa.Column('challenge_id', sa.String(64), unique=True, nullable=False),
        sa.Column('code_digest', sa.String(64), nullable=False),
        sa.Column('policy_digest', sa.String(64), nullable=False),
        sa.Column('state', sa.String(16), nullable=False),
        sa.Column('attempts', sa.Integer(), nullable=False),
        sa.Column('expires_ms', sa.BigInteger(), nullable=False),
        sa.Column('created_ms', sa.BigInteger(), nullable=False),
        sa.Column('consumed_by', sa.String(64)))
    op.create_table('registration_rate',
        sa.Column('bucket_key', sa.String(64), primary_key=True),
        sa.Column('count', sa.Integer(), nullable=False),
        sa.Column('expires_ms', sa.BigInteger(), nullable=False))


def downgrade():
    for table in ('registration_challenge', 'registration_rate'):
        if op.get_bind().scalar(sa.text('SELECT count(*) FROM ' + table)):
            raise RuntimeError('REGISTRATION_DATA_PRESENT_RESTORE_BACKUP_FOR_DOWNGRADE')
    op.drop_table('registration_rate')
    op.drop_table('registration_challenge')
