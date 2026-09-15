from alembic import op
from go_hotel.db.models import Base
revision='0093_f656e2fd0f65';down_revision='0092_d6ac03c98590';branch_labels=None;depends_on=None
TABLES=['omnichannel_merchant_binding','omnichannel_payment_intent','omnichannel_payment_attempt','omnichannel_webhook_receipt','omnichannel_ledger_entry','omnichannel_reconciliation','omnichannel_payout']
def upgrade():
 bind=op.get_bind()
 for n in TABLES:Base.metadata.tables[n].create(bind,checkfirst=True)
def downgrade():
 bind=op.get_bind()
 for n in reversed(TABLES):Base.metadata.tables[n].drop(bind,checkfirst=True)
