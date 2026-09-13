from alembic import op
from go_hotel.db.models import Base
revision='0090_go_identity_entitlements';down_revision='0089_24184f9074aa';branch_labels=None;depends_on=None
TABLES=['go_identity_credential','go_identity_evidence','go_identity_event','go_identity_supplier_program','go_friends_family_invitation']
def upgrade():
 bind=op.get_bind()
 for n in TABLES:Base.metadata.tables[n].create(bind,checkfirst=True)
def downgrade():
 bind=op.get_bind()
 for n in reversed(TABLES):Base.metadata.tables[n].drop(bind,checkfirst=True)
