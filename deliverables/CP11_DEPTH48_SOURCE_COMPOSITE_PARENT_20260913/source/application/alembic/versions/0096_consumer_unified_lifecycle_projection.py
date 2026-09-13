from alembic import op
from go_hotel.db.models import Base
revision='0096_e63794766c0d';down_revision='0095_59ac5a29f1d5';branch_labels=None;depends_on=None
TABLES=['consumer_unified_lifecycle','consumer_unified_lifecycle_event']
def upgrade():
 bind=op.get_bind()
 for n in TABLES:Base.metadata.tables[n].create(bind,checkfirst=True)
def downgrade():
 bind=op.get_bind()
 for n in reversed(TABLES):Base.metadata.tables[n].drop(bind,checkfirst=True)
