from alembic import op
from go_hotel.db.models import Base

revision='0097_vertical_source_runtime'
down_revision='0096_e63794766c0d'
branch_labels=None
depends_on=None

TABLES=['vertical_source_decision']

def upgrade():
    bind=op.get_bind()
    for name in TABLES:
        Base.metadata.tables[name].create(bind,checkfirst=True)

def downgrade():
    bind=op.get_bind()
    for name in reversed(TABLES):
        Base.metadata.tables[name].drop(bind,checkfirst=True)
