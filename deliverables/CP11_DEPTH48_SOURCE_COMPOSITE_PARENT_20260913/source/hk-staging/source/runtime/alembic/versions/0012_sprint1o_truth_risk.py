"""Sprint 1O GO Truth Quick Review, risk evidence and judgment hook runtime

Revision ID: 0012_sprint1o
Revises: 0011_sprint1n
"""
from alembic import op
import sqlalchemy as sa
revision="0012_sprint1o"
down_revision="0011_sprint1n"
branch_labels=None
depends_on=None

def upgrade():
    op.create_table("review_session",
        sa.Column("review_id",sa.String(64),primary_key=True),
        sa.Column("order_id",sa.String(64),nullable=False,unique=True),
        sa.Column("hotel_id",sa.String(64),nullable=False),
        sa.Column("account_id",sa.String(64),nullable=False),
        sa.Column("verified_stay",sa.Boolean(),nullable=False,server_default=sa.false()),
        sa.Column("raw_star_input",sa.Integer()),
        sa.Column("trigger_source",sa.String(32)),
        sa.Column("status",sa.String(32),nullable=False),
        sa.Column("trust_weight_bps",sa.Integer(),nullable=False,server_default="10000"),
        sa.Column("public_status",sa.String(24),nullable=False),
        sa.Column("experience_score_milli",sa.Integer()),sa.Column("dimension_result",sa.JSON(),nullable=False),
        sa.Column("content_text",sa.Text()),sa.Column("voice_ref",sa.String(256)),
        sa.Column("photo_refs",sa.JSON(),nullable=False),
        sa.Column("completed_at",sa.DateTime(timezone=True)),
        sa.Column("created_at",sa.DateTime(timezone=True),nullable=False),sa.Column("updated_at",sa.DateTime(timezone=True),nullable=False))
    op.create_index("ix_review_session_order","review_session",["order_id"])
    op.create_index("ix_review_pending_account","review_session",["account_id","status","created_at"])
    op.create_table("review_tag_runtime",
        sa.Column("review_tag_id",sa.String(64),primary_key=True),sa.Column("review_id",sa.String(64),nullable=False),
        sa.Column("category",sa.String(48),nullable=False),sa.Column("tag_code",sa.String(64),nullable=False),
        sa.Column("polarity",sa.String(16),nullable=False),sa.Column("severity",sa.String(24),nullable=False),
        sa.Column("mapped_dimensions",sa.JSON(),nullable=False),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False),
        sa.UniqueConstraint("review_id","tag_code",name="uq_review_tag_code"))
    op.create_index("ix_review_tag_review","review_tag_runtime",["review_id"])
    op.create_table("risk_event_runtime",
        sa.Column("risk_event_id",sa.String(64),primary_key=True),sa.Column("hotel_id",sa.String(64),nullable=False),
        sa.Column("order_id",sa.String(64),nullable=False),sa.Column("review_id",sa.String(64),nullable=False),
        sa.Column("risk_type",sa.String(64),nullable=False),sa.Column("severity",sa.String(16),nullable=False),
        sa.Column("status",sa.String(32),nullable=False),sa.Column("confidence_bps",sa.Integer(),nullable=False,server_default="0"),
        sa.Column("decision_id",sa.String(64)),sa.Column("rule_version",sa.String(32),nullable=False),sa.Column("public_notice",sa.JSON()),
        sa.Column("created_at",sa.DateTime(timezone=True),nullable=False),sa.Column("updated_at",sa.DateTime(timezone=True),nullable=False),
        sa.Column("confirmed_at",sa.DateTime(timezone=True)),sa.Column("resolved_at",sa.DateTime(timezone=True)))
    op.create_index("ix_risk_hotel_status","risk_event_runtime",["hotel_id","status","created_at"])
    op.create_index("ix_risk_review","risk_event_runtime",["review_id"])
    op.create_table("risk_evidence_runtime",
        sa.Column("evidence_id",sa.String(64),primary_key=True),sa.Column("risk_event_id",sa.String(64),nullable=False),
        sa.Column("source_actor",sa.String(32),nullable=False),sa.Column("evidence_type",sa.String(48),nullable=False),
        sa.Column("content_ref",sa.String(512)),sa.Column("payload",sa.JSON(),nullable=False),
        sa.Column("credibility_bps",sa.Integer(),nullable=False,server_default="5000"),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False))
    op.create_index("ix_risk_evidence_event","risk_evidence_runtime",["risk_event_id"])
    op.create_table("risk_remediation_runtime",
        sa.Column("remediation_id",sa.String(64),primary_key=True),sa.Column("risk_event_id",sa.String(64),nullable=False),
        sa.Column("supplier_action",sa.Text(),nullable=False),sa.Column("evidence_ids",sa.JSON(),nullable=False),
        sa.Column("status",sa.String(24),nullable=False),sa.Column("submitted_at",sa.DateTime(timezone=True),nullable=False),sa.Column("verified_at",sa.DateTime(timezone=True)))
    op.create_index("ix_risk_remediation_event","risk_remediation_runtime",["risk_event_id"])
    op.create_table("judgment_hook_runtime",
        sa.Column("hook_id",sa.String(64),primary_key=True),sa.Column("hotel_id",sa.String(64),nullable=False),
        sa.Column("source_type",sa.String(48),nullable=False),sa.Column("source_id",sa.String(64),nullable=False),
        sa.Column("reason_code",sa.String(64),nullable=False),sa.Column("status",sa.String(24),nullable=False),
        sa.Column("payload",sa.JSON(),nullable=False),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False))
    op.create_index("ix_judgment_hook_hotel_status","judgment_hook_runtime",["hotel_id","status"])

def downgrade():
    op.drop_table("judgment_hook_runtime"); op.drop_table("risk_remediation_runtime"); op.drop_table("risk_evidence_runtime")
    op.drop_table("risk_event_runtime"); op.drop_table("review_tag_runtime"); op.drop_table("review_session")
