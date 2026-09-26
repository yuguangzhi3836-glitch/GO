"""Persist version-bound isolated Hosted publication reviews.

Revision ID: 0139_hosted_publication_review
Revises: 0138_supplier_library_import
"""
from alembic import op
import sqlalchemy as sa

revision = '0139_hosted_publication_review'
down_revision = '0138_supplier_library_import'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('hosted_media_asset',sa.Column('submitted_by',sa.String(64),nullable=True))
    op.add_column('hosted_media_asset',sa.Column('submitter_binding_hash',sa.String(64),nullable=True))
    op.create_table('hosted_publication_review',
        sa.Column('publication_review_id', sa.String(64), primary_key=True),
        sa.Column('hosted_hotel_id', sa.String(64), nullable=False),
        sa.Column('manifest_json', sa.JSON(), nullable=False),
        sa.Column('manifest_hash', sa.String(64), nullable=False),
        sa.Column('reviewer_id', sa.String(64), nullable=False),
        sa.Column('binding_hash', sa.String(64), nullable=False),
        sa.Column('decision', sa.String(24), nullable=False),
        sa.Column('evidence_reference', sa.String(512), nullable=False),
        sa.Column('decided_at', sa.DateTime(timezone=True), nullable=False))
    op.create_index('ix_hosted_publication_review_hosted_hotel_id', 'hosted_publication_review', ['hosted_hotel_id'])


def downgrade():
    op.drop_column('hosted_media_asset','submitter_binding_hash')
    op.drop_column('hosted_media_asset','submitted_by')
    op.drop_index('ix_hosted_publication_review_hosted_hotel_id', table_name='hosted_publication_review')
    op.drop_table('hosted_publication_review')
