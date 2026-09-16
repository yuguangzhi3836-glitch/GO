"""Durable, episode-bound reconciliation for hosted mixed funding."""
from alembic import op
import sqlalchemy as sa

revision = "0137_hosted_unknown_episode"
down_revision = "0136_merge_go_ai_journey"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "hosted_money_unknown_episode",
        sa.Column("episode_id", sa.String(64), primary_key=True),
        sa.Column("authorization_id", sa.String(64), nullable=False),
        sa.Column("hosted_reservation_id", sa.String(64), nullable=False),
        sa.Column("money_movement_id", sa.String(64), nullable=False),
        sa.Column("funding_leg", sa.String(40), nullable=False),
        sa.Column("episode_generation", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("open_evidence_reference", sa.String(512), nullable=False),
        sa.Column("open_evidence_digest", sa.String(64), nullable=False),
        sa.Column("resolution_decision", sa.String(32), nullable=True),
        sa.Column("resolution_evidence_reference", sa.String(512), nullable=True),
        sa.Column("resolution_evidence_digest", sa.String(64), nullable=True),
        sa.Column("opened_by", sa.String(64), nullable=False),
        sa.Column("resolved_by", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "money_movement_id", "episode_generation",
            name="uq_hosted_money_unknown_generation",
        ),
    )
    op.create_index(
        "ix_hosted_money_unknown_episode_authorization_id",
        "hosted_money_unknown_episode", ["authorization_id"],
    )
    op.create_index(
        "ix_hosted_money_unknown_episode_hosted_reservation_id",
        "hosted_money_unknown_episode", ["hosted_reservation_id"],
    )
    op.create_index(
        "ix_hosted_money_unknown_episode_money_movement_id",
        "hosted_money_unknown_episode", ["money_movement_id"],
    )
    op.create_index(
        "ix_hosted_money_unknown_episode_status",
        "hosted_money_unknown_episode", ["status"],
    )
    op.create_table(
        "hosted_money_unknown_episode_audit",
        sa.Column("audit_id", sa.String(64), primary_key=True),
        sa.Column("episode_id", sa.String(64), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("actor_id", sa.String(64), nullable=False),
        sa.Column("evidence_digest", sa.String(64), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("previous_hash", sa.String(64), nullable=True),
        sa.Column("event_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "episode_id", "sequence",
            name="uq_hosted_money_unknown_audit_sequence",
        ),
    )
    op.create_index(
        "ix_hosted_money_unknown_episode_audit_episode_id",
        "hosted_money_unknown_episode_audit", ["episode_id"],
    )


def downgrade():
    op.drop_index(
        "ix_hosted_money_unknown_episode_audit_episode_id",
        table_name="hosted_money_unknown_episode_audit",
    )
    op.drop_table("hosted_money_unknown_episode_audit")
    op.drop_index(
        "ix_hosted_money_unknown_episode_status",
        table_name="hosted_money_unknown_episode",
    )
    op.drop_index(
        "ix_hosted_money_unknown_episode_money_movement_id",
        table_name="hosted_money_unknown_episode",
    )
    op.drop_index(
        "ix_hosted_money_unknown_episode_hosted_reservation_id",
        table_name="hosted_money_unknown_episode",
    )
    op.drop_index(
        "ix_hosted_money_unknown_episode_authorization_id",
        table_name="hosted_money_unknown_episode",
    )
    op.drop_table("hosted_money_unknown_episode")
