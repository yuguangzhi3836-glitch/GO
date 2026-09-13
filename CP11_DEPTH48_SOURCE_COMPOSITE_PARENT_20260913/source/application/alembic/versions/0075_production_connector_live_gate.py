"""Production Connector Registry + Certification + Live Gate."""
from alembic import op
from go_hotel.db.models import Base
revision='0075_442bc0d513d1'
down_revision='0074_good_hotel_standard'
branch_labels=None
depends_on=None
TABLES=['production_connector_registry','connector_capability_matrix','connector_contract_authority','connector_credential_reference','connector_certification_run','connector_runtime_health','connector_live_gate_assessment','connector_activation_change','connector_kill_switch','connector_governance_event']
def upgrade():
 bind=op.get_bind()
 for name in TABLES: Base.metadata.tables[name].create(bind,checkfirst=True)
def downgrade():
 bind=op.get_bind()
 for name in reversed(TABLES): Base.metadata.tables[name].drop(bind,checkfirst=True)
