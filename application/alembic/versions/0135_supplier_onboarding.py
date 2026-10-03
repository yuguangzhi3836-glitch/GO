"""Add supplier onboarding lifecycle without duplicating subscription/capability state."""
from alembic import op
import sqlalchemy as sa

revision = "0135_supplier_onboarding"
down_revision = "0134_flight_status_width"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "supplier_onboarding",
        sa.Column("onboarding_id", sa.String(64), primary_key=True),
        sa.Column("supplier_id", sa.String(64), nullable=False),
        sa.Column("owner_user_id", sa.String(64), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("profile_json", sa.JSON(), nullable=False),
        sa.Column("contract_json", sa.JSON(), nullable=False),
        sa.Column("property_id", sa.String(64)),
        sa.Column("review_note", sa.Text()),
        sa.Column("reviewed_by", sa.String(64)),
        sa.Column("contract_review_note", sa.Text()),
        sa.Column("contract_reviewed_by", sa.String(64)),
        sa.Column("submitted_at", sa.DateTime(timezone=True)),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("contract_submitted_at", sa.DateTime(timezone=True)),
        sa.Column("contract_reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("supplier_id", name="uq_supplier_onboarding_supplier"),
    )
    op.create_index("ix_supplier_onboarding_supplier_id", "supplier_onboarding", ["supplier_id"])
    op.create_index("ix_supplier_onboarding_owner_user_id", "supplier_onboarding", ["owner_user_id"])
    op.create_index("ix_supplier_onboarding_state", "supplier_onboarding", ["state"])
    op.create_index("ix_supplier_onboarding_property_id", "supplier_onboarding", ["property_id"])

    # Preserve existing suppliers as already active. New registrations explicitly
    # create REGISTERED rows and therefore enter the staged onboarding flow.
    op.execute(sa.text("""
        INSERT INTO supplier_onboarding
            (onboarding_id, supplier_id, owner_user_id, state, profile_json, contract_json, created_at, updated_at)
        SELECT supplier_id, supplier_id, MIN(user_id), 'CONTRACT_ACTIVE', '{}', '{}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        FROM identity_user
        WHERE actor_type = 'SUPPLIER_USER' AND supplier_id IS NOT NULL
        GROUP BY supplier_id
    """))


def downgrade():
    op.drop_index("ix_supplier_onboarding_property_id", table_name="supplier_onboarding")
    op.drop_index("ix_supplier_onboarding_state", table_name="supplier_onboarding")
    op.drop_index("ix_supplier_onboarding_owner_user_id", table_name="supplier_onboarding")
    op.drop_index("ix_supplier_onboarding_supplier_id", table_name="supplier_onboarding")
    op.drop_table("supplier_onboarding")
