"""Sprint 1Y consumer identity, GO ID, travelers and tokenized payment references.
Revision ID: 0018_sprint1y
Revises: 0017_sprint1v
"""
from alembic import op
import sqlalchemy as sa
revision="0018_sprint1y"; down_revision="0017_sprint1v"; branch_labels=None; depends_on=None

def upgrade():
    op.create_table("consumer_profile",
      sa.Column("user_id",sa.String(64),primary_key=True), sa.Column("go_id",sa.String(32),nullable=False,unique=True),
      sa.Column("email",sa.String(256),nullable=False,unique=True), sa.Column("display_name",sa.String(128)), sa.Column("phone_ciphertext",sa.Text()),
      sa.Column("locale",sa.String(16),nullable=False,server_default="zh-CN"), sa.Column("status",sa.String(24),nullable=False,server_default="ACTIVE"),
      sa.Column("created_at",sa.DateTime(timezone=True),nullable=False), sa.Column("updated_at",sa.DateTime(timezone=True),nullable=False))
    op.create_index("ix_consumer_profile_go_id","consumer_profile",["go_id"],unique=True); op.create_index("ix_consumer_profile_email","consumer_profile",["email"],unique=True)
    op.create_table("consumer_traveler",
      sa.Column("traveler_id",sa.String(64),primary_key=True), sa.Column("user_id",sa.String(64),nullable=False), sa.Column("full_name",sa.String(160),nullable=False),
      sa.Column("date_of_birth",sa.String(10)), sa.Column("nationality",sa.String(3)), sa.Column("document_type",sa.String(32)), sa.Column("document_ciphertext",sa.Text()),
      sa.Column("is_primary",sa.Boolean(),nullable=False,server_default=sa.false()), sa.Column("status",sa.String(24),nullable=False,server_default="ACTIVE"),
      sa.Column("created_at",sa.DateTime(timezone=True),nullable=False), sa.Column("updated_at",sa.DateTime(timezone=True),nullable=False))
    op.create_index("ix_consumer_traveler_user","consumer_traveler",["user_id"]); op.create_index("ix_consumer_traveler_user_status","consumer_traveler",["user_id","status"])
    op.create_table("consumer_payment_method",
      sa.Column("payment_method_id",sa.String(64),primary_key=True), sa.Column("user_id",sa.String(64),nullable=False), sa.Column("provider",sa.String(48),nullable=False),
      sa.Column("provider_token_ciphertext",sa.Text(),nullable=False), sa.Column("fingerprint",sa.String(128),nullable=False), sa.Column("brand",sa.String(32)), sa.Column("last4",sa.String(4)),
      sa.Column("expiry_month",sa.Integer()), sa.Column("expiry_year",sa.Integer()), sa.Column("is_default",sa.Boolean(),nullable=False,server_default=sa.false()),
      sa.Column("status",sa.String(24),nullable=False,server_default="ACTIVE"), sa.Column("created_at",sa.DateTime(timezone=True),nullable=False), sa.Column("updated_at",sa.DateTime(timezone=True),nullable=False))
    op.create_index("ix_consumer_payment_user","consumer_payment_method",["user_id"]); op.create_index("ix_consumer_payment_fingerprint","consumer_payment_method",["fingerprint"]); op.create_index("ix_consumer_payment_user_status","consumer_payment_method",["user_id","status"])
    op.create_table("consumer_wallet", sa.Column("wallet_id",sa.String(64),primary_key=True), sa.Column("user_id",sa.String(64),nullable=False,unique=True), sa.Column("status",sa.String(24),nullable=False,server_default="ACTIVE"), sa.Column("created_at",sa.DateTime(timezone=True),nullable=False), sa.Column("updated_at",sa.DateTime(timezone=True),nullable=False))
    op.create_index("ix_consumer_wallet_user","consumer_wallet",["user_id"],unique=True)

def downgrade():
    op.drop_table("consumer_wallet"); op.drop_table("consumer_payment_method"); op.drop_table("consumer_traveler"); op.drop_table("consumer_profile")
