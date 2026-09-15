"""GO Good Hotel Standard Registry + Judgment binding."""
from alembic import op
import sqlalchemy as sa
from go_hotel.db.models import Base
revision='0074_good_hotel_standard';down_revision='0073_commercial_os';branch_labels=None;depends_on=None
TABLES=['good_hotel_standard_version','good_hotel_standard_assessment','good_hotel_standard_governance_event']
def upgrade():
 bind=op.get_bind()
 for name in TABLES:Base.metadata.tables[name].create(bind,checkfirst=True)
 op.add_column('judgment_runtime',sa.Column('good_hotel_standard_version_id',sa.String(64),nullable=True))
 op.create_index('ix_judgment_runtime_good_hotel_standard_version_id','judgment_runtime',['good_hotel_standard_version_id'])
 op.add_column('recommendation_decision_runtime',sa.Column('good_hotel_standard_version_id',sa.String(64),nullable=True))
 op.create_index('ix_recommendation_decision_gohs_version_id','recommendation_decision_runtime',['good_hotel_standard_version_id'])
def downgrade():
 op.drop_index('ix_recommendation_decision_gohs_version_id',table_name='recommendation_decision_runtime');op.drop_column('recommendation_decision_runtime','good_hotel_standard_version_id')
 op.drop_index('ix_judgment_runtime_good_hotel_standard_version_id',table_name='judgment_runtime');op.drop_column('judgment_runtime','good_hotel_standard_version_id')
 bind=op.get_bind()
 for name in reversed(TABLES):Base.metadata.tables[name].drop(bind,checkfirst=True)
