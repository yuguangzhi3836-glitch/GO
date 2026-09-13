"""First real connector activation readiness."""
from alembic import op
from go_hotel.db.models import Base
revision='0077_0ab7798c5638'
down_revision='0076_126e14322d21'
branch_labels=None
depends_on=None
TABLES=['connector_onboarding_profile','connector_kms_binding','connector_production_account','connector_ip_allowlist','connector_webhook_endpoint','connector_readiness_certification','connector_activation_drill','connector_financial_closure','connector_activation_readiness']
def upgrade():
 bind=op.get_bind()
 for name in TABLES:Base.metadata.tables[name].create(bind,checkfirst=True)
def downgrade():
 bind=op.get_bind()
 for name in reversed(TABLES):Base.metadata.tables[name].drop(bind,checkfirst=True)
