"""Sprint 1U production BFF security hardening.

Revision ID: 0016_sprint1u
Revises: 0015_sprint1r
"""
from alembic import op
import sqlalchemy as sa

revision = "0016_sprint1u"
down_revision = "0015_sprint1r"
branch_labels = None
depends_on = None

def upgrade():
    with op.batch_alter_table("identity_user") as b:
        b.add_column(sa.Column("mfa_secret_ciphertext", sa.Text(), nullable=True))
        b.add_column(sa.Column("mfa_enabled_at", sa.DateTime(timezone=True), nullable=True))
        b.add_column(sa.Column("sso_provider", sa.String(64), nullable=True))
        b.add_column(sa.Column("sso_subject", sa.String(256), nullable=True))
        b.create_index("ix_identity_user_sso_provider", ["sso_provider"])
        b.create_index("ix_identity_user_sso_subject", ["sso_subject"])
    with op.batch_alter_table("auth_session") as b:
        b.add_column(sa.Column("auth_method", sa.String(32), nullable=False, server_default="PASSWORD"))
        b.add_column(sa.Column("mfa_verified_at", sa.DateTime(timezone=True), nullable=True))
        b.add_column(sa.Column("csrf_token_hash", sa.String(64), nullable=True))
    op.create_table(
        "oidc_login_state",
        sa.Column("state", sa.String(128), primary_key=True),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("nonce", sa.String(128), nullable=False),
        sa.Column("code_verifier_ciphertext", sa.Text(), nullable=False),
        sa.Column("redirect_uri", sa.String(512), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_oidc_provider", "oidc_login_state", ["provider"])
    op.create_index("ix_oidc_expires", "oidc_login_state", ["expires_at"])

def downgrade():
    op.drop_table("oidc_login_state")
    with op.batch_alter_table("auth_session") as b:
        b.drop_column("csrf_token_hash")
        b.drop_column("mfa_verified_at")
        b.drop_column("auth_method")
    with op.batch_alter_table("identity_user") as b:
        b.drop_index("ix_identity_user_sso_subject")
        b.drop_index("ix_identity_user_sso_provider")
        b.drop_column("sso_subject")
        b.drop_column("sso_provider")
        b.drop_column("mfa_enabled_at")
        b.drop_column("mfa_secret_ciphertext")
