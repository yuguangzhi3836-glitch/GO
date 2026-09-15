"""Sprint 2A native consumer UI and push event orchestration.
Revision ID: 0020_sprint2a
Revises: 0019_sprint1z
"""
from alembic import op
import sqlalchemy as sa
revision="0020_sprint2a"; down_revision="0019_sprint1z"; branch_labels=None; depends_on=None

def upgrade():
    op.create_table("mobile_engagement_job",
      sa.Column("job_id",sa.String(64),primary_key=True),
      sa.Column("dedupe_key",sa.String(160),nullable=False,unique=True),
      sa.Column("user_id",sa.String(64),nullable=False),
      sa.Column("order_id",sa.String(64)), sa.Column("review_id",sa.String(64)),
      sa.Column("event_type",sa.String(96),nullable=False), sa.Column("notification_type",sa.String(64),nullable=False),
      sa.Column("title",sa.String(160),nullable=False), sa.Column("body",sa.Text(),nullable=False), sa.Column("deep_link",sa.Text()),
      sa.Column("payload_json",sa.JSON(),nullable=False), sa.Column("scheduled_at",sa.DateTime(timezone=True),nullable=False),
      sa.Column("status",sa.String(24),nullable=False,server_default="SCHEDULED"), sa.Column("processed_at",sa.DateTime(timezone=True)),
      sa.Column("created_at",sa.DateTime(timezone=True),nullable=False))
    op.create_index("ix_mobile_engagement_dedupe","mobile_engagement_job",["dedupe_key"],unique=True)
    op.create_index("ix_mobile_engagement_user","mobile_engagement_job",["user_id"])
    op.create_index("ix_mobile_engagement_order","mobile_engagement_job",["order_id"])
    op.create_index("ix_mobile_engagement_review","mobile_engagement_job",["review_id"])
    op.create_index("ix_mobile_engagement_event","mobile_engagement_job",["event_type"])
    op.create_index("ix_mobile_engagement_due","mobile_engagement_job",["status","scheduled_at"])

def downgrade(): op.drop_table("mobile_engagement_job")
