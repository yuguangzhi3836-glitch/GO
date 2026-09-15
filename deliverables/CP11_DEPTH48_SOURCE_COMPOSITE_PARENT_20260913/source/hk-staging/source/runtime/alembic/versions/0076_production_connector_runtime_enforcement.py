"""Production connector runtime enforcement, webhook and reconciliation."""
from alembic import op
import sqlalchemy as sa

revision = '0076_126e14322d21'
down_revision = '0075_442bc0d513d1'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'connector_runtime_authorization',
        sa.Column('runtime_authorization_id', sa.String(64), primary_key=True),
        sa.Column('connector_id', sa.String(64), nullable=False),
        sa.Column('operation_type', sa.String(64), nullable=False),
        sa.Column('decision', sa.String(16), nullable=False),
        sa.Column('reason_codes_json', sa.JSON(), nullable=False),
        sa.Column('evidence_hash', sa.String(64), nullable=False),
        sa.Column('decided_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_connector_runtime_authorization_connector_id', 'connector_runtime_authorization', ['connector_id'])
    op.create_index('ix_connector_runtime_authorization_operation_type', 'connector_runtime_authorization', ['operation_type'])
    op.create_index('ix_connector_runtime_authorization_decision', 'connector_runtime_authorization', ['decision'])

    op.create_table(
        'connector_runtime_operation',
        sa.Column('runtime_operation_id', sa.String(64), primary_key=True),
        sa.Column('connector_id', sa.String(64), nullable=False),
        sa.Column('operation_type', sa.String(64), nullable=False),
        sa.Column('idempotency_key', sa.String(128), nullable=False),
        sa.Column('request_hash', sa.String(64), nullable=False),
        sa.Column('request_json', sa.JSON(), nullable=False),
        sa.Column('state', sa.String(32), nullable=False),
        sa.Column('external_operation_id', sa.String(128), nullable=True),
        sa.Column('response_json', sa.JSON(), nullable=False),
        sa.Column('authorization_id', sa.String(64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('connector_id', 'idempotency_key', name='uq_connector_runtime_idempotency'),
    )
    op.create_index('ix_connector_runtime_operation_connector_id', 'connector_runtime_operation', ['connector_id'])
    op.create_index('ix_connector_runtime_operation_operation_type', 'connector_runtime_operation', ['operation_type'])
    op.create_index('ix_connector_runtime_operation_state', 'connector_runtime_operation', ['state'])
    op.create_index('ix_connector_runtime_operation_external_operation_id', 'connector_runtime_operation', ['external_operation_id'])
    op.create_index('ix_connector_runtime_operation_authorization_id', 'connector_runtime_operation', ['authorization_id'])

    op.create_table(
        'connector_webhook_receipt',
        sa.Column('webhook_receipt_id', sa.String(64), primary_key=True),
        sa.Column('connector_id', sa.String(64), nullable=False),
        sa.Column('delivery_id', sa.String(128), nullable=False),
        sa.Column('signature_fingerprint', sa.String(64), nullable=False),
        sa.Column('payload_hash', sa.String(64), nullable=False),
        sa.Column('signature_valid', sa.Boolean(), nullable=False),
        sa.Column('replay_rejected', sa.Boolean(), nullable=False),
        sa.Column('state', sa.String(24), nullable=False),
        sa.Column('received_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('connector_id', 'delivery_id', name='uq_connector_webhook_delivery'),
    )
    op.create_index('ix_connector_webhook_receipt_connector_id', 'connector_webhook_receipt', ['connector_id'])
    op.create_index('ix_connector_webhook_receipt_state', 'connector_webhook_receipt', ['state'])

    op.create_table(
        'connector_runtime_observation',
        sa.Column('runtime_observation_id', sa.String(64), primary_key=True),
        sa.Column('runtime_operation_id', sa.String(64), nullable=False),
        sa.Column('source', sa.String(24), nullable=False),
        sa.Column('external_state', sa.String(32), nullable=False),
        sa.Column('supplier_reference', sa.String(128), nullable=True),
        sa.Column('evidence_json', sa.JSON(), nullable=False),
        sa.Column('evidence_hash', sa.String(64), nullable=False),
        sa.Column('observed_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_connector_runtime_observation_runtime_operation_id', 'connector_runtime_observation', ['runtime_operation_id'])
    op.create_index('ix_connector_runtime_observation_source', 'connector_runtime_observation', ['source'])
    op.create_index('ix_connector_runtime_observation_external_state', 'connector_runtime_observation', ['external_state'])

    op.create_table(
        'connector_runtime_reconciliation',
        sa.Column('reconciliation_id', sa.String(64), primary_key=True),
        sa.Column('runtime_operation_id', sa.String(64), nullable=False),
        sa.Column('state', sa.String(32), nullable=False),
        sa.Column('attempt_count', sa.Integer(), nullable=False),
        sa.Column('max_attempts', sa.Integer(), nullable=False),
        sa.Column('next_attempt_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('manual_review_reason', sa.String(256), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        'ix_connector_runtime_reconciliation_runtime_operation_id',
        'connector_runtime_reconciliation',
        ['runtime_operation_id'],
        unique=True,
    )
    op.create_index('ix_connector_runtime_reconciliation_state', 'connector_runtime_reconciliation', ['state'])

    op.create_table(
        'connector_runtime_safety_event',
        sa.Column('runtime_safety_event_id', sa.String(64), primary_key=True),
        sa.Column('connector_id', sa.String(64), nullable=False),
        sa.Column('event_type', sa.String(64), nullable=False),
        sa.Column('severity', sa.String(16), nullable=False),
        sa.Column('reason_codes_json', sa.JSON(), nullable=False),
        sa.Column('evidence_hash', sa.String(64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_connector_runtime_safety_event_connector_id', 'connector_runtime_safety_event', ['connector_id'])
    op.create_index('ix_connector_runtime_safety_event_event_type', 'connector_runtime_safety_event', ['event_type'])
    op.create_index('ix_connector_runtime_safety_event_severity', 'connector_runtime_safety_event', ['severity'])


def downgrade():
    op.drop_table('connector_runtime_safety_event')
    op.drop_table('connector_runtime_reconciliation')
    op.drop_table('connector_runtime_observation')
    op.drop_table('connector_webhook_receipt')
    op.drop_table('connector_runtime_operation')
    op.drop_table('connector_runtime_authorization')
