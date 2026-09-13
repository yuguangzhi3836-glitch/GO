"""First GO-hosted hotel direct-booking pilot."""
from alembic import op
from go_hotel.db.models import Base
revision='0081_d921b0671c22'
down_revision='0080_2cb588879e4e'
branch_labels=None
depends_on=None
TABLES=['hosted_direct_hotel','hosted_direct_room_offer','hosted_direct_reservation','hosted_direct_reservation_event','hosted_direct_payment_readiness']
def upgrade():
 bind=op.get_bind()
 for n in TABLES:Base.metadata.tables[n].create(bind,checkfirst=True)
def downgrade():
 bind=op.get_bind()
 for n in reversed(TABLES):Base.metadata.tables[n].drop(bind,checkfirst=True)
