"""Production connector runtime enforcement, webhook and reconciliation.

Freeze the schema at revision0076. Importing current business metadata previously
created the future0113/0114 reconciliation fields before their migrations ran,
which broke a clean PostgreSQL or SQLite upgrade with duplicate columns.
Existing databases that already applied0076 are not rewritten by this correction.
"""
from alembic import op
import sqlalchemy as sa

revision = '0076_126e14322d21'
down_revision = '0075_442bc0d513d1'
branch_labels = None
depends_on = None

metadata = sa.MetaData()
TABLES = [
    sa.Table('connector_runtime_authorization', metadata,
        sa.Column('runtime_authorization_id', sa.String(length=64), nullable=False, primary_key=True),
        sa.Column('connector_id', sa.String(length=64), nullable=False),
        sa.Column('operation_type', sa.String(length=64), nullable=False),
        sa.Column('decision', sa.String(length=16), nullable=False),
        sa.Column('reason_codes_json', sa.JSON(), nullable=False),
        sa.Column('evidence_hash', sa.String(length=64), nullable=False),
        sa.Column('decided_at', sa.DateTime(timezone=True), nullable=False),
        sa.Index('ix_connector_runtime_authorization_connector_id', 'connector_id', unique=False),
        sa.Index('ix_connector_runtime_authorization_decision', 'decision', unique=False),
        sa.Index('ix_connector_runtime_authorization_operation_type', 'operation_type', unique=False),
    ),
    sa.Table('connector_runtime_operation', metadata,
        sa.Column('runtime_operation_id', sa.String(length=64), nullable=False, primary_key=True),
        sa.Column('connector_id', sa.String(length=64), nullable=False),
        sa.Column('operation_type', sa.String(length=64), nullable=False),
        sa.Column('idempotency_key', sa.String(length=128), nullable=False),
        sa.Column('request_hash', sa.String(length=64), nullable=False),
        sa.Column('request_json', sa.JSON(), nullable=False),
        sa.Column('state', sa.String(length=32), nullable=False),
        sa.Column('external_operation_id', sa.String(length=128), nullable=True),
        sa.Column('response_json', sa.JSON(), nullable=False),
        sa.Column('authorization_id', sa.String(length=64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('connector_id', 'idempotency_key', name='uq_connector_runtime_idempotency'),
        sa.Index('ix_connector_runtime_operation_authorization_id', 'authorization_id', unique=False),
        sa.Index('ix_connector_runtime_operation_connector_id', 'connector_id', unique=False),
        sa.Index('ix_connector_runtime_operation_external_operation_id', 'external_operation_id', unique=False),
        sa.Index('ix_connector_runtime_operation_operation_type', 'operation_type', unique=False),
        sa.Index('ix_connector_runtime_operation_state', 'state', unique=False),
    ),
    sa.Table('connector_webhook_receipt', metadata,
        sa.Column('webhook_receipt_id', sa.String(length=64), nullable=False, primary_key=True),
        sa.Column('connector_id', sa.String(length=64), nullable=False),
        sa.Column('delivery_id', sa.String(length=128), nullable=False),
        sa.Column('signature_fingerprint', sa.String(length=64), nullable=False),
        sa.Column('payload_hash', sa.String(length=64), nullable=False),
        sa.Column('signature_valid', sa.Boolean(), nullable=False),
        sa.Column('replay_rejected', sa.Boolean(), nullable=False),
        sa.Column('state', sa.String(length=24), nullable=False),
        sa.Column('received_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('connector_id', 'delivery_id', name='uq_connector_webhook_delivery'),
        sa.Index('ix_connector_webhook_receipt_connector_id', 'connector_id', unique=False),
        sa.Index('ix_connector_webhook_receipt_state', 'state', unique=False),
    ),
    sa.Table('connector_runtime_observation', metadata,
        sa.Column('runtime_observation_id', sa.String(length=64), nullable=False, primary_key=True),
        sa.Column('runtime_operation_id', sa.String(length=64), nullable=False),
        sa.Column('source', sa.String(length=24), nullable=False),
        sa.Column('external_state', sa.String(length=32), nullable=False),
        sa.Column('supplier_reference', sa.String(length=128), nullable=True),
        sa.Column('evidence_json', sa.JSON(), nullable=False),
        sa.Column('evidence_hash', sa.String(length=64), nullable=False),
        sa.Column('observed_at', sa.DateTime(timezone=True), nullable=False),
        sa.Index('ix_connector_runtime_observation_external_state', 'external_state', unique=False),
        sa.Index('ix_connector_runtime_observation_runtime_operation_id', 'runtime_operation_id', unique=False),
        sa.Index('ix_connector_runtime_observation_source', 'source', unique=False),
    ),
    sa.Table('connector_runtime_reconciliation', metadata,
        sa.Column('reconciliation_id', sa.String(length=64), nullable=False, primary_key=True),
        sa.Column('runtime_operation_id', sa.String(length=64), nullable=False),
        sa.Column('state', sa.String(length=32), nullable=False),
        sa.Column('attempt_count', sa.Integer(), nullable=False),
        sa.Column('max_attempts', sa.Integer(), nullable=False),
        sa.Column('next_attempt_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('manual_review_reason', sa.String(length=256), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Index('ix_connector_runtime_reconciliation_runtime_operation_id', 'runtime_operation_id', unique=True),
        sa.Index('ix_connector_runtime_reconciliation_state', 'state', unique=False),
    ),
    sa.Table('connector_runtime_safety_event', metadata,
        sa.Column('runtime_safety_event_id', sa.String(length=64), nullable=False, primary_key=True),
        sa.Column('connector_id', sa.String(length=64), nullable=False),
        sa.Column('event_type', sa.String(length=64), nullable=False),
        sa.Column('severity', sa.String(length=16), nullable=False),
        sa.Column('reason_codes_json', sa.JSON(), nullable=False),
        sa.Column('evidence_hash', sa.String(length=64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Index('ix_connector_runtime_safety_event_connector_id', 'connector_id', unique=False),
        sa.Index('ix_connector_runtime_safety_event_event_type', 'event_type', unique=False),
        sa.Index('ix_connector_runtime_safety_event_severity', 'severity', unique=False),
    ),
]


def upgrade():
    bind = op.get_bind()
    for table in TABLES:
        table.create(bind, checkfirst=True)


def downgrade():
    bind = op.get_bind()
    for table in reversed(TABLES):
        table.drop(bind, checkfirst=True)
