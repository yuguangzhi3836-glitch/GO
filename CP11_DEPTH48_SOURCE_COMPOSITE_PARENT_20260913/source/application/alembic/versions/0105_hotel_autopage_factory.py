"""GO Hotel AutoPage Factory: multi-source content graph, prebuilt pages, contacts and claims."""
from alembic import op
import sqlalchemy as sa
revision='0105_hotel_autopage_factory'
down_revision='0104_529182b87c94'
branch_labels=None
depends_on=None

def _immutable(table, code):
    bind=op.get_bind(); d=bind.dialect.name
    if d=='sqlite':
        op.execute(f"CREATE TRIGGER {table}_deny_update BEFORE UPDATE ON {table} BEGIN SELECT RAISE(ABORT, '{code}'); END")
        op.execute(f"CREATE TRIGGER {table}_deny_delete BEFORE DELETE ON {table} BEGIN SELECT RAISE(ABORT, '{code}'); END")
    elif d=='postgresql':
        fn=f'{table}_immutable_guard'
        op.execute(f"CREATE OR REPLACE FUNCTION {fn}() RETURNS trigger AS $$ BEGIN RAISE EXCEPTION '{code}'; END; $$ LANGUAGE plpgsql")
        op.execute(f"CREATE TRIGGER {table}_deny_update BEFORE UPDATE ON {table} FOR EACH ROW EXECUTE FUNCTION {fn}()")
        op.execute(f"CREATE TRIGGER {table}_deny_delete BEFORE DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION {fn}()")

def upgrade():
    op.create_table('hotel_content_source_snapshot',
        sa.Column('content_source_snapshot_id',sa.String(64),primary_key=True),
        sa.Column('source_key',sa.String(64),nullable=False,index=True),sa.Column('source_type',sa.String(48),nullable=False,index=True),
        sa.Column('external_hotel_id',sa.String(192),nullable=False,index=True),sa.Column('source_url',sa.String(1024)),
        sa.Column('rights_status',sa.String(48),nullable=False,index=True),sa.Column('confidence_bps',sa.Integer(),nullable=False),
        sa.Column('payload_json',sa.JSON(),nullable=False),sa.Column('payload_hash',sa.String(64),nullable=False,index=True),
        sa.Column('canonical_hotel_id',sa.String(64),index=True),sa.Column('observed_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.UniqueConstraint('source_key','external_hotel_id','payload_hash',name='uq_hotel_content_source_payload'))
    op.create_table('hotel_canonical_profile',
        sa.Column('hotel_id',sa.String(64),primary_key=True),sa.Column('slug',sa.String(192),nullable=False,unique=True,index=True),
        sa.Column('canonical_json',sa.JSON(),nullable=False),sa.Column('field_provenance_json',sa.JSON(),nullable=False),
        sa.Column('source_snapshot_ids_json',sa.JSON(),nullable=False),sa.Column('completeness_bps',sa.Integer(),nullable=False,index=True),
        sa.Column('claim_state',sa.String(32),nullable=False,index=True),sa.Column('page_state',sa.String(32),nullable=False,index=True),
        sa.Column('version',sa.Integer(),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False))
    op.create_table('hotel_contact_point',
        sa.Column('hotel_contact_point_id',sa.String(64),primary_key=True),sa.Column('hotel_id',sa.String(64),nullable=False,index=True),
        sa.Column('contact_type',sa.String(48),nullable=False,index=True),sa.Column('channel',sa.String(24),nullable=False,index=True),
        sa.Column('value',sa.String(512),nullable=False),sa.Column('normalized_value',sa.String(512),nullable=False,index=True),
        sa.Column('source_url',sa.String(1024)),sa.Column('source_type',sa.String(48),nullable=False),
        sa.Column('is_public_business_contact',sa.Boolean(),nullable=False),sa.Column('jurisdiction',sa.String(16),index=True),
        sa.Column('confidence_bps',sa.Integer(),nullable=False),sa.Column('marketing_eligibility',sa.String(40),nullable=False,index=True),
        sa.Column('do_not_contact',sa.Boolean(),nullable=False,index=True),sa.Column('verified_at',sa.DateTime(timezone=True)),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False),
        sa.UniqueConstraint('hotel_id','channel','normalized_value',name='uq_hotel_contact_point_value'))
    op.create_table('hotel_auto_page_version',
        sa.Column('hotel_auto_page_version_id',sa.String(64),primary_key=True),sa.Column('hotel_id',sa.String(64),nullable=False,index=True),
        sa.Column('slug',sa.String(192),nullable=False,index=True),sa.Column('version',sa.Integer(),nullable=False),sa.Column('page_json',sa.JSON(),nullable=False),
        sa.Column('page_hash',sa.String(64),nullable=False,unique=True),sa.Column('source_snapshot_ids_json',sa.JSON(),nullable=False),
        sa.Column('claim_state',sa.String(32),nullable=False,index=True),sa.Column('publication_state',sa.String(32),nullable=False,index=True),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.UniqueConstraint('hotel_id','version',name='uq_hotel_auto_page_version'))
    op.create_table('hotel_page_claim',
        sa.Column('hotel_page_claim_id',sa.String(64),primary_key=True),sa.Column('hotel_id',sa.String(64),nullable=False,index=True),
        sa.Column('supplier_id',sa.String(64),nullable=False,index=True),sa.Column('state',sa.String(32),nullable=False,index=True),
        sa.Column('evidence_json',sa.JSON(),nullable=False),sa.Column('official_supplement_json',sa.JSON(),nullable=False),
        sa.Column('requested_by',sa.String(64),nullable=False),sa.Column('reviewed_by',sa.String(64)),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.Column('reviewed_at',sa.DateTime(timezone=True)))
    op.create_table('hotel_auto_page_event',
        sa.Column('hotel_auto_page_event_id',sa.String(64),primary_key=True),sa.Column('hotel_id',sa.String(64),index=True),
        sa.Column('event_type',sa.String(64),nullable=False,index=True),sa.Column('evidence_json',sa.JSON(),nullable=False),
        sa.Column('actor',sa.String(64),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False,index=True))
    _immutable('hotel_content_source_snapshot','IMMUTABLE_HOTEL_CONTENT_SOURCE_EVIDENCE')
    _immutable('hotel_auto_page_version','IMMUTABLE_HOTEL_AUTO_PAGE_VERSION')
    _immutable('hotel_auto_page_event','IMMUTABLE_HOTEL_AUTO_PAGE_EVENT')

def downgrade():
    for t in ['hotel_auto_page_event','hotel_page_claim','hotel_auto_page_version','hotel_contact_point','hotel_canonical_profile','hotel_content_source_snapshot']:
        op.drop_table(t)
