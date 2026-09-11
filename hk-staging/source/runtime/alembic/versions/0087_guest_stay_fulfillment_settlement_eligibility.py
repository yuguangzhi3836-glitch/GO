from alembic import op
from go_hotel.db.models import Base
revision='0087_c049d2c650d7';down_revision='0086_01748f3984db';branch_labels=None;depends_on=None
TABLES=['guest_stay_lifecycle','guest_identity_evidence','guest_stay_event','stay_fulfillment_evidence','stay_dispute','settlement_eligibility_decision']
def upgrade():
 bind=op.get_bind()
 for n in TABLES:Base.metadata.tables[n].create(bind,checkfirst=True)
def downgrade():
 bind=op.get_bind()
 for n in reversed(TABLES):Base.metadata.tables[n].drop(bind,checkfirst=True)
