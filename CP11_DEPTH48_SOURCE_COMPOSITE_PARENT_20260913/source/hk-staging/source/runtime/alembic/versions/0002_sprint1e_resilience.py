"""Sprint 1E concurrency, saga recovery, outbox DLQ and webhook inbox."""
from alembic import op
import sqlalchemy as sa

revision = "0002_sprint1e"
down_revision = "0001_sprint1d"
branch_labels = None
depends_on = None

def upgrade():
    with op.batch_alter_table("payment_runtime") as batch:
        batch.add_column(sa.Column("payment_type", sa.String(48), nullable=False, server_default="ORIGINAL_BOOKING"))
        batch.add_column(sa.Column("external_operation_id", sa.String(64), nullable=True))
        batch.create_unique_constraint("uq_payment_external_operation", ["external_operation_id"])

    op.add_column("transactional_outbox", sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("transactional_outbox", sa.Column("lock_token", sa.String(64), nullable=True))
    op.add_column("transactional_outbox", sa.Column("worker_id", sa.String(128), nullable=True))
    op.add_column("transactional_outbox", sa.Column("dead_lettered_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_outbox_lock_token", "transactional_outbox", ["lock_token"])
    op.create_index("ix_outbox_claim", "transactional_outbox", ["status", "available_at", "locked_at", "outbox_id"])

    op.create_table("outbox_dead_letter",
        sa.Column("dead_letter_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("outbox_id", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.String(64), nullable=False),
        sa.Column("event_type", sa.String(96), nullable=False),
        sa.Column("aggregate_id", sa.String(64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text()),
        sa.Column("dead_lettered_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_dlq_outbox", "outbox_dead_letter", ["outbox_id"])
    op.create_index("ix_dlq_event", "outbox_dead_letter", ["event_id"])

    op.create_table("external_operation",
        sa.Column("operation_id", sa.String(64), primary_key=True),
        sa.Column("operation_type", sa.String(64), nullable=False),
        sa.Column("aggregate_id", sa.String(64), nullable=False),
        sa.Column("business_key", sa.String(160), nullable=False, unique=True),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("external_reference", sa.String(128)),
        sa.Column("request_payload", sa.JSON(), nullable=False),
        sa.Column("result_payload", sa.JSON()),
        sa.Column("last_error", sa.Text()),
        sa.Column("next_retry_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_external_operation_aggregate", "external_operation", ["aggregate_id"])
    op.create_index("ix_external_operation_recovery", "external_operation", ["status", "next_retry_at"])

    op.create_table("webhook_inbox",
        sa.Column("webhook_id", sa.String(64), primary_key=True),
        sa.Column("connector_id", sa.String(64), nullable=False),
        sa.Column("external_event_id", sa.String(128), nullable=False),
        sa.Column("aggregate_id", sa.String(64), nullable=False),
        sa.Column("event_type", sa.String(96), nullable=False),
        sa.Column("external_sequence", sa.BigInteger()),
        sa.Column("signature_valid", sa.Boolean(), nullable=False),
        sa.Column("raw_payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("processing_error", sa.Text()),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("connector_id", "external_event_id", name="uq_webhook_connector_event"),
    )
    op.create_index("ix_webhook_aggregate", "webhook_inbox", ["aggregate_id"])
    op.create_index("ix_webhook_pending", "webhook_inbox", ["status", "received_at"])

    op.create_table("connector_event_cursor",
        sa.Column("connector_id", sa.String(64), primary_key=True),
        sa.Column("aggregate_id", sa.String(64), primary_key=True),
        sa.Column("last_sequence", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("last_external_event_id", sa.String(128)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

def downgrade():
    op.drop_table("connector_event_cursor")
    op.drop_table("webhook_inbox")
    op.drop_table("external_operation")
    op.drop_table("outbox_dead_letter")
    op.drop_index("ix_outbox_claim", table_name="transactional_outbox")
    op.drop_index("ix_outbox_lock_token", table_name="transactional_outbox")
    op.drop_column("transactional_outbox", "dead_lettered_at")
    op.drop_column("transactional_outbox", "worker_id")
    op.drop_column("transactional_outbox", "lock_token")
    op.drop_column("transactional_outbox", "locked_at")
    with op.batch_alter_table("payment_runtime") as batch:
        batch.drop_constraint("uq_payment_external_operation", type_="unique")
        batch.drop_column("external_operation_id")
        batch.drop_column("payment_type")
