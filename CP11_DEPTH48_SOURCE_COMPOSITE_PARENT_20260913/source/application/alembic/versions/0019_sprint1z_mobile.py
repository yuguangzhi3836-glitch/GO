"""Sprint 1Z native mobile device and push registration runtime.
Revision ID: 0019_sprint1z
Revises: 0018_sprint1y
"""
from alembic import op
import sqlalchemy as sa
revision="0019_sprint1z"; down_revision="0018_sprint1y"; branch_labels=None; depends_on=None

def upgrade():
    op.create_table("consumer_device",
      sa.Column("device_id",sa.String(64),primary_key=True), sa.Column("user_id",sa.String(64),nullable=False),
      sa.Column("platform",sa.String(16),nullable=False), sa.Column("app_version",sa.String(32)), sa.Column("device_model",sa.String(128)), sa.Column("os_version",sa.String(64)),
      sa.Column("push_provider",sa.String(16)), sa.Column("push_token_ciphertext",sa.Text()), sa.Column("push_token_hash",sa.String(64)), sa.Column("notifications_enabled",sa.Boolean(),nullable=False,server_default=sa.false()),
      sa.Column("last_seen_at",sa.DateTime(timezone=True),nullable=False), sa.Column("status",sa.String(24),nullable=False,server_default="ACTIVE"),
      sa.Column("created_at",sa.DateTime(timezone=True),nullable=False), sa.Column("updated_at",sa.DateTime(timezone=True),nullable=False))
    op.create_index("ix_consumer_device_user","consumer_device",["user_id"]); op.create_index("ix_consumer_device_push_hash","consumer_device",["push_token_hash"]); op.create_index("ix_consumer_device_user_status","consumer_device",["user_id","status"])
    op.create_table("consumer_notification",
      sa.Column("notification_id",sa.String(64),primary_key=True), sa.Column("user_id",sa.String(64),nullable=False), sa.Column("notification_type",sa.String(64),nullable=False),
      sa.Column("title",sa.String(160),nullable=False), sa.Column("body",sa.Text(),nullable=False), sa.Column("deep_link",sa.Text()), sa.Column("payload_json",sa.JSON(),nullable=False),
      sa.Column("delivery_status",sa.String(24),nullable=False,server_default="PENDING"), sa.Column("read_at",sa.DateTime(timezone=True)), sa.Column("created_at",sa.DateTime(timezone=True),nullable=False))
    op.create_index("ix_consumer_notification_user","consumer_notification",["user_id"]); op.create_index("ix_consumer_notification_type","consumer_notification",["notification_type"]); op.create_index("ix_consumer_notification_user_created","consumer_notification",["user_id","created_at"])

def downgrade():
    op.drop_table("consumer_notification"); op.drop_table("consumer_device")
