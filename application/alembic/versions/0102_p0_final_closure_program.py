"""P0 Final Closure Program: immutable requirement-to-code-to-runtime evidence registry."""
from alembic import op
import sqlalchemy as sa
revision='0102_p0_final_closure_program'
down_revision='0101_7ae44f334cf0'
branch_labels=None
depends_on=None

def immutable(table,code):
    d=op.get_bind().dialect.name
    if d=='sqlite':
        op.execute(f"CREATE TRIGGER {table}_deny_update BEFORE UPDATE ON {table} BEGIN SELECT RAISE(ABORT, '{code}'); END")
        op.execute(f"CREATE TRIGGER {table}_deny_delete BEFORE DELETE ON {table} BEGIN SELECT RAISE(ABORT, '{code}'); END")
    elif d=='postgresql':
        fn=f'{table}_immutable_guard'
        op.execute(f"CREATE OR REPLACE FUNCTION {fn}() RETURNS trigger AS $$ BEGIN RAISE EXCEPTION '{code}'; END; $$ LANGUAGE plpgsql")
        op.execute(f"CREATE TRIGGER {table}_deny_update BEFORE UPDATE ON {table} FOR EACH ROW EXECUTE FUNCTION {fn}()")
        op.execute(f"CREATE TRIGGER {table}_deny_delete BEFORE DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION {fn}()")

def upgrade():
    op.create_table('p0_final_closure_requirement_evidence',
      sa.Column('p0_final_closure_requirement_evidence_id',sa.String(64),primary_key=True),
      sa.Column('requirement_key',sa.String(128),nullable=False,index=True),sa.Column('domain',sa.String(64),nullable=False,index=True),
      sa.Column('requirement_text',sa.String(512),nullable=False),sa.Column('code_reference',sa.String(512),nullable=False),
      sa.Column('runtime_evidence_reference',sa.String(512),nullable=True),sa.Column('status',sa.String(32),nullable=False,index=True),
      sa.Column('blocker_code',sa.String(160),nullable=True,index=True),sa.Column('evidence_hash',sa.String(64),nullable=False,unique=True),
      sa.Column('created_at',sa.DateTime(timezone=True),nullable=False))
    op.create_table('p0_final_closure_bundle',
      sa.Column('p0_final_closure_bundle_id',sa.String(64),primary_key=True),sa.Column('build_sha256',sa.String(64),nullable=False,index=True),
      sa.Column('design_state',sa.String(32),nullable=False,index=True),sa.Column('code_state',sa.String(32),nullable=False,index=True),
      sa.Column('runtime_state',sa.String(32),nullable=False,index=True),sa.Column('external_sandbox_gate',sa.String(16),nullable=False,index=True),
      sa.Column('blockers_json',sa.JSON(),nullable=False),sa.Column('requirement_snapshot_json',sa.JSON(),nullable=False),
      sa.Column('evidence_hash',sa.String(64),nullable=False,unique=True),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False))
    immutable('p0_final_closure_requirement_evidence','IMMUTABLE_P0_FINAL_CLOSURE_EVIDENCE')
    immutable('p0_final_closure_bundle','IMMUTABLE_P0_FINAL_CLOSURE_BUNDLE')

def downgrade():
    op.drop_table('p0_final_closure_bundle');op.drop_table('p0_final_closure_requirement_evidence')
