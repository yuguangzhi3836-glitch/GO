"""Commercial Constitution Policy Engine + GO Admin Commercial OS."""
from alembic import op
from go_hotel.db.models import Base
revision='0073_commercial_os';down_revision='0072_partner_core';branch_labels=None;depends_on=None
TABLES=['commercial_policy_version','commercial_decision','commercial_evidence','supplier_subscription','distribution_authority','commercial_pool_membership','hotel_net_guard_assessment','commercial_case']
def upgrade():
    bind=op.get_bind()
    for name in TABLES:Base.metadata.tables[name].create(bind,checkfirst=True)
def downgrade():
    bind=op.get_bind()
    for name in reversed(TABLES):Base.metadata.tables[name].drop(bind,checkfirst=True)
