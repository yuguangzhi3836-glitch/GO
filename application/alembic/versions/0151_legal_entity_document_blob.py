"""Durable bytes for private applicant documents, addressed by content.

``legal_entity_document`` (0147) records *what* a document is: its type, revision,
owner, size and sha256. It never recorded *where* the bytes live — they were
written to a local volume (``services/document_store.py``) whose path came from
``GO_SUPPLIER_DOCUMENT_DIR``.

That is not durable in the Hong Kong deployment. The eight business containers
are recreated from a digest-pinned Compose file and a digest-pinned environment
file, so the container filesystem is discarded on every deployment, and no
private host directory can be mounted without editing the host's sealed
deployment runtime. A licence uploaded by an applicant would therefore be gone
after the next deploy while its metadata row survived — the worst possible
combination, because the reviewer would see a document that can no longer be
served.

This migration adds the table that makes the bytes durable: the database is the
one store the environment already has, is backed up as a unit, and is restored as
a unit. Bytes stay addressed by the same content address the filesystem store
uses, so the two backends are interchangeable and nothing user-supplied ever
becomes a key.

Both stores remain supported: an explicit ``GO_SUPPLIER_DOCUMENT_DIR`` selects the
filesystem backend (development, tests, and any deployment that does mount a
private volume), and its absence selects this table.
"""
from alembic import op
import sqlalchemy as sa

revision = '0151_legal_entity_document_blob'
down_revision = '0150_identity_login_identifiers'
branch_labels = None
depends_on = None

TABLE = 'legal_entity_document_blob'


def upgrade():
    op.create_table(
        TABLE,
        sa.Column('storage_key', sa.String(255), primary_key=True),
        sa.Column('sha256', sa.String(64), nullable=False),
        sa.Column('mime_type', sa.String(64), nullable=False),
        sa.Column('size_bytes', sa.Integer(), nullable=False),
        sa.Column('content', sa.LargeBinary(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint('size_bytes > 0', name='ck_legal_entity_document_blob_bounds'),
    )


def downgrade():
    op.drop_table(TABLE)
