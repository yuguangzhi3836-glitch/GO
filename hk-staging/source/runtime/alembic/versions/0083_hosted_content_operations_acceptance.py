from alembic import op
from go_hotel.db.models import Base
revision='0083_396ac652da7a';down_revision='0082_452aa445e8f7';branch_labels=None;depends_on=None
TABLES=['hosted_content_snapshot','hosted_content_approval','hosted_media_asset']
def upgrade():
 bind=op.get_bind()
 for n in TABLES:Base.metadata.tables[n].create(bind,checkfirst=True)
def downgrade():
 bind=op.get_bind()
 for n in reversed(TABLES):Base.metadata.tables[n].drop(bind,checkfirst=True)
