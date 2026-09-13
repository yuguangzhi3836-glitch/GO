from alembic import op
from go_hotel.db.models import Base
revision='0086_01748f3984db';down_revision='0085_bfa53313a4e7';branch_labels=None;depends_on=None
TABLES=['alipay_merchant_binding','alipay_credential_binding','alipay_authorization','alipay_safeguarded_event','alipay_adjustment_approval','alipay_reconciliation']
def upgrade():
 bind=op.get_bind()
 for n in TABLES:Base.metadata.tables[n].create(bind,checkfirst=True)
def downgrade():
 bind=op.get_bind()
 for n in reversed(TABLES):Base.metadata.tables[n].drop(bind,checkfirst=True)
