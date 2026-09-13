"""Sprint 3E unified GO Trips and multi-vertical journey
Revision ID: 0026_sprint3e
Revises: 0025_sprint3d
"""
from alembic import op
import sqlalchemy as sa
revision="0026_sprint3e"
down_revision="0025_sprint3d"
branch_labels=None
depends_on=None

def upgrade():
    op.create_table("go_journey_runtime",
        sa.Column("journey_id",sa.String(64),primary_key=True),
        sa.Column("account_id",sa.String(64),nullable=False),
        sa.Column("title",sa.String(160),nullable=False),
        sa.Column("destination_summary",sa.String(255)),
        sa.Column("starts_at",sa.String(40)),sa.Column("ends_at",sa.String(40)),
        sa.Column("status",sa.String(24),nullable=False),
        sa.Column("created_at",sa.DateTime(timezone=True),nullable=False),
        sa.Column("updated_at",sa.DateTime(timezone=True),nullable=False))
    op.create_index("ix_go_journey_account","go_journey_runtime",["account_id"])
    op.create_index("ix_go_journey_starts","go_journey_runtime",["starts_at"])
    op.create_index("ix_go_journey_status","go_journey_runtime",["status"])
    op.create_table("go_journey_item_runtime",
        sa.Column("item_id",sa.String(64),primary_key=True),
        sa.Column("journey_id",sa.String(64),nullable=False),sa.Column("account_id",sa.String(64),nullable=False),
        sa.Column("vertical",sa.String(24),nullable=False),sa.Column("order_id",sa.String(64),nullable=False),
        sa.Column("title",sa.String(255),nullable=False),sa.Column("subtitle",sa.String(255)),sa.Column("location",sa.String(255)),
        sa.Column("starts_at",sa.String(40)),sa.Column("ends_at",sa.String(40)),sa.Column("status_snapshot",sa.String(32),nullable=False),
        sa.Column("facts_json",sa.JSON,nullable=False),sa.Column("detail_route",sa.String(64),nullable=False),
        sa.Column("sort_key",sa.String(64),nullable=False),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False))
    for name,col in [("ix_go_journey_item_journey","journey_id"),("ix_go_journey_item_account","account_id"),("ix_go_journey_item_vertical","vertical"),("ix_go_journey_item_order","order_id"),("ix_go_journey_item_starts","starts_at"),("ix_go_journey_item_sort","sort_key")]:
        op.create_index(name,"go_journey_item_runtime",[col])
    op.create_index("ux_go_journey_order_once","go_journey_item_runtime",["account_id","vertical","order_id"],unique=True)

def downgrade():
    op.drop_table("go_journey_item_runtime")
    op.drop_table("go_journey_runtime")
