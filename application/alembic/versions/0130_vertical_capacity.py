"""Shared isolated rail/attraction capacity; legacy orders are not fabricated."""
from alembic import op
import sqlalchemy as sa
revision='0130_vertical_capacity'
down_revision='0129_rail_change_resolution'
branch_labels=None
depends_on=None


def upgrade():
    op.create_table('vertical_capacity_bucket',
        sa.Column('bucket_id',sa.String(64),primary_key=True),
        sa.Column('vertical',sa.String(16),nullable=False),
        sa.Column('resource_json',sa.JSON(),nullable=False),
        sa.Column('capacity',sa.Integer(),nullable=False),
        sa.Column('allocated',sa.Integer(),nullable=False),
        sa.CheckConstraint("vertical IN ('RAIL','ATTRACTION')",name='ck_capacity_vertical'),
        sa.CheckConstraint('capacity >= 0 AND allocated >= 0 AND allocated <= capacity',name='ck_capacity_bounds'))
    op.create_table('vertical_capacity_claim',
        sa.Column('vertical',sa.String(16),primary_key=True),
        sa.Column('order_id',sa.String(64),primary_key=True),
        sa.Column('slot',sa.String(64),primary_key=True),
        sa.Column('bucket_id',sa.String(64),sa.ForeignKey('vertical_capacity_bucket.bucket_id'),nullable=False),
        sa.Column('quantity',sa.Integer(),nullable=False),
        sa.Column('state',sa.String(16),nullable=False),
        sa.Column('created_ms',sa.BigInteger(),nullable=False),
        sa.Column('released_ms',sa.BigInteger()),
        sa.CheckConstraint("state IN ('ALLOCATED','RELEASED')",name='ck_capacity_claim_state'),
        sa.CheckConstraint('quantity > 0',name='ck_capacity_claim_quantity'))
    op.create_index('ix_vertical_capacity_claim_bucket_id','vertical_capacity_claim',['bucket_id'])


def downgrade():
    bind=op.get_bind()
    if bind.scalar(sa.text('SELECT count(*) FROM vertical_capacity_claim')) or bind.scalar(sa.text('SELECT count(*) FROM vertical_capacity_bucket WHERE allocated <> 0')):
        raise RuntimeError('CAPACITY_DATA_PRESENT_RESTORE_BACKUP_FOR_DOWNGRADE')
    op.drop_index('ix_vertical_capacity_claim_bucket_id',table_name='vertical_capacity_claim')
    op.drop_table('vertical_capacity_claim');op.drop_table('vertical_capacity_bucket')
