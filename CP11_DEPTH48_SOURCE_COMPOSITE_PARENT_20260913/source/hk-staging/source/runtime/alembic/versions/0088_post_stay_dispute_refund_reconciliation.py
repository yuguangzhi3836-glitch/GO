from alembic import op
from go_hotel.db.models import Base
revision='0088_226558bdb985';down_revision='0087_c049d2c650d7';branch_labels=None;depends_on=None
TABLES=['post_stay_dispute_case','post_stay_dispute_evidence','post_stay_dispute_communication','post_stay_mediation','post_stay_decision','refund_eligibility','post_stay_reconciliation']
def upgrade():
 bind=op.get_bind()
 for n in TABLES:Base.metadata.tables[n].create(bind,checkfirst=True)
def downgrade():
 bind=op.get_bind()
 for n in reversed(TABLES):Base.metadata.tables[n].drop(bind,checkfirst=True)
