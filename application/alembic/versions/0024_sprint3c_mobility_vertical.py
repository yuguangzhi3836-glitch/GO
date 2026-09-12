"""Sprint 3C mobility: ride + rent-a-car.
Revision ID: 0024_sprint3c
Revises: 0023_sprint3b
"""
from alembic import op
import sqlalchemy as sa
revision="0024_sprint3c"; down_revision="0023_sprint3b"; branch_labels=None; depends_on=None
def upgrade():
 op.create_table("mobility_ride_order_runtime",sa.Column("order_id",sa.String(64),primary_key=True),sa.Column("account_id",sa.String(64),nullable=False),sa.Column("status",sa.String(32),nullable=False),sa.Column("pickup",sa.String(255),nullable=False),sa.Column("dropoff",sa.String(255),nullable=False),sa.Column("pickup_at",sa.String(40),nullable=False),sa.Column("vehicle_class",sa.String(40),nullable=False),sa.Column("total_amount_minor",sa.BigInteger(),nullable=False),sa.Column("currency",sa.String(3),nullable=False),sa.Column("passengers",sa.JSON(),nullable=False),sa.Column("flight_no",sa.String(24)),sa.Column("supplier_reference",sa.String(32)),sa.Column("created_at",sa.DateTime(),nullable=False),sa.Column("updated_at",sa.DateTime(),nullable=False))
 op.create_table("mobility_rental_order_runtime",sa.Column("order_id",sa.String(64),primary_key=True),sa.Column("account_id",sa.String(64),nullable=False),sa.Column("status",sa.String(32),nullable=False),sa.Column("pickup_location",sa.String(255),nullable=False),sa.Column("return_location",sa.String(255),nullable=False),sa.Column("pickup_at",sa.String(40),nullable=False),sa.Column("return_at",sa.String(40),nullable=False),sa.Column("vehicle_class",sa.String(40),nullable=False),sa.Column("insurance",sa.JSON(),nullable=False),sa.Column("mileage",sa.JSON(),nullable=False),sa.Column("deposit_minor",sa.BigInteger(),nullable=False),sa.Column("total_amount_minor",sa.BigInteger(),nullable=False),sa.Column("currency",sa.String(3),nullable=False),sa.Column("drivers",sa.JSON(),nullable=False),sa.Column("supplier_reference",sa.String(32)),sa.Column("created_at",sa.DateTime(),nullable=False),sa.Column("updated_at",sa.DateTime(),nullable=False))
 op.create_table("mobility_refund_runtime",sa.Column("refund_id",sa.String(64),primary_key=True),sa.Column("order_id",sa.String(64),nullable=False),sa.Column("vertical",sa.String(16),nullable=False),sa.Column("fee_minor",sa.BigInteger(),nullable=False),sa.Column("refund_amount_minor",sa.BigInteger(),nullable=False),sa.Column("currency",sa.String(3),nullable=False),sa.Column("status",sa.String(32),nullable=False),sa.Column("created_at",sa.DateTime(),nullable=False))
def downgrade():
 for t in ["mobility_refund_runtime","mobility_rental_order_runtime","mobility_ride_order_runtime"]: op.drop_table(t)
