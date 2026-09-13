"""Sprint 3D attractions and experiences vertical
Revision ID: 0025_sprint3d
Revises: 0024_sprint3c
"""
from alembic import op
import sqlalchemy as sa
revision="0025_sprint3d"
down_revision="0024_sprint3c"
branch_labels=None
depends_on=None
def upgrade():
 op.create_table("attraction_order_runtime",sa.Column("order_id",sa.String(64),primary_key=True),sa.Column("account_id",sa.String(64),nullable=False),sa.Column("status",sa.String(32),nullable=False),sa.Column("product_id",sa.String(64),nullable=False),sa.Column("product_name",sa.String(255),nullable=False),sa.Column("product_type",sa.String(24),nullable=False),sa.Column("destination",sa.String(128),nullable=False),sa.Column("visit_date",sa.String(24),nullable=False),sa.Column("session_time",sa.String(24)),sa.Column("ticket_type",sa.String(64),nullable=False),sa.Column("quantity",sa.Integer,nullable=False),sa.Column("eligibility",sa.JSON,nullable=False),sa.Column("voucher_type",sa.String(24),nullable=False),sa.Column("voucher_code",sa.String(128)),sa.Column("total_amount_minor",sa.BigInteger,nullable=False),sa.Column("currency",sa.String(3),nullable=False),sa.Column("attendees",sa.JSON,nullable=False),sa.Column("supplier_reference",sa.String(64)),sa.Column("created_at",sa.DateTime,nullable=False),sa.Column("updated_at",sa.DateTime,nullable=False))
 op.create_index("ix_attraction_order_account","attraction_order_runtime",["account_id"]);op.create_index("ix_attraction_order_status","attraction_order_runtime",["status"]);op.create_index("ix_attraction_order_product","attraction_order_runtime",["product_id"])
 op.create_table("attraction_change_quote_runtime",sa.Column("quote_id",sa.String(64),primary_key=True),sa.Column("order_id",sa.String(64),nullable=False),sa.Column("new_visit_date",sa.String(24),nullable=False),sa.Column("new_session_time",sa.String(24)),sa.Column("change_fee_minor",sa.BigInteger,nullable=False,server_default="0"),sa.Column("total_due_minor",sa.BigInteger,nullable=False,server_default="0"),sa.Column("currency",sa.String(3),nullable=False),sa.Column("status",sa.String(24),nullable=False),sa.Column("expires_at",sa.DateTime,nullable=False),sa.Column("created_at",sa.DateTime,nullable=False));op.create_index("ix_attraction_change_order","attraction_change_quote_runtime",["order_id"])
 op.create_table("attraction_refund_runtime",sa.Column("refund_id",sa.String(64),primary_key=True),sa.Column("order_id",sa.String(64),nullable=False),sa.Column("refund_fee_minor",sa.BigInteger,nullable=False,server_default="0"),sa.Column("refund_amount_minor",sa.BigInteger,nullable=False),sa.Column("currency",sa.String(3),nullable=False),sa.Column("status",sa.String(32),nullable=False),sa.Column("created_at",sa.DateTime,nullable=False),sa.Column("completed_at",sa.DateTime));op.create_index("ix_attraction_refund_order","attraction_refund_runtime",["order_id"]);op.create_index("ix_attraction_refund_status","attraction_refund_runtime",["status"])
def downgrade():
 op.drop_table("attraction_refund_runtime");op.drop_table("attraction_change_quote_runtime");op.drop_table("attraction_order_runtime")
