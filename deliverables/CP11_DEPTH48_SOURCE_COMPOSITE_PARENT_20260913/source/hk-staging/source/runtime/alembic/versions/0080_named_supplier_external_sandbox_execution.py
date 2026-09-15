"""Named supplier adapters and external sandbox execution gate."""
from alembic import op
from go_hotel.db.models import Base
revision='0080_2cb588879e4e'
down_revision='0079_3211684dd25f'
branch_labels=None
depends_on=None
TABLES=['named_supplier_adapter','named_supplier_adapter_binding','external_sandbox_execution_authorization','external_sandbox_execution_attempt','external_sandbox_transport_evidence','external_sandbox_execution_decision']
def upgrade():
 bind=op.get_bind()
 for name in TABLES:Base.metadata.tables[name].create(bind,checkfirst=True)
def downgrade():
 bind=op.get_bind()
 for name in reversed(TABLES):Base.metadata.tables[name].drop(bind,checkfirst=True)
