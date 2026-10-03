"""Index the source reservation check performed on every new money movement.

Standard transactional index creation blocks writes while building. Schedule
this migration explicitly; this revision does not authorize a live rollout.
"""
from alembic import op

revision = '0135_credit_source_intent_index'
down_revision = '0134_flight_status_width'
branch_labels = None
depends_on = None


def upgrade():
    op.create_index('ix_catalog_credit_source_payment_intent_id',
                    'catalog_credit_source', ['payment_intent_id'], unique=False)


def downgrade():
    op.drop_index('ix_catalog_credit_source_payment_intent_id',
                  table_name='catalog_credit_source')
