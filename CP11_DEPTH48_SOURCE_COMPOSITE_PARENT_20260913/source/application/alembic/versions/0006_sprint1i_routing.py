"""Sprint 1I traffic router, SLA scoring, routing audit

Revision ID: 0006_sprint1i
Revises: 0005_sprint1h
"""
from alembic import op
import sqlalchemy as sa

revision = "0006_sprint1i"
down_revision = "0005_sprint1h"
branch_labels = None
depends_on = None

def upgrade():
    with op.batch_alter_table("offer_snapshot") as b:
        b.add_column(sa.Column("connector_id", sa.String(64), nullable=True))
    op.execute("UPDATE offer_snapshot SET connector_id='conn_mock_hotel' WHERE connector_id IS NULL")
    with op.batch_alter_table("offer_snapshot") as b:
        b.alter_column("connector_id", existing_type=sa.String(64), nullable=False)
        b.create_index("ix_offer_snapshot_connector_id", ["connector_id"])
    op.create_table("connector_sla_window",
        sa.Column("connector_id",sa.String(64),primary_key=True),
        sa.Column("success_rate_bps",sa.Integer(),nullable=False,server_default="10000"),
        sa.Column("confirmation_latency_ms_p95",sa.Integer(),nullable=False,server_default="0"),
        sa.Column("cancel_success_rate_bps",sa.Integer(),nullable=False,server_default="10000"),
        sa.Column("inventory_accuracy_bps",sa.Integer(),nullable=False,server_default="10000"),
        sa.Column("price_consistency_bps",sa.Integer(),nullable=False,server_default="10000"),
        sa.Column("composite_score_bps",sa.Integer(),nullable=False,server_default="10000"),
        sa.Column("sample_size",sa.Integer(),nullable=False,server_default="0"),
        sa.Column("health_status",sa.String(24),nullable=False,server_default="HEALTHY"),
        sa.Column("updated_at",sa.DateTime(timezone=True),nullable=False),
    )
    op.create_index("ix_connector_sla_composite","connector_sla_window",["composite_score_bps"])
    op.create_index("ix_connector_sla_health","connector_sla_window",["health_status"])
    op.create_table("connector_routing_decision",
        sa.Column("decision_id",sa.String(64),primary_key=True),
        sa.Column("operation",sa.String(32),nullable=False),
        sa.Column("hotel_id",sa.String(64)),
        sa.Column("request_key",sa.String(160),nullable=False),
        sa.Column("selected_connector_id",sa.String(64)),
        sa.Column("candidate_connector_ids",sa.JSON(),nullable=False),
        sa.Column("fallback_connector_ids",sa.JSON(),nullable=False),
        sa.Column("reason_codes",sa.JSON(),nullable=False),
        sa.Column("candidate_snapshot",sa.JSON(),nullable=False),
        sa.Column("created_at",sa.DateTime(timezone=True),nullable=False),
    )
    op.create_index("ix_routing_decision_operation","connector_routing_decision",["operation"])
    op.create_index("ix_routing_decision_hotel_time","connector_routing_decision",["hotel_id","created_at"])
    op.create_index("ix_routing_decision_request_key","connector_routing_decision",["request_key"])

def downgrade():
    op.drop_table("connector_routing_decision")
    op.drop_table("connector_sla_window")
    with op.batch_alter_table("offer_snapshot") as b:
        b.drop_index("ix_offer_snapshot_connector_id")
        b.drop_column("connector_id")
