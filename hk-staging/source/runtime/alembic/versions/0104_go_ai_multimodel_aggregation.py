"""GO AI multi-model aggregation audit registry."""
from alembic import op
import sqlalchemy as sa

revision = "0104_529182b87c94"
down_revision = "0103_p0_design_code_freeze"
branch_labels = None
depends_on = None


def _immutable(table: str, code: str):
    bind = op.get_bind()
    d = bind.dialect.name
    if d == "sqlite":
        op.execute(f"CREATE TRIGGER {table}_deny_update BEFORE UPDATE ON {table} BEGIN SELECT RAISE(ABORT, '{code}'); END")
        op.execute(f"CREATE TRIGGER {table}_deny_delete BEFORE DELETE ON {table} BEGIN SELECT RAISE(ABORT, '{code}'); END")
    elif d == "postgresql":
        fn = f"{table}_immutable_guard"
        op.execute(f"CREATE OR REPLACE FUNCTION {fn}() RETURNS trigger AS $$ BEGIN RAISE EXCEPTION '{code}'; END; $$ LANGUAGE plpgsql")
        op.execute(f"CREATE TRIGGER {table}_deny_update BEFORE UPDATE ON {table} FOR EACH ROW EXECUTE FUNCTION {fn}()")
        op.execute(f"CREATE TRIGGER {table}_deny_delete BEFORE DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION {fn}()")


def upgrade():
    op.create_table(
        "go_ai_request",
        sa.Column("go_ai_request_id", sa.String(64), primary_key=True),
        sa.Column("account_id", sa.String(64), nullable=False, index=True),
        sa.Column("task", sa.String(64), nullable=False, index=True),
        sa.Column("region", sa.String(16), nullable=False, index=True),
        sa.Column("locale", sa.String(24), nullable=False),
        sa.Column("state", sa.String(32), nullable=False, index=True),
        sa.Column("request_hash", sa.String(64), nullable=False, index=True),
        sa.Column("selected_provider", sa.String(32), nullable=True, index=True),
        sa.Column("selected_model", sa.String(128), nullable=True),
        sa.Column("response_hash", sa.String(64), nullable=True),
        sa.Column("failure_code", sa.String(96), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "go_ai_invocation",
        sa.Column("go_ai_invocation_id", sa.String(64), primary_key=True),
        sa.Column("go_ai_request_id", sa.String(64), nullable=False, index=True),
        sa.Column("provider_key", sa.String(32), nullable=False, index=True),
        sa.Column("model_name", sa.String(128), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(32), nullable=False, index=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("provider_request_id", sa.String(192), nullable=True),
        sa.Column("response_hash", sa.String(64), nullable=True),
        sa.Column("error_code", sa.String(96), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("go_ai_request_id", "attempt_no", name="uq_go_ai_invocation_request_attempt"),
    )
    _immutable("go_ai_invocation", "IMMUTABLE_GO_AI_INVOCATION_EVIDENCE")


def downgrade():
    op.drop_table("go_ai_invocation")
    op.drop_table("go_ai_request")
