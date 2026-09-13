"""Sprint 1Q operational dashboard supplier identity and indexes.

Revision ID: 0014_sprint1q
Revises: 0013_sprint1p
"""
from alembic import op
import sqlalchemy as sa

revision = '0014_sprint1q'
down_revision = '0013_sprint1p'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('offer_snapshot', sa.Column('supplier_id', sa.String(length=64), nullable=True))
    op.create_index('ix_offer_snapshot_supplier_id', 'offer_snapshot', ['supplier_id'])
    op.add_column('hotel_order_runtime', sa.Column('supplier_id', sa.String(length=64), nullable=True))
    op.create_index('ix_hotel_order_runtime_supplier_id', 'hotel_order_runtime', ['supplier_id'])
    op.create_index('ix_order_supplier_status_updated', 'hotel_order_runtime', ['supplier_id','status','updated_at'])
    op.create_index('ix_refund_status_created', 'refund_runtime', ['status','created_at'])
    op.create_index('ix_stay_credit_status_expiry', 'stay_credit_runtime', ['status','expires_at'])
    op.create_index('ix_risk_status_updated', 'risk_event_runtime', ['status','updated_at'])
    op.create_index('ix_liability_status_created', 'supplier_liability_runtime', ['status','created_at'])
    op.create_index('ix_judgment_status_created', 'judgment_runtime', ['status','created_at'])


def downgrade() -> None:
    op.drop_index('ix_judgment_status_created', table_name='judgment_runtime')
    op.drop_index('ix_liability_status_created', table_name='supplier_liability_runtime')
    op.drop_index('ix_risk_status_updated', table_name='risk_event_runtime')
    op.drop_index('ix_stay_credit_status_expiry', table_name='stay_credit_runtime')
    op.drop_index('ix_refund_status_created', table_name='refund_runtime')
    op.drop_index('ix_order_supplier_status_updated', table_name='hotel_order_runtime')
    op.drop_index('ix_hotel_order_runtime_supplier_id', table_name='hotel_order_runtime')
    op.drop_column('hotel_order_runtime', 'supplier_id')
    op.drop_index('ix_offer_snapshot_supplier_id', table_name='offer_snapshot')
    op.drop_column('offer_snapshot', 'supplier_id')
