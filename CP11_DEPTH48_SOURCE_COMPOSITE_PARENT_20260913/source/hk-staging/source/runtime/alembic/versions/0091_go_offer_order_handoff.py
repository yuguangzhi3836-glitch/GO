from alembic import op
from go_hotel.db.models import Base
revision='0091_go_offer_order_handoff';down_revision='0090_go_identity_entitlements';branch_labels=None;depends_on=None
TABLES=['go_offer_prebook','go_offer_order_handoff','go_offer_lifecycle_event']
def upgrade():
 bind=op.get_bind()
 for n in TABLES:Base.metadata.tables[n].create(bind,checkfirst=True)
def downgrade():
 bind=op.get_bind()
 for n in reversed(TABLES):Base.metadata.tables[n].drop(bind,checkfirst=True)
