"""Sprint 1R identity RBAC tenant isolation approval audit

Revision ID: 0015_sprint1r
Revises: 0014_sprint1q
"""
from alembic import op
import sqlalchemy as sa
revision='0015_sprint1r'; down_revision='0014_sprint1q'; branch_labels=None; depends_on=None

def upgrade():
    op.create_table('identity_user',sa.Column('user_id',sa.String(64),primary_key=True),sa.Column('username',sa.String(128),nullable=False,unique=True),sa.Column('password_hash',sa.String(512),nullable=False),sa.Column('actor_type',sa.String(32),nullable=False),sa.Column('supplier_id',sa.String(64)),sa.Column('roles',sa.JSON(),nullable=False),sa.Column('status',sa.String(24),nullable=False),sa.Column('token_version',sa.Integer(),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False))
    op.create_index('ix_identity_user_username','identity_user',['username'],unique=True); op.create_index('ix_identity_supplier_status','identity_user',['supplier_id','status'])
    op.create_table('auth_session',sa.Column('session_id',sa.String(64),primary_key=True),sa.Column('user_id',sa.String(64),nullable=False),sa.Column('status',sa.String(24),nullable=False),sa.Column('client_ip',sa.String(128)),sa.Column('user_agent',sa.String(512)),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.Column('last_seen_at',sa.DateTime(timezone=True),nullable=False),sa.Column('expires_at',sa.DateTime(timezone=True),nullable=False),sa.Column('revoked_at',sa.DateTime(timezone=True)))
    op.create_index('ix_auth_session_user','auth_session',['user_id']); op.create_index('ix_auth_session_status','auth_session',['status'])
    op.create_table('refresh_token',sa.Column('token_id',sa.String(64),primary_key=True),sa.Column('session_id',sa.String(64),nullable=False),sa.Column('user_id',sa.String(64),nullable=False),sa.Column('token_hash',sa.String(64),nullable=False,unique=True),sa.Column('status',sa.String(24),nullable=False),sa.Column('expires_at',sa.DateTime(timezone=True),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.Column('revoked_at',sa.DateTime(timezone=True)))
    op.create_index('ix_refresh_session','refresh_token',['session_id']); op.create_index('ix_refresh_user','refresh_token',['user_id'])
    op.create_table('approval_request',sa.Column('approval_id',sa.String(64),primary_key=True),sa.Column('operation_type',sa.String(64),nullable=False),sa.Column('subject_type',sa.String(64),nullable=False),sa.Column('subject_id',sa.String(128),nullable=False),sa.Column('requested_by',sa.String(64),nullable=False),sa.Column('approved_by',sa.String(64)),sa.Column('status',sa.String(24),nullable=False),sa.Column('request_payload',sa.JSON(),nullable=False),sa.Column('approval_note',sa.Text()),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.Column('approved_at',sa.DateTime(timezone=True)),sa.Column('consumed_at',sa.DateTime(timezone=True)),sa.Column('expires_at',sa.DateTime(timezone=True),nullable=False))
    op.create_index('ix_approval_status','approval_request',['status']); op.create_index('ix_approval_subject','approval_request',['subject_id'])
    op.create_table('audit_event',sa.Column('audit_id',sa.String(64),primary_key=True),sa.Column('actor_id',sa.String(64),nullable=False),sa.Column('actor_type',sa.String(32),nullable=False),sa.Column('supplier_id',sa.String(64)),sa.Column('roles',sa.JSON(),nullable=False),sa.Column('session_id',sa.String(64)),sa.Column('action',sa.String(128),nullable=False),sa.Column('resource_type',sa.String(64),nullable=False),sa.Column('resource_id',sa.String(128)),sa.Column('request_id',sa.String(128)),sa.Column('client_ip',sa.String(128)),sa.Column('http_method',sa.String(16)),sa.Column('path',sa.String(512)),sa.Column('before_state',sa.JSON()),sa.Column('after_state',sa.JSON()),sa.Column('decision_id',sa.String(64)),sa.Column('evidence_id',sa.String(64)),sa.Column('approval_id',sa.String(64)),sa.Column('metadata_json',sa.JSON(),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False))
    op.create_index('ix_audit_actor_created','audit_event',['actor_id','created_at']); op.create_index('ix_audit_resource_created','audit_event',['resource_type','resource_id','created_at']); op.create_index('ix_audit_request','audit_event',['request_id'])
    bind=op.get_bind()
    if bind.dialect.name == 'postgresql':
        op.execute("CREATE OR REPLACE FUNCTION go_audit_immutable() RETURNS trigger AS $$ BEGIN RAISE EXCEPTION 'audit_event is append-only'; END; $$ LANGUAGE plpgsql")
        op.execute("CREATE TRIGGER trg_audit_no_update BEFORE UPDATE OR DELETE ON audit_event FOR EACH ROW EXECUTE FUNCTION go_audit_immutable()")
    elif bind.dialect.name == 'sqlite':
        op.execute("CREATE TRIGGER trg_audit_no_update BEFORE UPDATE ON audit_event BEGIN SELECT RAISE(ABORT, 'audit_event is append-only'); END")
        op.execute("CREATE TRIGGER trg_audit_no_delete BEFORE DELETE ON audit_event BEGIN SELECT RAISE(ABORT, 'audit_event is append-only'); END")

def downgrade():
    bind=op.get_bind()
    if bind.dialect.name == 'postgresql':
        op.execute('DROP TRIGGER IF EXISTS trg_audit_no_update ON audit_event')
        op.execute('DROP FUNCTION IF EXISTS go_audit_immutable()')
    elif bind.dialect.name == 'sqlite':
        op.execute('DROP TRIGGER IF EXISTS trg_audit_no_update')
        op.execute('DROP TRIGGER IF EXISTS trg_audit_no_delete')
    op.drop_table('audit_event'); op.drop_table('approval_request'); op.drop_table('refresh_token'); op.drop_table('auth_session'); op.drop_table('identity_user')
