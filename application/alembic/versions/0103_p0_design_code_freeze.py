"""P0 design/code freeze marker.

Revision ID: 0103_p0_design_code_freeze
Revises: 0102_p0_final_closure_program
"""
from alembic import op
revision='0103_p0_design_code_freeze'
down_revision='0102_p0_final_closure_program'
branch_labels=None
depends_on=None

def upgrade():
    # Marker migration: 0103 freezes static P0 design/code contracts. Runtime evidence remains external to this marker.
    pass

def downgrade():
    pass
