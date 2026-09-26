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


def review_columns():
    return [
        sa.Column('publication_review_id', sa.String(64), primary_key=True),
        sa.Column('hosted_hotel_id', sa.String(64), nullable=False),
        sa.Column('manifest_json', sa.JSON(), nullable=False),
        sa.Column('manifest_hash', sa.String(64), nullable=False),
        sa.Column('reviewer_id', sa.String(64), nullable=False),
        sa.Column('binding_hash', sa.String(64), nullable=False),
        sa.Column('decision', sa.String(24), nullable=False),
        sa.Column('evidence_reference', sa.String(512), nullable=False),
        sa.Column('decided_at', sa.DateTime(timezone=True), nullable=False)]


def compatible(actual,expected,dialect=None):
    kind=expected.type
    same_type=isinstance(actual['type'],type(kind))
    same_length=not isinstance(kind,sa.String) or getattr(actual['type'],'length',None)==kind.length
    same_timezone=dialect!='postgresql' or not isinstance(kind,sa.DateTime) or getattr(actual['type'],'timezone',None)==kind.timezone
    if not same_type or not same_length or not same_timezone or actual['nullable']!=expected.nullable:
        raise RuntimeError('HOSTED_PUBLICATION_SCHEMA_MISMATCH:'+expected.name)


def upgrade():
    bind=op.get_bind();inspector=sa.inspect(bind)
    # Isolated historical upgrades may omit this unrelated table. Some inherited
    # migrations use current metadata; validate fields already created by them.
    if inspector.has_table('hosted_media_asset'):
        existing={c['name']:c for c in inspector.get_columns('hosted_media_asset')}
        for name in ('submitted_by','submitter_binding_hash'):
            column=sa.Column(name,sa.String(64),nullable=True)
            if name in existing:compatible(existing[name],column,bind.dialect.name)
            else:op.add_column('hosted_media_asset',column)
    columns=review_columns()
    if inspector.has_table('hosted_publication_review'):
        existing={c['name']:c for c in inspector.get_columns('hosted_publication_review')}
        if set(existing)!={c.name for c in columns}:raise RuntimeError('HOSTED_PUBLICATION_SCHEMA_MISMATCH')
        for column in columns:compatible(existing[column.name],column,bind.dialect.name)
        if inspector.get_pk_constraint('hosted_publication_review')['constrained_columns']!=['publication_review_id']:
            raise RuntimeError('HOSTED_PUBLICATION_PRIMARY_KEY_MISMATCH')
    else:op.create_table('hosted_publication_review',*columns)
    indexes={x['name']:x for x in sa.inspect(bind).get_indexes('hosted_publication_review')}
    name='ix_hosted_publication_review_hosted_hotel_id'
    if name in indexes:
        if indexes[name]['column_names']!=['hosted_hotel_id'] or indexes[name]['unique']:raise RuntimeError('HOSTED_PUBLICATION_INDEX_MISMATCH')
    else:op.create_index(name,'hosted_publication_review',['hosted_hotel_id'])


def downgrade():
    bind=op.get_bind()
    if bind.execute(sa.text('SELECT COUNT(*) FROM hosted_publication_review')).scalar():
        raise RuntimeError('HOSTED_PUBLICATION_DOWNGRADE_DATA_PRESENT')
    if sa.inspect(bind).has_table('hosted_media_asset'):
        if bind.execute(sa.text('SELECT COUNT(*) FROM hosted_media_asset WHERE submitted_by IS NOT NULL OR submitter_binding_hash IS NOT NULL')).scalar():
            raise RuntimeError('HOSTED_MEDIA_PROVENANCE_DOWNGRADE_DATA_PRESENT')
        op.drop_column('hosted_media_asset','submitter_binding_hash')
        op.drop_column('hosted_media_asset','submitted_by')
    op.drop_index('ix_hosted_publication_review_hosted_hotel_id', table_name='hosted_publication_review')
    op.drop_table('hosted_publication_review')
