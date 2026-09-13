"""Sprint 1P GO Judgment runtime, GO Score, Recommendation and Evidence Package

Revision ID: 0013_sprint1p
Revises: 0012_sprint1o
"""
from alembic import op
import sqlalchemy as sa
revision="0013_sprint1p"
down_revision="0012_sprint1o"
branch_labels=None
depends_on=None

def upgrade():
    op.create_table("judgment_evidence_package",
        sa.Column("package_id",sa.String(64),primary_key=True),
        sa.Column("hotel_id",sa.String(64),nullable=False),
        sa.Column("source_refs",sa.JSON(),nullable=False),
        sa.Column("source_summary",sa.JSON(),nullable=False),
        sa.Column("feature_snapshot",sa.JSON(),nullable=False),
        sa.Column("excluded_commercial_fields",sa.JSON(),nullable=False),
        sa.Column("content_hash",sa.String(64),nullable=False,unique=True),
        sa.Column("sealed_at",sa.DateTime(timezone=True),nullable=False),
        sa.Column("created_at",sa.DateTime(timezone=True),nullable=False))
    op.create_index("ix_judgment_evidence_hotel","judgment_evidence_package",["hotel_id"])
    op.create_table("judgment_runtime",
        sa.Column("judgment_id",sa.String(64),primary_key=True),
        sa.Column("hotel_id",sa.String(64),nullable=False),
        sa.Column("evidence_package_id",sa.String(64),nullable=False),
        sa.Column("go_score_milli",sa.Integer(),nullable=False),
        sa.Column("dimension_result",sa.JSON(),nullable=False),
        sa.Column("explanation",sa.JSON(),nullable=False),
        sa.Column("confidence_bps",sa.Integer(),nullable=False),
        sa.Column("model_version",sa.String(64),nullable=False),
        sa.Column("prompt_version",sa.String(64),nullable=False),
        sa.Column("rule_version",sa.String(64),nullable=False),
        sa.Column("status",sa.String(24),nullable=False),
        sa.Column("public_at",sa.DateTime(timezone=True)),
        sa.Column("valid_from",sa.DateTime(timezone=True),nullable=False),
        sa.Column("valid_to",sa.DateTime(timezone=True)),
        sa.Column("created_at",sa.DateTime(timezone=True),nullable=False))
    op.create_index("ix_judgment_hotel_created","judgment_runtime",["hotel_id","created_at"])
    op.create_index("ix_judgment_evidence_package","judgment_runtime",["evidence_package_id"])
    op.create_table("recommendation_decision_runtime",
        sa.Column("decision_id",sa.String(64),primary_key=True),
        sa.Column("hotel_id",sa.String(64),nullable=False),
        sa.Column("judgment_id",sa.String(64),nullable=False),
        sa.Column("status",sa.String(32),nullable=False),
        sa.Column("reason_codes",sa.JSON(),nullable=False),
        sa.Column("public_go_score_milli",sa.Integer()),
        sa.Column("rule_version",sa.String(64),nullable=False),
        sa.Column("valid_from",sa.DateTime(timezone=True),nullable=False),
        sa.Column("valid_to",sa.DateTime(timezone=True)),
        sa.Column("created_at",sa.DateTime(timezone=True),nullable=False))
    op.create_index("ix_recommendation_hotel_created","recommendation_decision_runtime",["hotel_id","created_at"])
    op.create_index("ix_recommendation_judgment","recommendation_decision_runtime",["judgment_id"])

def downgrade():
    op.drop_table("recommendation_decision_runtime")
    op.drop_table("judgment_runtime")
    op.drop_table("judgment_evidence_package")
