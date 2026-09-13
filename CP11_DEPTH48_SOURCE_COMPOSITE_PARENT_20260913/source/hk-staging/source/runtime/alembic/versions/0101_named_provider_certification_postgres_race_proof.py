"""P0 0101 named provider certification evidence and PostgreSQL race proof registry."""
from alembic import op
import sqlalchemy as sa
revision='0101_7ae44f334cf0'
down_revision='0100_159ffd29a7f8'
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
    op.create_table('named_provider_certification_evidence',
        sa.Column('named_provider_certification_evidence_id',sa.String(64),primary_key=True),
        sa.Column('provider_kind',sa.String(32),nullable=False,index=True),
        sa.Column('provider_name',sa.String(96),nullable=False,index=True),
        sa.Column('environment',sa.String(32),nullable=False,index=True),
        sa.Column('operation_type',sa.String(64),nullable=False,index=True),
        sa.Column('external_reference',sa.String(256),nullable=True,index=True),
        sa.Column('state',sa.String(48),nullable=False,index=True),
        sa.Column('request_hash',sa.String(64),nullable=False),
        sa.Column('response_hash',sa.String(64),nullable=False),
        sa.Column('evidence_reference',sa.String(512),nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False))
    op.create_table('postgres_race_proof_evidence',
        sa.Column('postgres_race_proof_evidence_id',sa.String(64),primary_key=True),
        sa.Column('scenario_key',sa.String(96),nullable=False,index=True),
        sa.Column('database_version',sa.String(128),nullable=False),
        sa.Column('worker_count',sa.Integer(),nullable=False),
        sa.Column('commit_count',sa.Integer(),nullable=False),
        sa.Column('reject_count',sa.Integer(),nullable=False),
        sa.Column('assertion_state',sa.String(32),nullable=False,index=True),
        sa.Column('evidence_hash',sa.String(64),nullable=False,unique=True),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False))
    _immutable('named_provider_certification_evidence','IMMUTABLE_NAMED_PROVIDER_CERTIFICATION_EVIDENCE')
    _immutable('postgres_race_proof_evidence','IMMUTABLE_POSTGRES_RACE_PROOF_EVIDENCE')

def downgrade():
    op.drop_table('postgres_race_proof_evidence')
    op.drop_table('named_provider_certification_evidence')
