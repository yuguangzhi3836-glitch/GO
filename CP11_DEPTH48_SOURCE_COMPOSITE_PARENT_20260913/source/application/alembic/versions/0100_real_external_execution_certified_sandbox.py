"""P0 0100 real external execution and certified sandbox closure evidence."""
from alembic import op
import sqlalchemy as sa
revision='0100_159ffd29a7f8'
down_revision='0099_e9ab838ca46d'
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
    op.create_table('external_truth_operation',
        sa.Column('external_truth_operation_id',sa.String(64),primary_key=True),
        sa.Column('execution_authorization_id',sa.String(64),nullable=False,index=True),
        sa.Column('payment_intent_id',sa.String(64),index=True),sa.Column('supplier_fulfillment_id',sa.String(64),index=True),
        sa.Column('vertical',sa.String(24),nullable=False,index=True),sa.Column('operation_type',sa.String(48),nullable=False,index=True),
        sa.Column('idempotency_key',sa.String(160),nullable=False,unique=True),sa.Column('endpoint_reference',sa.String(512),nullable=False),
        sa.Column('external_operation_id',sa.String(256),index=True),sa.Column('http_status',sa.Integer()),
        sa.Column('state',sa.String(48),nullable=False,index=True),sa.Column('request_hash',sa.String(64),nullable=False),
        sa.Column('response_hash',sa.String(64)),sa.Column('evidence_reference',sa.String(512)),
        sa.Column('started_at',sa.DateTime(timezone=True),nullable=False),sa.Column('completed_at',sa.DateTime(timezone=True)))
    op.create_table('external_truth_webhook_receipt',
        sa.Column('external_truth_webhook_receipt_id',sa.String(64),primary_key=True),
        sa.Column('external_truth_operation_id',sa.String(64),nullable=False,index=True),
        sa.Column('source_vertical',sa.String(24),nullable=False,index=True),sa.Column('delivery_id',sa.String(160),nullable=False,unique=True),
        sa.Column('signature_scheme',sa.String(64),nullable=False),sa.Column('signature_verified',sa.Boolean(),nullable=False),
        sa.Column('supplier_state',sa.String(64),nullable=False),sa.Column('payload_hash',sa.String(64),nullable=False),
        sa.Column('received_at',sa.DateTime(timezone=True),nullable=False))
    op.create_table('external_truth_bank_feed_receipt',
        sa.Column('bank_feed_receipt_id',sa.String(64),primary_key=True),sa.Column('provider_key',sa.String(128),nullable=False,index=True),
        sa.Column('delivery_id',sa.String(160),nullable=False,unique=True),sa.Column('signature_verified',sa.Boolean(),nullable=False),
        sa.Column('payload_hash',sa.String(64),nullable=False),sa.Column('imported_line_count',sa.Integer(),nullable=False),
        sa.Column('evidence_reference',sa.String(512),nullable=False),sa.Column('received_at',sa.DateTime(timezone=True),nullable=False))
    for t in ('external_truth_operation','external_truth_webhook_receipt','external_truth_bank_feed_receipt'):_immutable(t,'IMMUTABLE_EXTERNAL_TRUTH_EVIDENCE')

def downgrade():
    for t in ('external_truth_bank_feed_receipt','external_truth_webhook_receipt','external_truth_operation'):
        op.drop_table(t)
