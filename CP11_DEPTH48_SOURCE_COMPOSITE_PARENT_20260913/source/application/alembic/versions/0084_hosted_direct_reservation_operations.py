from alembic import op
from go_hotel.db.models import Base
revision='0084_bee2eab998ec';down_revision='0083_396ac652da7a';branch_labels=None;depends_on=None
TABLES=['hosted_inventory_day','hosted_rate_calendar_day','hosted_reservation_stay','hosted_reservation_night','hosted_reservation_notification']
def upgrade():
 bind=op.get_bind()
 for n in TABLES:Base.metadata.tables[n].create(bind,checkfirst=True)
def downgrade():
 bind=op.get_bind()
 for n in reversed(TABLES):Base.metadata.tables[n].drop(bind,checkfirst=True)
