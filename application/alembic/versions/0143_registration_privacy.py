"""Registration decision history, privacy intake and bounded cleanup heartbeat."""
from alembic import op
import sqlalchemy as sa
revision = '0143_registration_privacy'
down_revision = '0142_registration_verification'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('registration_decision',
        sa.Column('decision_id',sa.String(64),primary_key=True),
        sa.Column('user_id',sa.String(64),nullable=False),
        sa.Column('audience',sa.String(16),nullable=False),
        sa.Column('decisions',sa.JSON(),nullable=False),
        sa.Column('versions',sa.JSON(),nullable=False),
        sa.Column('hashes',sa.JSON(),nullable=False),
        sa.Column('created_ms',sa.BigInteger(),nullable=False),
        sa.Column('expires_ms',sa.BigInteger(),nullable=False))
    op.create_index('ix_registration_decision_user_id','registration_decision',['user_id'])
    op.create_index('ix_registration_decision_expires_ms','registration_decision',['expires_ms'])
    op.create_table('registration_maintenance',sa.Column('key',sa.String(40),primary_key=True),sa.Column('success_ms',sa.BigInteger(),nullable=False))
    op.create_table('privacy_request',
        sa.Column('request_id',sa.String(64),primary_key=True),
        sa.Column('user_id',sa.String(64),nullable=False),
        sa.Column('kind',sa.String(24),nullable=False),
        sa.Column('status',sa.String(24),nullable=False),
        sa.Column('created_ms',sa.BigInteger(),nullable=False),
        sa.Column('due_ms',sa.BigInteger(),nullable=False),
        sa.Column('updated_ms',sa.BigInteger(),nullable=False),
        sa.Column('resolution',sa.JSON(),nullable=False))
    op.create_index('ix_privacy_request_user_id','privacy_request',['user_id'])

def downgrade():
    for name in ('privacy_request','registration_decision'):
        if op.get_bind().scalar(sa.text('SELECT count(*) FROM '+name)):
            raise RuntimeError('PRIVACY_RECORDS_PRESENT_RESTORE_REQUIRED')
    for name in ('privacy_request','registration_decision','registration_maintenance'):
        op.drop_table(name)
