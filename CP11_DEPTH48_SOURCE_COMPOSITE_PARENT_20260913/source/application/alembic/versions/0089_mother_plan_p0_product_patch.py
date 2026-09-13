from alembic import op
from go_hotel.db.models import Base
revision='0089_24184f9074aa';down_revision='0088_226558bdb985';branch_labels=None;depends_on=None
TABLES=['flight_check_in_state','flight_check_in_event','ride_flight_tracking_binding','ride_flight_sync_event','go_offer_requirement','go_offer_quote']
def upgrade():
 bind=op.get_bind()
 for n in TABLES:Base.metadata.tables[n].create(bind,checkfirst=True)
def downgrade():
 bind=op.get_bind()
 for n in reversed(TABLES):Base.metadata.tables[n].drop(bind,checkfirst=True)
