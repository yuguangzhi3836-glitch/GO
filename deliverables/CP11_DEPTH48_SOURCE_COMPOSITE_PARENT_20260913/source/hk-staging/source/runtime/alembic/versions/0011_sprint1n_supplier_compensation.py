"""Sprint 1N supplier fault compensation and financial recovery runtime

Revision ID: 0011_sprint1n
Revises: 0010_sprint1m
"""
from alembic import op
import sqlalchemy as sa

revision="0011_sprint1n"
down_revision="0010_sprint1m"
branch_labels=None
depends_on=None

def upgrade():
    op.create_table("supplier_fault_case",
        sa.Column("case_id",sa.String(64),primary_key=True),
        sa.Column("order_id",sa.String(64),nullable=False,unique=True),
        sa.Column("supplier_id",sa.String(64),nullable=False),
        sa.Column("reason_code",sa.String(64),nullable=False),
        sa.Column("status",sa.String(40),nullable=False),
        sa.Column("fault_party",sa.String(32)),
        sa.Column("evidence_json",sa.JSON(),nullable=False),
        sa.Column("decision_json",sa.JSON()),
        sa.Column("created_at",sa.DateTime(timezone=True),nullable=False),
        sa.Column("decided_at",sa.DateTime(timezone=True)))
    op.create_index("ix_supplier_fault_case_order","supplier_fault_case",["order_id"])
    op.create_index("ix_supplier_fault_case_supplier_status","supplier_fault_case",["supplier_id","status"])

    op.create_table("supplier_financial_account",
        sa.Column("supplier_id",sa.String(64),primary_key=True),
        sa.Column("settlement_available_minor",sa.BigInteger(),nullable=False,server_default="0"),
        sa.Column("reserve_available_minor",sa.BigInteger(),nullable=False,server_default="0"),
        sa.Column("bank_available_minor",sa.BigInteger(),nullable=False,server_default="0"),
        sa.Column("debit_mandate_active",sa.Boolean(),nullable=False,server_default=sa.false()),
        sa.Column("negative_balance_minor",sa.BigInteger(),nullable=False,server_default="0"),
        sa.Column("updated_at",sa.DateTime(timezone=True),nullable=False))

    op.create_table("supplier_liability_runtime",
        sa.Column("liability_id",sa.String(64),primary_key=True),
        sa.Column("case_id",sa.String(64),nullable=False,unique=True),
        sa.Column("supplier_id",sa.String(64),nullable=False),
        sa.Column("order_id",sa.String(64),nullable=False),
        sa.Column("actual_paid_minor",sa.BigInteger(),nullable=False),
        sa.Column("refund_minor",sa.BigInteger(),nullable=False),
        sa.Column("compensation_minor",sa.BigInteger(),nullable=False),
        sa.Column("total_return_minor",sa.BigInteger(),nullable=False),
        sa.Column("settlement_offset_minor",sa.BigInteger(),nullable=False,server_default="0"),
        sa.Column("reserve_offset_minor",sa.BigInteger(),nullable=False,server_default="0"),
        sa.Column("bank_debit_minor",sa.BigInteger(),nullable=False,server_default="0"),
        sa.Column("protection_fund_minor",sa.BigInteger(),nullable=False,server_default="0"),
        sa.Column("negative_balance_minor",sa.BigInteger(),nullable=False,server_default="0"),
        sa.Column("status",sa.String(40),nullable=False),
        sa.Column("decision_id",sa.String(64),nullable=False),
        sa.Column("created_at",sa.DateTime(timezone=True),nullable=False),
        sa.Column("cleared_at",sa.DateTime(timezone=True)))
    op.create_index("ix_supplier_liability_order","supplier_liability_runtime",["order_id"])
    op.create_index("ix_supplier_liability_supplier_status","supplier_liability_runtime",["supplier_id","status"])

    op.create_table("consumer_protection_fund_ledger",
        sa.Column("entry_id",sa.String(64),primary_key=True),
        sa.Column("liability_id",sa.String(64),nullable=False),
        sa.Column("order_id",sa.String(64),nullable=False),
        sa.Column("supplier_id",sa.String(64),nullable=False),
        sa.Column("entry_type",sa.String(24),nullable=False),
        sa.Column("amount_minor",sa.BigInteger(),nullable=False),
        sa.Column("status",sa.String(24),nullable=False),
        sa.Column("created_at",sa.DateTime(timezone=True),nullable=False))
    op.create_index("ix_protection_fund_liability","consumer_protection_fund_ledger",["liability_id"])
    op.create_index("ix_protection_fund_supplier","consumer_protection_fund_ledger",["supplier_id"])

    op.create_table("compensation_payment_runtime",
        sa.Column("compensation_id",sa.String(64),primary_key=True),
        sa.Column("liability_id",sa.String(64),nullable=False),
        sa.Column("order_id",sa.String(64),nullable=False),
        sa.Column("amount_minor",sa.BigInteger(),nullable=False),
        sa.Column("currency",sa.String(3),nullable=False),
        sa.Column("source_breakdown",sa.JSON(),nullable=False),
        sa.Column("status",sa.String(32),nullable=False),
        sa.Column("created_at",sa.DateTime(timezone=True),nullable=False),
        sa.Column("completed_at",sa.DateTime(timezone=True)))
    op.create_index("ix_compensation_payment_liability","compensation_payment_runtime",["liability_id"])
    op.create_index("ix_compensation_payment_order","compensation_payment_runtime",["order_id"])

def downgrade():
    op.drop_table("compensation_payment_runtime")
    op.drop_table("consumer_protection_fund_ledger")
    op.drop_table("supplier_liability_runtime")
    op.drop_table("supplier_financial_account")
    op.drop_table("supplier_fault_case")
