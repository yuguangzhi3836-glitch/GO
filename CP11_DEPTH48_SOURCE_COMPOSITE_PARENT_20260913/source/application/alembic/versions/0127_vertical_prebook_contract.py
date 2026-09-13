"""Bind quoted parties and terms to one consumer order; no fabricated legacy backfill."""
from alembic import op
import sqlalchemy as sa

revision='0127_vertical_prebook_contract'
down_revision='0126_travel_operational_facts'
branch_labels=None
depends_on=None


def upgrade():
    op.create_table('vertical_prebook_contract',
        sa.Column('prebook_id',sa.String(64),primary_key=True,nullable=False),
        sa.Column('vertical',sa.String(16),nullable=False),
        sa.Column('issued_account_id',sa.String(64)),
        sa.Column('owner_id',sa.String(64)),
        sa.Column('order_id',sa.String(64)),
        sa.Column('state',sa.String(16),nullable=False),
        sa.Column('terms_json',sa.JSON(),nullable=False),
        sa.Column('terms_hash',sa.String(64),nullable=False),
        sa.Column('consumed_hash',sa.String(64)),
        sa.Column('expires_ms',sa.BigInteger(),nullable=False),
        sa.Column('created_ms',sa.BigInteger(),nullable=False),
        sa.Column('consumed_ms',sa.BigInteger()),
        sa.UniqueConstraint('vertical','order_id',name='uq_vertical_prebook_order'),
        sa.CheckConstraint("state IN ('QUOTED','CONSUMED')",name='ck_vertical_prebook_contract_state'))
    op.create_index('ix_vertical_prebook_contract_vertical','vertical_prebook_contract',['vertical'])
    op.create_index('ix_vertical_prebook_contract_owner_id','vertical_prebook_contract',['owner_id'])


def downgrade():
    if op.get_bind().scalar(sa.text('SELECT count(*) FROM vertical_prebook_contract')):
        raise RuntimeError('PREBOOK_CONTRACT_DATA_PRESENT_RESTORE_BACKUP_FOR_DOWNGRADE')
    op.drop_table('vertical_prebook_contract')
