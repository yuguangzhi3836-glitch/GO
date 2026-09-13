"""Sprint 1M persistent cancellation/refund/change/stay-credit runtime

Revision ID: 0010_sprint1m
Revises: 0009_sprint1l
"""
from alembic import op
import sqlalchemy as sa

revision="0010_sprint1m"
down_revision="0009_sprint1l"
branch_labels=None
depends_on=None

def upgrade():
    op.create_table("hotel_fare_rule_runtime",
        sa.Column("fare_rule_id",sa.String(64),primary_key=True),sa.Column("fare_family",sa.String(32),nullable=False),sa.Column("cooling_off_minutes",sa.Integer(),nullable=False),sa.Column("change_allowed",sa.Boolean(),nullable=False),sa.Column("change_fee_minor",sa.BigInteger(),nullable=False),sa.Column("stay_credit_allowed",sa.Boolean(),nullable=False),sa.Column("stay_credit_validity_days",sa.Integer(),nullable=False),sa.Column("stay_credit_scope",sa.String(32),nullable=False),sa.Column("tiers_json",sa.JSON(),nullable=False),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False))
    op.create_table("cancellation_quote",
        sa.Column("quote_id",sa.String(64),primary_key=True),sa.Column("order_id",sa.String(64),nullable=False),sa.Column("paid_amount_minor",sa.BigInteger(),nullable=False),sa.Column("cancellation_fee_minor",sa.BigInteger(),nullable=False),sa.Column("refund_amount_minor",sa.BigInteger(),nullable=False),sa.Column("rule_snapshot",sa.JSON(),nullable=False),sa.Column("expires_at",sa.DateTime(timezone=True),nullable=False),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False))
    op.create_index("ix_cancel_quote_order","cancellation_quote",["order_id"])
    op.create_table("refund_runtime",
        sa.Column("refund_id",sa.String(64),primary_key=True),sa.Column("order_id",sa.String(64),nullable=False),sa.Column("payment_id",sa.String(64),nullable=False),sa.Column("amount_minor",sa.BigInteger(),nullable=False),sa.Column("currency",sa.String(3),nullable=False),sa.Column("provider_refund_id",sa.String(128)),sa.Column("status",sa.String(32),nullable=False),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False),sa.Column("completed_at",sa.DateTime(timezone=True)))
    op.create_index("ix_refund_runtime_order","refund_runtime",["order_id"]); op.create_index("ix_refund_runtime_status","refund_runtime",["status"])
    op.create_table("change_quote",
        sa.Column("quote_id",sa.String(64),primary_key=True),sa.Column("order_id",sa.String(64),nullable=False),sa.Column("new_check_in",sa.String(10),nullable=False),sa.Column("new_check_out",sa.String(10),nullable=False),sa.Column("old_value_minor",sa.BigInteger(),nullable=False),sa.Column("new_value_minor",sa.BigInteger(),nullable=False),sa.Column("fare_difference_minor",sa.BigInteger(),nullable=False),sa.Column("change_fee_minor",sa.BigInteger(),nullable=False),sa.Column("amount_due_minor",sa.BigInteger(),nullable=False),sa.Column("rule_snapshot",sa.JSON(),nullable=False),sa.Column("expires_at",sa.DateTime(timezone=True),nullable=False),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False))
    op.create_index("ix_change_quote_order","change_quote",["order_id"])
    op.create_table("order_change_runtime",
        sa.Column("change_id",sa.String(64),primary_key=True),sa.Column("order_id",sa.String(64),nullable=False),sa.Column("quote_id",sa.String(64),nullable=False,unique=True),sa.Column("new_check_in",sa.String(10),nullable=False),sa.Column("new_check_out",sa.String(10),nullable=False),sa.Column("additional_payment_minor",sa.BigInteger(),nullable=False),sa.Column("status",sa.String(32),nullable=False),sa.Column("supplier_confirmation_no",sa.String(128)),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False),sa.Column("confirmed_at",sa.DateTime(timezone=True)))
    op.create_index("ix_order_change_order","order_change_runtime",["order_id"]); op.create_index("ix_order_change_status","order_change_runtime",["status"])
    op.create_table("stay_credit_runtime",
        sa.Column("stay_credit_id",sa.String(64),primary_key=True),sa.Column("original_order_id",sa.String(64),nullable=False,unique=True),sa.Column("account_id",sa.String(64),nullable=False),sa.Column("property_id",sa.String(64),nullable=False),sa.Column("credit_value_minor",sa.BigInteger(),nullable=False),sa.Column("currency",sa.String(3),nullable=False),sa.Column("valid_from",sa.DateTime(timezone=True),nullable=False),sa.Column("expires_at",sa.DateTime(timezone=True),nullable=False),sa.Column("status",sa.String(32),nullable=False),sa.Column("redemption_order_id",sa.String(64)),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False),sa.Column("redeemed_at",sa.DateTime(timezone=True)))
    op.create_index("ix_stay_credit_property","stay_credit_runtime",["property_id"]); op.create_index("ix_stay_credit_status","stay_credit_runtime",["status"]); op.create_index("ix_stay_credit_account","stay_credit_runtime",["account_id"])
    op.create_table("stay_credit_redemption_quote",
        sa.Column("quote_id",sa.String(64),primary_key=True),sa.Column("stay_credit_id",sa.String(64),nullable=False),sa.Column("offer_id",sa.String(64),nullable=False),sa.Column("new_value_minor",sa.BigInteger(),nullable=False),sa.Column("credit_value_minor",sa.BigInteger(),nullable=False),sa.Column("amount_due_minor",sa.BigInteger(),nullable=False),sa.Column("forfeited_difference_minor",sa.BigInteger(),nullable=False),sa.Column("expires_at",sa.DateTime(timezone=True),nullable=False),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False))
    op.create_index("ix_stay_credit_redemption_quote_credit","stay_credit_redemption_quote",["stay_credit_id"])

def downgrade():
    op.drop_table("stay_credit_redemption_quote"); op.drop_table("stay_credit_runtime"); op.drop_table("order_change_runtime"); op.drop_table("change_quote"); op.drop_table("refund_runtime"); op.drop_table("cancellation_quote"); op.drop_table("hotel_fare_rule_runtime")
