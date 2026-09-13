"""R7 compatibility lineage node for staging test-account expiry.

Restored from authoritative Hong Kong Staging/RDS lineage evidence.
The authoritative evidence supplied revision/down_revision identity but not historical DDL text.
Do not add guessed DDL here. Existing staging RDS is already at this revision.
"""

revision = "0111_test_account_expiry"
down_revision = "0110_7012f1955180"
branch_labels = None
depends_on = None

def upgrade():
    # Compatibility lineage marker only. Historical DDL was not supplied; never invent it.
    pass

def downgrade():
    # Never rewrite applied staging history.
    pass
