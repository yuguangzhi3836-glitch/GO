"""Add spendable wallet cash, cashback display balance and wallet ledger."""
from alembic import op
import sqlalchemy as sa

revision = "0136_consumer_wallet_cash_ledger"
down_revision = "0135_supplier_onboarding"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("consumer_wallet", sa.Column(
        "cash_balance_minor", sa.BigInteger(), nullable=False, server_default="0"))
    op.add_column("consumer_wallet", sa.Column(
        "cashback_balance_minor", sa.BigInteger(), nullable=False, server_default="0"))
    op.create_table(
        "consumer_wallet_ledger",
        sa.Column("wallet_ledger_id", sa.String(64), primary_key=True),
        sa.Column("wallet_id", sa.String(64), nullable=False),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("order_id", sa.String(64)),
        sa.Column("entry_type", sa.String(40), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("balance_after_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="CNY"),
        sa.Column("idempotency_key", sa.String(160), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_consumer_wallet_ledger_wallet_id", "consumer_wallet_ledger", ["wallet_id"])
    op.create_index("ix_consumer_wallet_ledger_user_id", "consumer_wallet_ledger", ["user_id"])
    op.create_index("ix_consumer_wallet_ledger_order_id", "consumer_wallet_ledger", ["order_id"])
    op.create_index("ix_consumer_wallet_ledger_entry_type", "consumer_wallet_ledger", ["entry_type"])
    op.create_index("ix_consumer_wallet_ledger_created_at", "consumer_wallet_ledger", ["created_at"])
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        op.execute("CREATE TRIGGER consumer_wallet_ledger_deny_update BEFORE UPDATE ON consumer_wallet_ledger BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_CONSUMER_WALLET_LEDGER'); END")
        op.execute("CREATE TRIGGER consumer_wallet_ledger_deny_delete BEFORE DELETE ON consumer_wallet_ledger BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_CONSUMER_WALLET_LEDGER'); END")
    elif bind.dialect.name == "postgresql":
        op.execute("CREATE OR REPLACE FUNCTION deny_consumer_wallet_ledger_mutation() RETURNS trigger AS $$ BEGIN RAISE EXCEPTION 'IMMUTABLE_CONSUMER_WALLET_LEDGER'; END; $$ LANGUAGE plpgsql")
        op.execute("CREATE TRIGGER consumer_wallet_ledger_deny_update BEFORE UPDATE ON consumer_wallet_ledger FOR EACH ROW EXECUTE FUNCTION deny_consumer_wallet_ledger_mutation()")
        op.execute("CREATE TRIGGER consumer_wallet_ledger_deny_delete BEFORE DELETE ON consumer_wallet_ledger FOR EACH ROW EXECUTE FUNCTION deny_consumer_wallet_ledger_mutation()")


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS consumer_wallet_ledger_deny_update")
        op.execute("DROP TRIGGER IF EXISTS consumer_wallet_ledger_deny_delete")
    elif bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS consumer_wallet_ledger_deny_update ON consumer_wallet_ledger")
        op.execute("DROP TRIGGER IF EXISTS consumer_wallet_ledger_deny_delete ON consumer_wallet_ledger")
        op.execute("DROP FUNCTION IF EXISTS deny_consumer_wallet_ledger_mutation()")
    op.drop_index("ix_consumer_wallet_ledger_created_at", table_name="consumer_wallet_ledger")
    op.drop_index("ix_consumer_wallet_ledger_entry_type", table_name="consumer_wallet_ledger")
    op.drop_index("ix_consumer_wallet_ledger_order_id", table_name="consumer_wallet_ledger")
    op.drop_index("ix_consumer_wallet_ledger_user_id", table_name="consumer_wallet_ledger")
    op.drop_index("ix_consumer_wallet_ledger_wallet_id", table_name="consumer_wallet_ledger")
    op.drop_table("consumer_wallet_ledger")
    op.drop_column("consumer_wallet", "cashback_balance_minor")
    op.drop_column("consumer_wallet", "cash_balance_minor")
