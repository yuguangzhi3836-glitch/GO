"""External supplier credentialed sandbox certification and evidence import."""
from alembic import op
from go_hotel.db.models import Base
revision='0079_3211684dd25f'
down_revision='0078_e79db192807d'
branch_labels=None
depends_on=None
TABLES=['external_sandbox_supplier_intake','external_sandbox_credential_binding','external_sandbox_certification_suite','external_sandbox_certification_run','external_sandbox_evidence_import','external_sandbox_callback_proof','external_sandbox_certification_decision']
def upgrade():
 bind=op.get_bind()
 for name in TABLES:Base.metadata.tables[name].create(bind,checkfirst=True)
def downgrade():
 bind=op.get_bind()
 for name in reversed(TABLES):Base.metadata.tables[name].drop(bind,checkfirst=True)
