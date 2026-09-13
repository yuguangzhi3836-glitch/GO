from alembic import op
from go_hotel.db.models import Base
revision='0095_59ac5a29f1d5';down_revision='0094_c3116e73c367';branch_labels=None;depends_on=None
TABLES=['supplier_vertical_capability','supplier_certification_run']
def upgrade():
 bind=op.get_bind()
 for n in TABLES:Base.metadata.tables[n].create(bind,checkfirst=True)
def downgrade():
 bind=op.get_bind()
 for n in reversed(TABLES):Base.metadata.tables[n].drop(bind,checkfirst=True)
