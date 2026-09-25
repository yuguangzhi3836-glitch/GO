"""Durable supplier hotel-library import authorization and idempotency."""
from alembic import op
import sqlalchemy as sa

revision='0138_supplier_library_import'
down_revision='0137_hosted_unknown_episode'
branch_labels=None
depends_on=None

def upgrade():
    op.create_table('hotel_partner_import_authorization',
        sa.Column('authorization_id',sa.String(64),primary_key=True),
        sa.Column('property_id',sa.String(64),nullable=False,index=True),
        sa.Column('supplier_id',sa.String(64),nullable=False,index=True),
        sa.Column('provider',sa.String(32),nullable=False,index=True),
        sa.Column('state_hash',sa.String(64),nullable=False,unique=True),
        sa.Column('status',sa.String(24),nullable=False,index=True),
        sa.Column('requested_by',sa.String(64),nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('expires_at',sa.DateTime(timezone=True),nullable=False,index=True),
        sa.Column('consumed_at',sa.DateTime(timezone=True)))
    op.create_table('hotel_partner_import_job',
        sa.Column('import_job_id',sa.String(64),primary_key=True),
        sa.Column('property_id',sa.String(64),nullable=False,index=True),
        sa.Column('supplier_id',sa.String(64),nullable=False,index=True),
        sa.Column('provider',sa.String(32),nullable=False,index=True),
        sa.Column('method',sa.String(32),nullable=False),
        sa.Column('idempotency_key',sa.String(160),nullable=False),
        sa.Column('request_hash',sa.String(64),nullable=False),
        sa.Column('status',sa.String(24),nullable=False,index=True),
        sa.Column('result_json',sa.JSON(),nullable=False),
        sa.Column('error_code',sa.String(96)),
        sa.Column('created_by',sa.String(64),nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('completed_at',sa.DateTime(timezone=True)),
        sa.UniqueConstraint('supplier_id','property_id','idempotency_key',name='uq_partner_import_idempotency'))

def downgrade():
    bind = op.get_bind()
    for table in ('hotel_partner_import_job', 'hotel_partner_import_authorization'):
        if bind.execute(sa.text(f'SELECT COUNT(*) FROM {table}')).scalar():
            raise RuntimeError('SUPPLIER_IMPORT_DOWNGRADE_DATA_PRESENT')
    op.drop_table('hotel_partner_import_job')
    op.drop_table('hotel_partner_import_authorization')
