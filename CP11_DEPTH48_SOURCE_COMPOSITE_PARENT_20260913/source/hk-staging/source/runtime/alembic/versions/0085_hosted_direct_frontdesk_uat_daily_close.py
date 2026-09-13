from alembic import op
from go_hotel.db.models import Base
revision='0085_bfa53313a4e7';down_revision='0084_bee2eab998ec';branch_labels=None;depends_on=None
TABLES=['hosted_staff_role','hosted_shift_handover','hosted_sla_escalation','hosted_action_approval','hosted_daily_close','hosted_uat_scenario','hosted_guest_access_audit']
def upgrade():
 bind=op.get_bind()
 for n in TABLES:Base.metadata.tables[n].create(bind,checkfirst=True)
def downgrade():
 bind=op.get_bind()
 for n in reversed(TABLES):Base.metadata.tables[n].drop(bind,checkfirst=True)
