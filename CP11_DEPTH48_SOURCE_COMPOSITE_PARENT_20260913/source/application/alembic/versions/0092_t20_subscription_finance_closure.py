from alembic import op
from go_hotel.db.models import Base
revision='0092_d6ac03c98590';down_revision='0091_go_offer_order_handoff';branch_labels=None;depends_on=None
TABLES=['t20_qualifying_order','supplier_commercial_cohort','subscription_invoice','subscription_waiver','commercial_audit_event']
def upgrade():
 bind=op.get_bind()
 for n in TABLES:Base.metadata.tables[n].create(bind,checkfirst=True)
def downgrade():
 bind=op.get_bind()
 for n in reversed(TABLES):Base.metadata.tables[n].drop(bind,checkfirst=True)
