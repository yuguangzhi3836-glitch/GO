from alembic import op
from go_hotel.db.models import Base
revision='0094_c3116e73c367';down_revision='0093_f656e2fd0f65';branch_labels=None;depends_on=None
TABLES=['omnichannel_money_movement','finance_close_batch','finance_close_line']
def upgrade():
 bind=op.get_bind()
 for n in TABLES:Base.metadata.tables[n].create(bind,checkfirst=True)
def downgrade():
 bind=op.get_bind()
 for n in reversed(TABLES):Base.metadata.tables[n].drop(bind,checkfirst=True)
