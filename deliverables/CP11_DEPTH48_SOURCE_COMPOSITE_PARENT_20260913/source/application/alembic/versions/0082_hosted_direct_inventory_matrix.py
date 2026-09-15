from alembic import op
from go_hotel.db.models import Base
revision='0082_452aa445e8f7';down_revision='0081_d921b0671c22';branch_labels=None;depends_on=None
TABLES=['hosted_direct_inventory_pool','hosted_direct_rate_variant']
def upgrade():
 bind=op.get_bind()
 for n in TABLES:Base.metadata.tables[n].create(bind,checkfirst=True)
def downgrade():
 bind=op.get_bind()
 for n in reversed(TABLES):Base.metadata.tables[n].drop(bind,checkfirst=True)
