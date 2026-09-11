"""First paired Hotel + PSP connector pilot integration."""
from alembic import op
from go_hotel.db.models import Base
revision='0078_e79db192807d'
down_revision='0077_0ab7798c5638'
branch_labels=None
depends_on=None
TABLES=['connector_pilot_pair','connector_pilot_scenario','connector_pilot_execution','connector_pilot_operation','connector_pilot_callback','connector_pilot_evidence','connector_pilot_reconciliation','connector_pilot_control']
def upgrade():
 bind=op.get_bind()
 for name in TABLES:Base.metadata.tables[name].create(bind,checkfirst=True)
def downgrade():
 bind=op.get_bind()
 for name in reversed(TABLES):Base.metadata.tables[name].drop(bind,checkfirst=True)
