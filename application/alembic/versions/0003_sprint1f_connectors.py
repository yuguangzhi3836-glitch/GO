"""Sprint 1F connector framework, certification and reconciliation
Revision ID: 0003_sprint1f
Revises: 0002_sprint1e
"""
from alembic import op
import sqlalchemy as sa
revision='0003_sprint1f'; down_revision='0002_sprint1e'; branch_labels=None; depends_on=None

def upgrade():
    op.create_table('connector_certification',
        sa.Column('certification_id',sa.Integer(),primary_key=True,autoincrement=True),
        sa.Column('connector_id',sa.String(64),nullable=False), sa.Column('passed',sa.Boolean(),nullable=False),
        sa.Column('report',sa.JSON(),nullable=False), sa.Column('certified_at',sa.DateTime(timezone=True),nullable=False))
    op.create_index('ix_connector_certification_connector_id','connector_certification',['connector_id'])
    op.create_table('connector_health',
        sa.Column('connector_id',sa.String(64),primary_key=True), sa.Column('healthy',sa.Boolean(),nullable=False),
        sa.Column('detail',sa.JSON(),nullable=False), sa.Column('checked_at',sa.DateTime(timezone=True),nullable=False))
    op.create_table('connector_reconciliation',
        sa.Column('reconciliation_id',sa.Integer(),primary_key=True,autoincrement=True), sa.Column('order_id',sa.String(64),nullable=False),
        sa.Column('connector_id',sa.String(64),nullable=False), sa.Column('local_status',sa.String(32),nullable=False),
        sa.Column('external_status',sa.String(32)), sa.Column('result',sa.String(24),nullable=False), sa.Column('error',sa.Text()),
        sa.Column('checked_at',sa.DateTime(timezone=True),nullable=False))
    op.create_index('ix_connector_reconciliation_order_id','connector_reconciliation',['order_id'])
    op.create_index('ix_connector_reconciliation_connector_id','connector_reconciliation',['connector_id'])
    op.create_index('ix_connector_reconciliation_result','connector_reconciliation',['result'])

def downgrade():
    op.drop_table('connector_reconciliation'); op.drop_table('connector_health'); op.drop_table('connector_certification')
