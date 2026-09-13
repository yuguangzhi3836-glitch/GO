"""Signed travel facts and versioned flight-linked ride adjustments; no legacy facts are upgraded."""
from alembic import op
import sqlalchemy as sa

revision = '0126_travel_operational_facts'
down_revision = '0125_regional_queue'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('travel_fact_authority',
        sa.Column('authority_id', sa.String(64), nullable=False, primary_key=True),
        sa.Column('provider_id', sa.String(64), nullable=False),
        sa.Column('environment', sa.String(24), nullable=False),
        sa.Column('source_type', sa.String(48), nullable=False),
        sa.Column('contract_json', sa.JSON(), nullable=False),
        sa.Column('contract_hash', sa.String(64), nullable=False),
        sa.Column('public_key_hex', sa.String(64), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('created_by', sa.String(64), nullable=False),
        sa.Column('approved_by', sa.String(64), nullable=True),
        sa.Column('valid_from_ms', sa.BigInteger(), nullable=False),
        sa.Column('valid_until_ms', sa.BigInteger(), nullable=False),
        sa.Column('created_ms', sa.BigInteger(), nullable=False),
        sa.Column('updated_ms', sa.BigInteger(), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.CheckConstraint("status IN ('DRAFT','ACTIVE','REVOKED')", name='ck_travel_fact_authority_status'))
    op.create_table('travel_operational_fact',
        sa.Column('fact_id', sa.String(64), nullable=False, primary_key=True),
        sa.Column('authority_id', sa.String(64), sa.ForeignKey('travel_fact_authority.authority_id'), nullable=False),
        sa.Column('provider_id', sa.String(64), nullable=False),
        sa.Column('event_id', sa.String(128), nullable=False),
        sa.Column('kind', sa.String(24), nullable=False),
        sa.Column('stream_key', sa.String(64), nullable=False),
        sa.Column('order_id', sa.String(64), nullable=True),
        sa.Column('source_sequence', sa.BigInteger(), nullable=False),
        sa.Column('payload_json', sa.JSON(), nullable=False),
        sa.Column('payload_hash', sa.String(64), nullable=False),
        sa.Column('signature_hex', sa.String(128), nullable=False),
        sa.Column('observed_ms', sa.BigInteger(), nullable=False),
        sa.Column('expires_ms', sa.BigInteger(), nullable=False),
        sa.Column('created_ms', sa.BigInteger(), nullable=False),
        sa.UniqueConstraint('provider_id','event_id',name='uq_travel_fact_event'),
        sa.UniqueConstraint('provider_id','stream_key','source_sequence',name='uq_travel_fact_sequence'))
    op.create_table('ride_service_policy_snapshot',
        sa.Column('ride_order_id', sa.String(64), nullable=False, primary_key=True),
        sa.Column('policy_json', sa.JSON(), nullable=False),
        sa.Column('policy_hash', sa.String(64), nullable=False),
        sa.Column('accepted_ms', sa.BigInteger(), nullable=False))
    op.create_table('ride_flight_binding_v2',
        sa.Column('ride_order_id', sa.String(64), nullable=False, primary_key=True),
        sa.Column('account_id', sa.String(64), nullable=False),
        sa.Column('flight_key', sa.String(64), nullable=False),
        sa.Column('identity_json', sa.JSON(), nullable=False),
        sa.Column('authority_id', sa.String(64), sa.ForeignKey('travel_fact_authority.authority_id'), nullable=False),
        sa.Column('policy_hash', sa.String(64), nullable=False),
        sa.Column('tracking_enabled', sa.Boolean(), nullable=False),
        sa.Column('delay_protection_enabled', sa.Boolean(), nullable=False),
        sa.Column('original_pickup_at', sa.String(48), nullable=False),
        sa.Column('current_pickup_at', sa.String(48), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('last_fact_id', sa.String(64), nullable=True),
        sa.Column('updated_ms', sa.BigInteger(), nullable=False))
    op.create_table('ride_flight_adjustment',
        sa.Column('adjustment_id', sa.String(64), nullable=False, primary_key=True),
        sa.Column('ride_order_id', sa.String(64), nullable=False),
        sa.Column('fact_id', sa.String(64), sa.ForeignKey('travel_operational_fact.fact_id'), nullable=False),
        sa.Column('binding_revision', sa.Integer(), nullable=False),
        sa.Column('policy_hash', sa.String(64), nullable=False),
        sa.Column('expected_pickup_at', sa.String(48), nullable=False),
        sa.Column('proposed_pickup_at', sa.String(48), nullable=False),
        sa.Column('free_wait_minutes', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(24), nullable=False),
        sa.Column('request_hash', sa.String(64), nullable=False),
        sa.Column('provider_reference', sa.String(256), nullable=True),
        sa.Column('result_json', sa.JSON(), nullable=True),
        sa.Column('created_ms', sa.BigInteger(), nullable=False),
        sa.Column('updated_ms', sa.BigInteger(), nullable=False),
        sa.UniqueConstraint('ride_order_id','fact_id','binding_revision',name='uq_ride_flight_adjustment_fact'),
        sa.CheckConstraint("status IN ('PENDING','DISPATCHED','UNKNOWN','CONFIRMED','REJECTED','SUPERSEDED','HOLD')",name='ck_ride_flight_adjustment_status'))
    op.create_index('ix_travel_fact_authority_provider_id', 'travel_fact_authority', ['provider_id'])
    op.create_index('ix_travel_operational_fact_order_id', 'travel_operational_fact', ['order_id'])
    op.create_index('ix_travel_fact_stream', 'travel_operational_fact', ['kind', 'stream_key', 'created_ms'])
    op.create_index('ix_ride_flight_binding_v2_flight_key', 'ride_flight_binding_v2', ['flight_key'])
    op.create_index('ix_ride_flight_adjustment_ride_order_id', 'ride_flight_adjustment', ['ride_order_id'])


def downgrade():
    connection=op.get_bind()
    if connection.scalar(sa.text('SELECT count(*) FROM ride_flight_adjustment')):raise RuntimeError('TRAVEL_FACT_DATA_PRESENT_RESTORE_BACKUP_FOR_DOWNGRADE')
    if connection.scalar(sa.text('SELECT count(*) FROM ride_flight_binding_v2')):raise RuntimeError('TRAVEL_FACT_DATA_PRESENT_RESTORE_BACKUP_FOR_DOWNGRADE')
    if connection.scalar(sa.text('SELECT count(*) FROM ride_service_policy_snapshot')):raise RuntimeError('TRAVEL_FACT_DATA_PRESENT_RESTORE_BACKUP_FOR_DOWNGRADE')
    if connection.scalar(sa.text('SELECT count(*) FROM travel_operational_fact')):raise RuntimeError('TRAVEL_FACT_DATA_PRESENT_RESTORE_BACKUP_FOR_DOWNGRADE')
    if connection.scalar(sa.text('SELECT count(*) FROM travel_fact_authority')):raise RuntimeError('TRAVEL_FACT_DATA_PRESENT_RESTORE_BACKUP_FOR_DOWNGRADE')
    op.drop_table('ride_flight_adjustment')
    op.drop_table('ride_flight_binding_v2')
    op.drop_table('ride_service_policy_snapshot')
    op.drop_table('travel_operational_fact')
    op.drop_table('travel_fact_authority')
