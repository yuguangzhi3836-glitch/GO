from __future__ import annotations
from datetime import datetime
from sqlalchemy import BigInteger, Boolean, DateTime, Integer, String, Text, JSON, UniqueConstraint, Index, Float, ForeignKey, CheckConstraint, Uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

class Base(DeclarativeBase):
    pass

class VerticalPaymentDeadlineRow(Base):
    __tablename__ = 'vertical_payment_deadline'
    vertical: Mapped[str] = mapped_column(String(16), primary_key=True)
    order_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    account_id: Mapped[str] = mapped_column(String(64), nullable=False)
    created_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    expires_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    terms_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False)
    finalized_ms: Mapped[int | None] = mapped_column(BigInteger)
    reason: Mapped[str | None] = mapped_column(String(96))
    __table_args__ = (
        CheckConstraint("vertical IN ('RAIL','ATTRACTION','RIDE','RENTAL')", name='ck_payment_deadline_vertical'),
        CheckConstraint("state IN ('OPEN','PAYMENT_STARTED','CANCELLED','EXPIRED','REVIEW')", name='ck_payment_deadline_state'),
        CheckConstraint('created_ms >= 0 AND expires_ms > created_ms', name='ck_payment_deadline_bounds'),
        Index('ix_payment_deadline_due', 'state', 'expires_ms', 'vertical', 'order_id'),
    )

class VerticalCapacityBucketRow(Base):
    __tablename__ = 'vertical_capacity_bucket'
    bucket_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    vertical: Mapped[str] = mapped_column(String(16), nullable=False)
    resource_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    capacity: Mapped[int] = mapped_column(Integer, nullable=False)
    allocated: Mapped[int] = mapped_column(Integer, nullable=False)
    __table_args__ = (
        CheckConstraint("vertical IN ('RAIL','ATTRACTION')", name='ck_capacity_vertical'),
        CheckConstraint('capacity >= 0 AND allocated >= 0 AND allocated <= capacity', name='ck_capacity_bounds'),
    )

class VerticalCapacityClaimRow(Base):
    __tablename__ = 'vertical_capacity_claim'
    vertical: Mapped[str] = mapped_column(String(16), primary_key=True)
    order_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    slot: Mapped[str] = mapped_column(String(64), primary_key=True)
    bucket_id: Mapped[str] = mapped_column(String(64), ForeignKey('vertical_capacity_bucket.bucket_id'), nullable=False, index=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    created_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    released_ms: Mapped[int | None] = mapped_column(BigInteger)
    __table_args__ = (
        CheckConstraint("state IN ('ALLOCATED','RELEASED')", name='ck_capacity_claim_state'),
        CheckConstraint('quantity > 0', name='ck_capacity_claim_quantity'),
    )

class FlightChangePlanRow(Base):
    __tablename__ = 'flight_change_plan'
    quote_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    order_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    account_id: Mapped[str] = mapped_column(String(64), nullable=False)
    plan_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    plan_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class FlightChangeResolutionRow(Base):
    __tablename__ = 'flight_change_resolution'
    quote_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    order_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    account_id: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    request_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    terms_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    result_json: Mapped[dict | None] = mapped_column(JSON)
    lease_token: Mapped[str | None] = mapped_column(String(64))
    lease_until_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    created_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    completed_ms: Mapped[int | None] = mapped_column(BigInteger)
    __table_args__ = (
        CheckConstraint("state IN ('PENDING','COMPLETED')", name='ck_flight_resolution_state'),
        CheckConstraint('attempt >= 0 AND lease_until_ms >= 0', name='ck_flight_resolution_lease'),
    )

class RailChangeResolutionRow(Base):
    __tablename__ = 'rail_change_resolution'
    quote_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    order_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    account_id: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    request_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    terms_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    result_json: Mapped[dict | None] = mapped_column(JSON)
    lease_token: Mapped[str | None] = mapped_column(String(64))
    lease_until_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    created_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    completed_ms: Mapped[int | None] = mapped_column(BigInteger)
    __table_args__ = (
        CheckConstraint("state IN ('PENDING','COMPLETED')", name='ck_rail_resolution_state'),
        CheckConstraint('attempt >= 0 AND lease_until_ms >= 0', name='ck_rail_resolution_lease'),
    )

class VerticalRefundOperationRow(Base):
    __tablename__ = 'vertical_refund_operation'
    vertical: Mapped[str] = mapped_column(String(16), primary_key=True)
    order_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    account_id: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    quote_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    adjustment_ids_json: Mapped[list] = mapped_column(JSON, nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    result_json: Mapped[dict | None] = mapped_column(JSON)
    lease_token: Mapped[str | None] = mapped_column(String(64))
    lease_until_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    created_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    completed_ms: Mapped[int | None] = mapped_column(BigInteger)
    __table_args__ = (
        CheckConstraint("vertical IN ('RAIL','ATTRACTION')", name='ck_refund_operation_vertical'),
        CheckConstraint("state IN ('PENDING','COMPLETED')", name='ck_refund_operation_state'),
        CheckConstraint('attempt >= 0 AND lease_until_ms >= 0', name='ck_refund_operation_lease'),
    )

class VerticalPrebookContractRow(Base):
    __tablename__ = 'vertical_prebook_contract'
    prebook_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    vertical: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    issued_account_id: Mapped[str | None] = mapped_column(String(64))
    owner_id: Mapped[str | None] = mapped_column(String(64), index=True)
    order_id: Mapped[str | None] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    terms_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    terms_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    consumed_hash: Mapped[str | None] = mapped_column(String(64))
    expires_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    consumed_ms: Mapped[int | None] = mapped_column(BigInteger)
    __table_args__ = (
        UniqueConstraint('vertical','order_id',name='uq_vertical_prebook_order'),
        CheckConstraint("state IN ('QUOTED','CONSUMED')",name='ck_vertical_prebook_contract_state'),
    )

class TravelFactAuthorityRow(Base):
    __tablename__ = 'travel_fact_authority'
    authority_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    provider_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    environment: Mapped[str] = mapped_column(String(24), nullable=False)
    source_type: Mapped[str] = mapped_column(String(48), nullable=False)
    contract_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    contract_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    public_key_hex: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    created_by: Mapped[str] = mapped_column(String(64), nullable=False)
    approved_by: Mapped[str | None] = mapped_column(String(64))
    valid_from_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    valid_until_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    updated_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    __table_args__ = (CheckConstraint("status IN ('DRAFT','ACTIVE','REVOKED')", name='ck_travel_fact_authority_status'),)


class TravelOperationalFactRow(Base):
    __tablename__ = 'travel_operational_fact'
    fact_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    authority_id: Mapped[str] = mapped_column(ForeignKey('travel_fact_authority.authority_id'), nullable=False)
    provider_id: Mapped[str] = mapped_column(String(64), nullable=False)
    event_id: Mapped[str] = mapped_column(String(128), nullable=False)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    stream_key: Mapped[str] = mapped_column(String(64), nullable=False)
    order_id: Mapped[str | None] = mapped_column(String(64), index=True)
    source_sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    signature_hex: Mapped[str] = mapped_column(String(128), nullable=False)
    observed_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    expires_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    __table_args__ = (
        UniqueConstraint('provider_id','event_id',name='uq_travel_fact_event'),
        UniqueConstraint('provider_id','stream_key','source_sequence',name='uq_travel_fact_sequence'),
        Index('ix_travel_fact_stream','kind','stream_key','created_ms'),
    )


class RideServicePolicyRow(Base):
    __tablename__ = 'ride_service_policy_snapshot'
    ride_order_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    policy_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    policy_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    accepted_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)


class RideFlightBindingV2Row(Base):
    __tablename__ = 'ride_flight_binding_v2'
    ride_order_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    account_id: Mapped[str] = mapped_column(String(64), nullable=False)
    flight_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    identity_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    authority_id: Mapped[str] = mapped_column(ForeignKey('travel_fact_authority.authority_id'), nullable=False)
    policy_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    tracking_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    delay_protection_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    original_pickup_at: Mapped[str] = mapped_column(String(48), nullable=False)
    current_pickup_at: Mapped[str] = mapped_column(String(48), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    last_fact_id: Mapped[str | None] = mapped_column(String(64))
    updated_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)


class RideFlightAdjustmentRow(Base):
    __tablename__ = 'ride_flight_adjustment'
    adjustment_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    ride_order_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    fact_id: Mapped[str] = mapped_column(ForeignKey('travel_operational_fact.fact_id'), nullable=False)
    binding_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    policy_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expected_pickup_at: Mapped[str] = mapped_column(String(48), nullable=False)
    proposed_pickup_at: Mapped[str] = mapped_column(String(48), nullable=False)
    free_wait_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_reference: Mapped[str | None] = mapped_column(String(256))
    result_json: Mapped[dict | None] = mapped_column(JSON)
    created_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    updated_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    __table_args__ = (
        UniqueConstraint('ride_order_id','fact_id','binding_revision',name='uq_ride_flight_adjustment_fact'),
        CheckConstraint("status IN ('PENDING','DISPATCHED','UNKNOWN','CONFIRMED','REJECTED','SUPERSEDED','HOLD')",name='ck_ride_flight_adjustment_status'),
    )


class RegionalQueueRow(Base):
    __tablename__ = 'regional_build_queue'
    message_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    topic: Mapped[str] = mapped_column(String(96), nullable=False)
    run_id: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    available_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    lease_until_ms: Mapped[int | None] = mapped_column(BigInteger)
    lease_token: Mapped[str | None] = mapped_column(String(64))
    last_code: Mapped[str | None] = mapped_column(String(96))
    result_json: Mapped[dict | None] = mapped_column(JSON)
    created_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    updated_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    __table_args__ = (
        Index('ix_regional_queue_ready', 'topic', 'status', 'available_ms'),
        Index('ix_regional_queue_run', 'run_id', 'status'),
        CheckConstraint('attempt >= 0 AND max_attempts BETWEEN 1 AND 20', name='ck_regional_queue_bounds'),
        CheckConstraint("status IN ('QUEUED','RUNNING','SUCCEEDED','DEAD','SUPERSEDED')", name='ck_regional_queue_status'),
    )


class AutonomyTaskRow(Base):
    __tablename__ = 'autonomy_task'
    task_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    environment: Mapped[str] = mapped_column(String(24), nullable=False)
    cell_id: Mapped[str] = mapped_column(String(8), nullable=False)
    operation: Mapped[str] = mapped_column(String(96), nullable=False)
    handler_version: Mapped[str] = mapped_column(String(64), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    submitted_by: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    next_step: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    event_seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    available_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    lease_until_ms: Mapped[int | None] = mapped_column(BigInteger)
    lease_token: Mapped[str | None] = mapped_column(String(64))
    worker_id: Mapped[str | None] = mapped_column(String(128))
    external_started: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_code: Mapped[str | None] = mapped_column(String(128))
    result_json: Mapped[dict | None] = mapped_column(JSON)
    created_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    updated_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    __table_args__ = (
        Index('ix_autonomy_task_queue', 'environment', 'status', 'available_ms'),
        Index('ix_autonomy_task_cell', 'environment', 'cell_id', 'created_ms'),
        CheckConstraint('attempt >= 0 AND max_attempts BETWEEN 1 AND 20 AND next_step >= 0', name='ck_autonomy_task_bounds'),
        CheckConstraint("status IN ('QUEUED','RUNNING','RETRY_WAIT','HOLD','SUCCEEDED','FAILED','DEAD','UNCERTAIN','CANCELLED')", name='ck_autonomy_task_status'),
    )


class AutonomyStepRow(Base):
    __tablename__ = 'autonomy_step'
    task_id: Mapped[str] = mapped_column(ForeignKey('autonomy_task.task_id'), primary_key=True)
    step_no: Mapped[int] = mapped_column(Integer, primary_key=True)
    result_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    result_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    completed_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)


class AutonomyEventRow(Base):
    __tablename__ = 'autonomy_event'
    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_id: Mapped[str | None] = mapped_column(ForeignKey('autonomy_task.task_id'), index=True)
    environment: Mapped[str] = mapped_column(String(24), nullable=False)
    cell_id: Mapped[str] = mapped_column(String(8), nullable=False)
    event_type: Mapped[str] = mapped_column(String(48), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(128), nullable=False)
    details_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    __table_args__ = (UniqueConstraint('task_id', 'sequence', name='uq_autonomy_event_sequence'),)


class AutonomyCellControlRow(Base):
    __tablename__ = 'autonomy_cell_control'
    environment: Mapped[str] = mapped_column(String(24), primary_key=True)
    cell_id: Mapped[str] = mapped_column(String(8), primary_key=True)
    paused: Mapped[bool] = mapped_column(Boolean, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_by: Mapped[str] = mapped_column(String(64), nullable=False)
    updated_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)


class AutonomyQualificationRow(Base):
    __tablename__ = 'autonomy_qualification'
    qualification_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    record_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    expires_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)


class OfferRow(Base):
    __tablename__ = "offer_snapshot"
    offer_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    hotel_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    room_type_id: Mapped[str] = mapped_column(String(64), nullable=False)
    rate_plan_id: Mapped[str] = mapped_column(String(64), nullable=False)
    total_amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    check_in: Mapped[str] = mapped_column(String(10), nullable=False)
    check_out: Mapped[str] = mapped_column(String(10), nullable=False)
    official_direct: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    fare_rule_id: Mapped[str] = mapped_column(String(64), nullable=False)
    connector_id: Mapped[str] = mapped_column(String(64), nullable=False, default="conn_mock_hotel", index=True)
    supplier_id: Mapped[str | None] = mapped_column(String(64), index=True)
    base_amount_minor: Mapped[int | None] = mapped_column(BigInteger)
    tax_amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    fee_amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    meal_plan: Mapped[str] = mapped_column(String(32), nullable=False, default="ROOM_ONLY")
    refundable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    cancellation_deadline: Mapped[str | None] = mapped_column(String(64))
    inventory_units: Mapped[int | None] = mapped_column(Integer)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class PrebookRow(Base):
    __tablename__ = "prebook"
    prebook_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    offer_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    total_amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    hold_type: Mapped[str] = mapped_column(String(16), nullable=False, default="SOFT")
    inventory_held: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    price_locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    fare_rule_id: Mapped[str | None] = mapped_column(String(64))
    benefits_fingerprint: Mapped[str | None] = mapped_column(String(64))

class OrderRow(Base):
    __tablename__ = "hotel_order_runtime"
    order_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    prebook_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    hotel_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    account_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    total_amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    supplier_confirmation_no: Mapped[str | None] = mapped_column(String(128))
    supplier_id: Mapped[str | None] = mapped_column(String(64), index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class PaymentRow(Base):
    __tablename__ = "payment_runtime"
    payment_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    order_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    payment_type: Mapped[str] = mapped_column(String(48), nullable=False, default="ORIGINAL_BOOKING")
    external_operation_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PaymentOrchestrationRow(Base):
    __tablename__ = "payment_booking_orchestration"
    orchestration_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    order_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    payment_id: Mapped[str | None] = mapped_column(String(64), index=True)
    phase: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    supplier_confirmation_no: Mapped[str | None] = mapped_column(String(128))
    compensation_status: Mapped[str] = mapped_column(String(32), nullable=False, default="NONE")
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class EventRow(Base):
    __tablename__ = "order_event_runtime"
    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    aggregate_type: Mapped[str] = mapped_column(String(64), nullable=False)
    aggregate_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class OutboxRow(Base):
    __tablename__ = "transactional_outbox"
    outbox_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    topic: Mapped[str] = mapped_column(String(128), nullable=False, default="domain.events")
    event_type: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    aggregate_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="PENDING", index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lock_token: Mapped[str | None] = mapped_column(String(64), index=True)
    worker_id: Mapped[str | None] = mapped_column(String(128))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dead_lettered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class OutboxDeadLetterRow(Base):
    __tablename__ = "outbox_dead_letter"
    dead_letter_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    outbox_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    event_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(96), nullable=False)
    aggregate_id: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text)
    dead_lettered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class IdempotencyRow(Base):
    __tablename__ = "idempotency_record_runtime"
    idempotency_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    operation: Mapped[str] = mapped_column(String(96), primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response_code: Mapped[int] = mapped_column(Integer, nullable=False)
    response_body: Mapped[dict] = mapped_column(JSON, nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class ExternalOperationRow(Base):
    """Durable saga guard for exactly-once business effect around external systems."""
    __tablename__ = "external_operation"
    operation_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    operation_type: Mapped[str] = mapped_column(String(64), nullable=False)
    aggregate_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    business_key: Mapped[str] = mapped_column(String(160), nullable=False, unique=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    external_reference: Mapped[str | None] = mapped_column(String(128))
    request_payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    result_payload: Mapped[dict | None] = mapped_column(JSON)
    last_error: Mapped[str | None] = mapped_column(Text)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

class WebhookInboxRow(Base):
    __tablename__ = "webhook_inbox"
    webhook_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    connector_id: Mapped[str] = mapped_column(String(64), nullable=False)
    external_event_id: Mapped[str] = mapped_column(String(128), nullable=False)
    aggregate_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(96), nullable=False)
    external_sequence: Mapped[int | None] = mapped_column(BigInteger)
    signature_valid: Mapped[bool] = mapped_column(Boolean, nullable=False)
    raw_payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    processing_error: Mapped[str | None] = mapped_column(Text)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (UniqueConstraint("connector_id", "external_event_id", name="uq_webhook_connector_event"),)

class ConnectorCursorRow(Base):
    __tablename__ = "connector_event_cursor"
    connector_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    aggregate_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    last_sequence: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    last_external_event_id: Mapped[str | None] = mapped_column(String(128))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

Index("ix_outbox_claim", OutboxRow.status, OutboxRow.available_at, OutboxRow.locked_at, OutboxRow.outbox_id)
Index("ix_external_operation_recovery", ExternalOperationRow.status, ExternalOperationRow.next_retry_at)
Index("ix_webhook_pending", WebhookInboxRow.status, WebhookInboxRow.received_at)

class ConnectorCertificationRow(Base):
    __tablename__ = "connector_certification"
    certification_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    connector_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    report: Mapped[dict] = mapped_column(JSON, nullable=False)
    certified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class ConnectorHealthRow(Base):
    __tablename__ = "connector_health"
    connector_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    healthy: Mapped[bool] = mapped_column(Boolean, nullable=False)
    detail: Mapped[dict] = mapped_column(JSON, nullable=False)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class ReconciliationRunRow(Base):
    __tablename__ = "connector_reconciliation"
    reconciliation_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    connector_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    local_status: Mapped[str] = mapped_column(String(32), nullable=False)
    external_status: Mapped[str | None] = mapped_column(String(32))
    result: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    error: Mapped[str | None] = mapped_column(Text)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class HotelExternalIdentityRow(Base):
    __tablename__ = "hotel_external_identity_runtime"
    identity_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    connector_id: Mapped[str] = mapped_column(String(64), nullable=False)
    external_hotel_id: Mapped[str] = mapped_column(String(160), nullable=False)
    hotel_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    match_confidence_bps: Mapped[int] = mapped_column(Integer, nullable=False, default=10000)
    match_method: Mapped[str] = mapped_column(String(64), nullable=False, default="CONTRACTED_MAPPING")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="ACTIVE", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint("connector_id","external_hotel_id",name="uq_runtime_connector_external_hotel"),)

class ConnectorPropertyMappingAuditRow(Base):
    __tablename__ = "connector_property_mapping_audit"
    audit_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    connector_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    external_hotel_id: Mapped[str] = mapped_column(String(160), nullable=False)
    hotel_id: Mapped[str | None] = mapped_column(String(64), index=True)
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    detail: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class SupplierConnectorOnboardingRow(Base):
    __tablename__ = "supplier_connector_onboarding"
    onboarding_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    supplier_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    connector_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    environment: Mapped[str] = mapped_column(String(24), nullable=False, default="SANDBOX")
    status: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    rollout_percent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_certification_id: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (UniqueConstraint("supplier_id", "connector_id", "environment", name="uq_supplier_connector_onboarding"),)

class ConnectorCredentialRow(Base):
    __tablename__ = "connector_credential"
    credential_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    onboarding_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    connector_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    environment: Mapped[str] = mapped_column(String(24), nullable=False)
    secret_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    secret_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    field_names: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    vault_provider: Mapped[str] = mapped_column(String(32), nullable=False, default="LOCAL_FERNET")
    key_version: Mapped[str] = mapped_column(String(32), nullable=False, default="v1")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="ACTIVE", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

class PropertyMappingCandidateRow(Base):
    __tablename__ = "property_mapping_candidate"
    mapping_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    onboarding_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    connector_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    external_hotel_id: Mapped[str] = mapped_column(String(160), nullable=False)
    proposed_hotel_id: Mapped[str | None] = mapped_column(String(64), index=True)
    external_name: Mapped[str | None] = mapped_column(String(240))
    external_address: Mapped[str | None] = mapped_column(Text)
    confidence_bps: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    match_method: Mapped[str] = mapped_column(String(64), nullable=False, default="MANUAL")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="PROPOSED", index=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(64))
    review_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (UniqueConstraint("onboarding_id", "external_hotel_id", name="uq_onboarding_external_hotel"),)

class ConnectorActivationAuditRow(Base):
    __tablename__ = "connector_activation_audit"
    audit_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    onboarding_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    from_status: Mapped[str] = mapped_column(String(40), nullable=False)
    to_status: Mapped[str] = mapped_column(String(40), nullable=False)
    reason: Mapped[str] = mapped_column(String(160), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(64), nullable=False)
    detail: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

Index("ix_onboarding_status", SupplierConnectorOnboardingRow.status, SupplierConnectorOnboardingRow.updated_at)
Index("ix_property_mapping_review", PropertyMappingCandidateRow.onboarding_id, PropertyMappingCandidateRow.status)


class ConnectorSlaWindowRow(Base):
    __tablename__ = "connector_sla_window"
    connector_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    success_rate_bps: Mapped[int] = mapped_column(Integer, nullable=False, default=10000)
    confirmation_latency_ms_p95: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cancel_success_rate_bps: Mapped[int] = mapped_column(Integer, nullable=False, default=10000)
    inventory_accuracy_bps: Mapped[int] = mapped_column(Integer, nullable=False, default=10000)
    price_consistency_bps: Mapped[int] = mapped_column(Integer, nullable=False, default=10000)
    composite_score_bps: Mapped[int] = mapped_column(Integer, nullable=False, default=10000, index=True)
    sample_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    health_status: Mapped[str] = mapped_column(String(24), nullable=False, default="HEALTHY", index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class RoutingDecisionRow(Base):
    __tablename__ = "connector_routing_decision"
    decision_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    operation: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    hotel_id: Mapped[str | None] = mapped_column(String(64), index=True)
    request_key: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    selected_connector_id: Mapped[str | None] = mapped_column(String(64), index=True)
    candidate_connector_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    fallback_connector_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    reason_codes: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    candidate_snapshot: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

Index("ix_routing_decision_hotel_time", RoutingDecisionRow.hotel_id, RoutingDecisionRow.created_at)


class RoomExternalIdentityRow(Base):
    __tablename__ = "room_external_identity_runtime"
    identity_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    connector_id: Mapped[str] = mapped_column(String(64), nullable=False)
    external_room_id: Mapped[str] = mapped_column(String(160), nullable=False)
    canonical_room_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    match_confidence_bps: Mapped[int] = mapped_column(Integer, nullable=False, default=10000)
    match_method: Mapped[str] = mapped_column(String(64), nullable=False, default="CONTRACTED_MAPPING")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="ACTIVE", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (UniqueConstraint("connector_id","external_room_id",name="uq_room_connector_external"),)

class OfferMergeDecisionRow(Base):
    __tablename__ = "offer_merge_decision"
    decision_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    hotel_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    canonical_room_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    selected_offer_id: Mapped[str] = mapped_column(String(64), nullable=False)
    selected_connector_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    alternate_offer_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    reason_codes: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    conflicts: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    candidate_snapshot: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

class OfferDriftStateRow(Base):
    __tablename__ = "offer_drift_state"
    drift_key: Mapped[str] = mapped_column(String(512), primary_key=True)
    connector_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    hotel_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    canonical_room_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class OfferDriftEventRow(Base):
    __tablename__ = "offer_drift_event"
    drift_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    drift_key: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    connector_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    hotel_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    canonical_room_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    changed_fields: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    before_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    after_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="OPEN", index=True)

Index("ix_offer_merge_hotel_room", OfferMergeDecisionRow.hotel_id, OfferMergeDecisionRow.canonical_room_id, OfferMergeDecisionRow.created_at)
Index("ix_offer_drift_hotel_time", OfferDriftEventRow.hotel_id, OfferDriftEventRow.detected_at)


class PrebookRevalidationRow(Base):
    __tablename__ = "prebook_revalidation"
    revalidation_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    offer_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    prebook_id: Mapped[str | None] = mapped_column(String(64), index=True)
    connector_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    original_total_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    supplier_total_minor: Mapped[int | None] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    price_status: Mapped[str] = mapped_column(String(32), nullable=False)
    inventory_status: Mapped[str] = mapped_column(String(32), nullable=False)
    policy_status: Mapped[str] = mapped_column(String(32), nullable=False)
    benefit_status: Mapped[str] = mapped_column(String(32), nullable=False)
    hold_type: Mapped[str] = mapped_column(String(16), nullable=False)
    lock_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

class BookingConsistencyCheckRow(Base):
    __tablename__ = "booking_consistency_check"
    check_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    order_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    prebook_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    stage: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    result: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    reason_codes: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

Index("ix_prebook_revalidation_offer_time", PrebookRevalidationRow.offer_id, PrebookRevalidationRow.created_at)
Index("ix_booking_consistency_order_stage", BookingConsistencyCheckRow.order_id, BookingConsistencyCheckRow.stage, BookingConsistencyCheckRow.checked_at)

class FareRuleRow(Base):
    __tablename__ = "hotel_fare_rule_runtime"
    fare_rule_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    fare_family: Mapped[str] = mapped_column(String(32), nullable=False, default="GO_STANDARD")
    cooling_off_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    change_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    change_fee_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=10000)
    stay_credit_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    stay_credit_validity_days: Mapped[int] = mapped_column(Integer, nullable=False, default=365)
    stay_credit_scope: Mapped[str] = mapped_column(String(32), nullable=False, default="PROPERTY_ONLY")
    tiers_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class CatalogCashFareQuoteRow(Base):
    __tablename__ = 'catalog_cash_fare_quote'
    quote_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    order_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    quote_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class CatalogCashFareOperationRow(Base):
    __tablename__ = 'catalog_cash_fare_operation'
    operation_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    order_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    quote_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    state: Mapped[str] = mapped_column(String(40), nullable=False)
    plan_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    plan_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    payment_json: Mapped[dict | None] = mapped_column(JSON)
    supplier_reference: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class CatalogCashFareClaimRow(Base):
    __tablename__ = 'catalog_cash_fare_claim'
    order_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    operation_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)

class CancellationQuoteRow(Base):
    __tablename__ = "cancellation_quote"
    quote_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    order_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    paid_amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    cancellation_fee_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    refund_amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    rule_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class RefundRow(Base):
    __tablename__ = "refund_runtime"
    refund_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    order_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    payment_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    provider_refund_id: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

class ChangeQuoteRow(Base):
    __tablename__ = "change_quote"
    quote_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    order_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    new_check_in: Mapped[str] = mapped_column(String(10), nullable=False)
    new_check_out: Mapped[str] = mapped_column(String(10), nullable=False)
    old_value_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    new_value_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    fare_difference_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    change_fee_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    amount_due_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    rule_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class OrderChangeRow(Base):
    __tablename__ = "order_change_runtime"
    change_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    order_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    quote_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    new_check_in: Mapped[str] = mapped_column(String(10), nullable=False)
    new_check_out: Mapped[str] = mapped_column(String(10), nullable=False)
    additional_payment_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    supplier_confirmation_no: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

class StayCreditRow(Base):
    __tablename__ = "stay_credit_runtime"
    stay_credit_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    original_order_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    account_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    property_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    credit_value_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    redemption_order_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    redeemed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

class StayCreditRedemptionQuoteRow(Base):
    __tablename__ = "stay_credit_redemption_quote"
    quote_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    stay_credit_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    offer_id: Mapped[str] = mapped_column(String(64), nullable=False)
    new_value_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    credit_value_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    amount_due_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    forfeited_difference_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class SupplierFaultCaseRow(Base):
    __tablename__ = "supplier_fault_case"
    case_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    order_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    supplier_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    fault_party: Mapped[str | None] = mapped_column(String(32), index=True)
    evidence_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    decision_json: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

class SupplierFinancialAccountRow(Base):
    __tablename__ = "supplier_financial_account"
    supplier_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    settlement_available_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    reserve_available_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    bank_available_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    debit_mandate_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    negative_balance_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class SupplierLiabilityRow(Base):
    __tablename__ = "supplier_liability_runtime"
    liability_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    case_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    supplier_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    order_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    actual_paid_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    refund_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    compensation_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    total_return_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    settlement_offset_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    reserve_offset_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    bank_debit_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    protection_fund_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    negative_balance_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    decision_id: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cleared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

class CompensationPaymentRow(Base):
    __tablename__ = "compensation_payment_runtime"
    compensation_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    liability_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    order_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    source_breakdown: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

Index("ix_supplier_fault_case_supplier_status", SupplierFaultCaseRow.supplier_id, SupplierFaultCaseRow.status)
Index("ix_supplier_liability_supplier_status", SupplierLiabilityRow.supplier_id, SupplierLiabilityRow.status)

class ProtectionFundLedgerRow(Base):
    __tablename__ = "consumer_protection_fund_ledger"
    entry_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    liability_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    order_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    supplier_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    entry_type: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class ReviewSessionRow(Base):
    __tablename__ = "review_session"
    review_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    order_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    hotel_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    account_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    verified_stay: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    raw_star_input: Mapped[int | None] = mapped_column(Integer)
    trigger_source: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ELIGIBLE", index=True)
    trust_weight_bps: Mapped[int] = mapped_column(Integer, nullable=False, default=10000)
    public_status: Mapped[str] = mapped_column(String(24), nullable=False, default="PENDING")
    experience_score_milli: Mapped[int | None] = mapped_column(Integer)
    dimension_result: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    content_text: Mapped[str | None] = mapped_column(Text)
    voice_ref: Mapped[str | None] = mapped_column(String(256))
    photo_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class ReviewTagRow(Base):
    __tablename__ = "review_tag_runtime"
    review_tag_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    review_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(48), nullable=False)
    tag_code: Mapped[str] = mapped_column(String(64), nullable=False)
    polarity: Mapped[str] = mapped_column(String(16), nullable=False)
    severity: Mapped[str] = mapped_column(String(24), nullable=False, default="NORMAL")
    mapped_dimensions: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (UniqueConstraint("review_id", "tag_code", name="uq_review_tag_code"),)

class RiskEventRuntimeRow(Base):
    __tablename__ = "risk_event_runtime"
    risk_event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    hotel_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    order_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    review_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    risk_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="R2")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="CANDIDATE", index=True)
    confidence_bps: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    decision_id: Mapped[str | None] = mapped_column(String(64), index=True)
    rule_version: Mapped[str] = mapped_column(String(32), nullable=False, default="RISK_RULES_1.0")
    public_notice: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

class RiskEvidenceRuntimeRow(Base):
    __tablename__ = "risk_evidence_runtime"
    evidence_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    risk_event_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_actor: Mapped[str] = mapped_column(String(32), nullable=False)
    evidence_type: Mapped[str] = mapped_column(String(48), nullable=False)
    content_ref: Mapped[str | None] = mapped_column(String(512))
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    credibility_bps: Mapped[int] = mapped_column(Integer, nullable=False, default=5000)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class RiskRemediationRow(Base):
    __tablename__ = "risk_remediation_runtime"
    remediation_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    risk_event_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    supplier_action: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="SUBMITTED")
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

class JudgmentHookRow(Base):
    __tablename__ = "judgment_hook_runtime"
    hook_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    hotel_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(String(48), nullable=False)
    source_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="REQUESTED", index=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

Index("ix_review_pending_account", ReviewSessionRow.account_id, ReviewSessionRow.status, ReviewSessionRow.created_at)
Index("ix_risk_hotel_status", RiskEventRuntimeRow.hotel_id, RiskEventRuntimeRow.status, RiskEventRuntimeRow.created_at)

class JudgmentEvidencePackageRow(Base):
    __tablename__ = "judgment_evidence_package"
    package_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    hotel_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    source_summary: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    feature_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    excluded_commercial_fields: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    sealed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class JudgmentRuntimeRow(Base):
    __tablename__ = "judgment_runtime"
    judgment_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    hotel_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    evidence_package_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    go_score_milli: Mapped[int] = mapped_column(Integer, nullable=False)
    dimension_result: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    explanation: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    confidence_bps: Mapped[int] = mapped_column(Integer, nullable=False, default=5000)
    model_version: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    rule_version: Mapped[str] = mapped_column(String(64), nullable=False)
    good_hotel_standard_version_id: Mapped[str | None] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="ACTIVE", index=True)
    public_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class RecommendationDecisionRow(Base):
    __tablename__ = "recommendation_decision_runtime"
    decision_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    hotel_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    judgment_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    reason_codes: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    public_go_score_milli: Mapped[int | None] = mapped_column(Integer)
    rule_version: Mapped[str] = mapped_column(String(64), nullable=False)
    good_hotel_standard_version_id: Mapped[str | None] = mapped_column(String(64), index=True)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

Index("ix_judgment_hotel_created", JudgmentRuntimeRow.hotel_id, JudgmentRuntimeRow.created_at)
Index("ix_recommendation_hotel_created", RecommendationDecisionRow.hotel_id, RecommendationDecisionRow.created_at)

Index("ix_order_supplier_status_updated", OrderRow.supplier_id, OrderRow.status, OrderRow.updated_at)
Index("ix_refund_status_created", RefundRow.status, RefundRow.created_at)
Index("ix_stay_credit_status_expiry", StayCreditRow.status, StayCreditRow.expires_at)
Index("ix_risk_status_updated", RiskEventRuntimeRow.status, RiskEventRuntimeRow.updated_at)
Index("ix_liability_status_created", SupplierLiabilityRow.status, SupplierLiabilityRow.created_at)
Index("ix_judgment_status_created", JudgmentRuntimeRow.status, JudgmentRuntimeRow.created_at)

# Sprint 1R: production identity, RBAC, approval and immutable audit trail.
class IdentityUserRow(Base):
    __tablename__ = "identity_user"
    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    username: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)  # SUPPLIER_USER / GO_ADMIN / SERVICE_ACCOUNT
    supplier_id: Mapped[str | None] = mapped_column(String(64), index=True)
    roles: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="ACTIVE", index=True)
    token_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    mfa_secret_ciphertext: Mapped[str | None] = mapped_column(Text)
    mfa_enabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sso_provider: Mapped[str | None] = mapped_column(String(64), index=True)
    sso_subject: Mapped[str | None] = mapped_column(String(256), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class AuthSessionRow(Base):
    __tablename__ = "auth_session"
    session_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="ACTIVE", index=True)
    client_ip: Mapped[str | None] = mapped_column(String(128))
    user_agent: Mapped[str | None] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    auth_method: Mapped[str] = mapped_column(String(32), nullable=False, default="PASSWORD")
    mfa_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    csrf_token_hash: Mapped[str | None] = mapped_column(String(64))

class RefreshTokenRow(Base):
    __tablename__ = "refresh_token"
    token_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="ACTIVE", index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

class ApprovalRequestRow(Base):
    __tablename__ = "approval_request"
    approval_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    operation_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    subject_type: Mapped[str] = mapped_column(String(64), nullable=False)
    subject_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    requested_by: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    approved_by: Mapped[str | None] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="PENDING", index=True)
    request_payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    approval_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

class AuditEventRow(Base):
    __tablename__ = "audit_event"
    audit_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    actor_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    actor_type: Mapped[str] = mapped_column(String(32), nullable=False)
    supplier_id: Mapped[str | None] = mapped_column(String(64), index=True)
    roles: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    session_id: Mapped[str | None] = mapped_column(String(64), index=True)
    action: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    resource_id: Mapped[str | None] = mapped_column(String(128), index=True)
    request_id: Mapped[str | None] = mapped_column(String(128), index=True)
    client_ip: Mapped[str | None] = mapped_column(String(128))
    http_method: Mapped[str | None] = mapped_column(String(16))
    path: Mapped[str | None] = mapped_column(String(512))
    before_state: Mapped[dict | None] = mapped_column(JSON)
    after_state: Mapped[dict | None] = mapped_column(JSON)
    decision_id: Mapped[str | None] = mapped_column(String(64), index=True)
    evidence_id: Mapped[str | None] = mapped_column(String(64), index=True)
    approval_id: Mapped[str | None] = mapped_column(String(64), index=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

Index("ix_identity_supplier_status", IdentityUserRow.supplier_id, IdentityUserRow.status)
Index("ix_audit_actor_created", AuditEventRow.actor_id, AuditEventRow.created_at)
Index("ix_audit_resource_created", AuditEventRow.resource_type, AuditEventRow.resource_id, AuditEventRow.created_at)

class OIDCLoginStateRow(Base):
    __tablename__ = "oidc_login_state"
    state: Mapped[str] = mapped_column(String(128), primary_key=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    nonce: Mapped[str] = mapped_column(String(128), nullable=False)
    code_verifier_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    redirect_uri: Mapped[str] = mapped_column(String(512), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

# Sprint 1V: observability, incident control and production-readiness evidence.
class IncidentControlRow(Base):
    __tablename__ = "incident_control"
    control_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    scope: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="INACTIVE", index=True)
    reason: Mapped[str | None] = mapped_column(Text)
    activated_by: Mapped[str | None] = mapped_column(String(64), index=True)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class SecuritySignalRow(Base):
    __tablename__ = "security_signal"
    signal_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    signal_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="OPEN", index=True)
    request_id: Mapped[str | None] = mapped_column(String(128), index=True)
    actor_id: Mapped[str | None] = mapped_column(String(64), index=True)
    client_ip: Mapped[str | None] = mapped_column(String(128))
    metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

class ReadinessGateRunRow(Base):
    __tablename__ = "readiness_gate_run"
    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    environment: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    checks_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    blocker_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    executed_by: Mapped[str | None] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

# Sprint 1Y: Consumer GO ID, traveler profiles and tokenized payment references.
class ConsumerProfileRow(Base):
    __tablename__ = "consumer_profile"
    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    go_id: Mapped[str] = mapped_column(String(32), nullable=False, unique=True, index=True)
    email: Mapped[str] = mapped_column(String(256), nullable=False, unique=True, index=True)
    display_name: Mapped[str | None] = mapped_column(String(128))
    phone_ciphertext: Mapped[str | None] = mapped_column(Text)
    locale: Mapped[str] = mapped_column(String(16), nullable=False, default="zh-CN")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="ACTIVE", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class TravelerProfileRow(Base):
    __tablename__ = "consumer_traveler"
    traveler_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    full_name: Mapped[str] = mapped_column(String(160), nullable=False)
    date_of_birth: Mapped[str | None] = mapped_column(String(10))
    nationality: Mapped[str | None] = mapped_column(String(3))
    document_type: Mapped[str | None] = mapped_column(String(32))
    document_ciphertext: Mapped[str | None] = mapped_column(Text)
    relationship_type: Mapped[str] = mapped_column(String(32), nullable=False, default="SELF")
    booking_permission: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    guardian_traveler_id: Mapped[str | None] = mapped_column(String(64), index=True)
    guardian_consent_status: Mapped[str | None] = mapped_column(String(24))
    source_type: Mapped[str] = mapped_column(String(48), nullable=False, default="MANUAL")
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="ACTIVE", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class ConsumerPaymentMethodRow(Base):
    __tablename__ = "consumer_payment_method"
    payment_method_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(48), nullable=False)
    provider_token_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    brand: Mapped[str | None] = mapped_column(String(32))
    last4: Mapped[str | None] = mapped_column(String(4))
    expiry_month: Mapped[int | None] = mapped_column(Integer)
    expiry_year: Mapped[int | None] = mapped_column(Integer)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="ACTIVE", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class ConsumerWalletRow(Base):
    __tablename__ = "consumer_wallet"
    wallet_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

Index("ix_consumer_traveler_user_status", TravelerProfileRow.user_id, TravelerProfileRow.status)
Index("ix_consumer_payment_user_status", ConsumerPaymentMethodRow.user_id, ConsumerPaymentMethodRow.status)

# Sprint 1Z: Native mobile devices, push registrations and notification inbox.
class ConsumerDeviceRow(Base):
    __tablename__ = "consumer_device"
    device_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    platform: Mapped[str] = mapped_column(String(16), nullable=False)  # IOS / ANDROID
    app_version: Mapped[str | None] = mapped_column(String(32))
    device_model: Mapped[str | None] = mapped_column(String(128))
    os_version: Mapped[str | None] = mapped_column(String(64))
    push_provider: Mapped[str | None] = mapped_column(String(16))  # APNS / FCM
    push_token_ciphertext: Mapped[str | None] = mapped_column(Text)
    push_token_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    notifications_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="ACTIVE", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class ConsumerNotificationRow(Base):
    __tablename__ = "consumer_notification"
    notification_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    notification_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    deep_link: Mapped[str | None] = mapped_column(Text)
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    delivery_status: Mapped[str] = mapped_column(String(24), nullable=False, default="PENDING", index=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

Index("ix_consumer_device_user_status", ConsumerDeviceRow.user_id, ConsumerDeviceRow.status)
Index("ix_consumer_notification_user_created", ConsumerNotificationRow.user_id, ConsumerNotificationRow.created_at)

# Sprint 2B: provider delivery receipt lifecycle. One row per provider message/device delivery attempt.
class MobilePushReceiptRow(Base):
    __tablename__ = "mobile_push_receipt"
    receipt_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    notification_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    device_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(24), nullable=False)
    provider_message_id: Mapped[str | None] = mapped_column(String(160), index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="SUBMITTED", index=True)
    error_code: Mapped[str | None] = mapped_column(String(96))
    error_detail: Mapped[str | None] = mapped_column(Text)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

Index("ix_mobile_push_receipt_status_submitted", MobilePushReceiptRow.status, MobilePushReceiptRow.submitted_at)

# Sprint 2A: mobile engagement orchestration. Jobs are append-first and deduped by domain-event intent.
class MobileEngagementJobRow(Base):
    __tablename__ = "mobile_engagement_job"
    job_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    dedupe_key: Mapped[str] = mapped_column(String(160), nullable=False, unique=True, index=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    order_id: Mapped[str | None] = mapped_column(String(64), index=True)
    review_id: Mapped[str | None] = mapped_column(String(64), index=True)
    event_type: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    notification_type: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    deep_link: Mapped[str | None] = mapped_column(Text)
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="SCHEDULED", index=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

Index("ix_mobile_engagement_due", MobileEngagementJobRow.status, MobileEngagementJobRow.scheduled_at)

# Sprint 3A Flight vertical ----------------------------------------------------
class FlightOfferRow(Base):
    __tablename__ = "flight_offer_runtime"
    offer_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    origin: Mapped[str] = mapped_column(String(8), nullable=False, index=True)
    destination: Mapped[str] = mapped_column(String(8), nullable=False, index=True)
    departure_date: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    carrier_code: Mapped[str] = mapped_column(String(8), nullable=False)
    flight_number: Mapped[str] = mapped_column(String(16), nullable=False)
    cabin: Mapped[str] = mapped_column(String(24), nullable=False)
    fare_family: Mapped[str] = mapped_column(String(48), nullable=False)
    total_amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    tax_amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    baggage: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    change_policy: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    refund_policy: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    segments: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class FlightPrebookRow(Base):
    __tablename__ = "flight_prebook_runtime"
    prebook_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    offer_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    total_amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    price_locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    inventory_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class FlightOrderRow(Base):
    __tablename__ = "flight_order_runtime"
    order_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    account_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    prebook_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    total_amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    passengers: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    payment_method_id: Mapped[str | None] = mapped_column(String(64))
    pnr: Mapped[str | None] = mapped_column(String(16), index=True)
    ticket_numbers: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    current_itinerary: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class FlightChangeQuoteRow(Base):
    __tablename__ = "flight_change_quote_runtime"
    quote_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    order_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    new_departure_date: Mapped[str] = mapped_column(String(10), nullable=False)
    new_flight_number: Mapped[str] = mapped_column(String(16), nullable=False)
    fare_difference_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    change_fee_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    total_due_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="QUOTED")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class FlightRefundRow(Base):
    __tablename__ = "flight_refund_runtime"
    refund_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    order_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    refund_fee_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    refund_amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RailOfferRow(Base):
    __tablename__ = "rail_offer_runtime"
    offer_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    origin_station: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    destination_station: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    travel_date: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    train_no: Mapped[str] = mapped_column(String(16), nullable=False)
    seat_class: Mapped[str] = mapped_column(String(32), nullable=False)
    total_amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    departure_time: Mapped[str] = mapped_column(String(8), nullable=False)
    arrival_time: Mapped[str] = mapped_column(String(8), nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    stations: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    change_policy: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    refund_policy: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    inventory_left: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class RailPrebookRow(Base):
    __tablename__ = "rail_prebook_runtime"
    prebook_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    offer_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    total_amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    price_locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    inventory_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class RailOrderRow(Base):
    __tablename__ = "rail_order_runtime"
    order_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    account_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    prebook_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    total_amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    passengers: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    payment_method_id: Mapped[str | None] = mapped_column(String(64))
    booking_reference: Mapped[str | None] = mapped_column(String(128), index=True)
    ticket_numbers: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    current_journey: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class RailChangeQuoteRow(Base):
    __tablename__ = "rail_change_quote_runtime"
    quote_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    order_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    new_travel_date: Mapped[str] = mapped_column(String(10), nullable=False)
    new_train_no: Mapped[str] = mapped_column(String(16), nullable=False)
    new_seat_class: Mapped[str] = mapped_column(String(32), nullable=False)
    fare_difference_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    change_fee_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    total_due_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="QUOTED")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class RailRefundRow(Base):
    __tablename__ = "rail_refund_runtime"
    refund_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    order_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    refund_fee_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    refund_amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MobilityRideOrderRow(Base):
    __tablename__="mobility_ride_order_runtime"
    order_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    account_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    status: Mapped[str]=mapped_column(String(32),nullable=False)
    pickup: Mapped[str]=mapped_column(String(255),nullable=False)
    dropoff: Mapped[str]=mapped_column(String(255),nullable=False)
    pickup_at: Mapped[str]=mapped_column(String(40),nullable=False)
    vehicle_class: Mapped[str]=mapped_column(String(40),nullable=False)
    total_amount_minor: Mapped[int]=mapped_column(BigInteger,nullable=False)
    currency: Mapped[str]=mapped_column(String(3),nullable=False)
    passengers: Mapped[list]=mapped_column(JSON,nullable=False)
    flight_no: Mapped[str|None]=mapped_column(String(24))
    supplier_reference: Mapped[str|None]=mapped_column(String(32))
    created_at: Mapped[datetime]=mapped_column(DateTime,nullable=False)
    updated_at: Mapped[datetime]=mapped_column(DateTime,nullable=False)

class MobilityRentalOrderRow(Base):
    __tablename__="mobility_rental_order_runtime"
    order_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    account_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    status: Mapped[str]=mapped_column(String(32),nullable=False)
    pickup_location: Mapped[str]=mapped_column(String(255),nullable=False)
    return_location: Mapped[str]=mapped_column(String(255),nullable=False)
    pickup_at: Mapped[str]=mapped_column(String(40),nullable=False)
    return_at: Mapped[str]=mapped_column(String(40),nullable=False)
    vehicle_class: Mapped[str]=mapped_column(String(40),nullable=False)
    insurance: Mapped[dict]=mapped_column(JSON,nullable=False)
    mileage: Mapped[dict]=mapped_column(JSON,nullable=False)
    deposit_minor: Mapped[int]=mapped_column(BigInteger,nullable=False)
    total_amount_minor: Mapped[int]=mapped_column(BigInteger,nullable=False)
    currency: Mapped[str]=mapped_column(String(3),nullable=False)
    drivers: Mapped[list]=mapped_column(JSON,nullable=False)
    supplier_reference: Mapped[str|None]=mapped_column(String(32))
    created_at: Mapped[datetime]=mapped_column(DateTime,nullable=False)
    updated_at: Mapped[datetime]=mapped_column(DateTime,nullable=False)

class RentalChangeQuoteRow(Base):
    __tablename__ = 'rental_change_quote'
    quote_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    order_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    old_pickup_at: Mapped[str] = mapped_column(String(40), nullable=False)
    old_return_at: Mapped[str] = mapped_column(String(40), nullable=False)
    new_pickup_at: Mapped[str] = mapped_column(String(40), nullable=False)
    new_return_at: Mapped[str] = mapped_column(String(40), nullable=False)
    old_amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    new_amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    difference_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    daily_rate_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    order_revision: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    refund_plan_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class MobilityRefundRow(Base):
    __tablename__="mobility_refund_runtime"
    refund_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    order_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    vertical: Mapped[str]=mapped_column(String(16),nullable=False)
    fee_minor: Mapped[int]=mapped_column(BigInteger,nullable=False)
    refund_amount_minor: Mapped[int]=mapped_column(BigInteger,nullable=False)
    currency: Mapped[str]=mapped_column(String(3),nullable=False)
    status: Mapped[str]=mapped_column(String(32),nullable=False)
    settlement_plan_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    created_at: Mapped[datetime]=mapped_column(DateTime,nullable=False)


class AttractionOrderRow(Base):
    __tablename__="attraction_order_runtime"
    order_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    account_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    status: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    product_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    product_name: Mapped[str]=mapped_column(String(255),nullable=False)
    product_type: Mapped[str]=mapped_column(String(24),nullable=False)
    destination: Mapped[str]=mapped_column(String(128),nullable=False)
    visit_date: Mapped[str]=mapped_column(String(24),nullable=False)
    session_time: Mapped[str|None]=mapped_column(String(24))
    ticket_type: Mapped[str]=mapped_column(String(64),nullable=False)
    quantity: Mapped[int]=mapped_column(Integer,nullable=False)
    eligibility: Mapped[dict]=mapped_column(JSON,nullable=False)
    voucher_type: Mapped[str]=mapped_column(String(24),nullable=False)
    voucher_code: Mapped[str|None]=mapped_column(String(128))
    total_amount_minor: Mapped[int]=mapped_column(BigInteger,nullable=False)
    currency: Mapped[str]=mapped_column(String(3),nullable=False)
    attendees: Mapped[list]=mapped_column(JSON,nullable=False)
    supplier_reference: Mapped[str|None]=mapped_column(String(64))
    created_at: Mapped[datetime]=mapped_column(DateTime,nullable=False)
    updated_at: Mapped[datetime]=mapped_column(DateTime,nullable=False)

class AttractionChangeQuoteRow(Base):
    __tablename__="attraction_change_quote_runtime"
    quote_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    order_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    new_visit_date: Mapped[str]=mapped_column(String(24),nullable=False)
    new_session_time: Mapped[str|None]=mapped_column(String(24))
    change_fee_minor: Mapped[int]=mapped_column(BigInteger,nullable=False,default=0)
    total_due_minor: Mapped[int]=mapped_column(BigInteger,nullable=False,default=0)
    currency: Mapped[str]=mapped_column(String(3),nullable=False)
    status: Mapped[str]=mapped_column(String(24),nullable=False,default="QUOTED")
    expires_at: Mapped[datetime]=mapped_column(DateTime,nullable=False)
    created_at: Mapped[datetime]=mapped_column(DateTime,nullable=False)

class AttractionRefundRow(Base):
    __tablename__="attraction_refund_runtime"
    refund_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    order_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    refund_fee_minor: Mapped[int]=mapped_column(BigInteger,nullable=False,default=0)
    refund_amount_minor: Mapped[int]=mapped_column(BigInteger,nullable=False)
    currency: Mapped[str]=mapped_column(String(3),nullable=False)
    status: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    created_at: Mapped[datetime]=mapped_column(DateTime,nullable=False)
    completed_at: Mapped[datetime|None]=mapped_column(DateTime)

# Sprint 3E Unified GO Trips ---------------------------------------------------
class GoJourneyRow(Base):
    __tablename__ = "go_journey_runtime"
    journey_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    account_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    destination_summary: Mapped[str | None] = mapped_column(String(255))
    starts_at: Mapped[str | None] = mapped_column(String(40), index=True)
    ends_at: Mapped[str | None] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="UPCOMING", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class GoJourneyItemRow(Base):
    __tablename__ = "go_journey_item_runtime"
    item_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    journey_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    account_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    vertical: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    order_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    subtitle: Mapped[str | None] = mapped_column(String(255))
    location: Mapped[str | None] = mapped_column(String(255))
    starts_at: Mapped[str | None] = mapped_column(String(40), index=True)
    ends_at: Mapped[str | None] = mapped_column(String(40))
    status_snapshot: Mapped[str] = mapped_column(String(32), nullable=False)
    facts_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    detail_route: Mapped[str] = mapped_column(String(64), nullable=False)
    sort_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

Index("ux_go_journey_order_once", GoJourneyItemRow.account_id, GoJourneyItemRow.vertical, GoJourneyItemRow.order_id, unique=True)

# Sprint 3F Journey Intelligence + Disruption Orchestration -------------------
class JourneyDisruptionSignalRow(Base):
    __tablename__ = "journey_disruption_signal"
    signal_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    journey_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    account_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_item_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_vertical: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    source_order_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    event_at: Mapped[str] = mapped_column(String(40), nullable=False)
    facts_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class JourneyImpactRow(Base):
    __tablename__ = "journey_impact_runtime"
    impact_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    signal_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    journey_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    account_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    affected_item_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    affected_vertical: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    affected_order_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    impact_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    confidence_milli: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    recommended_action_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class JourneyAdviceRow(Base):
    __tablename__ = "journey_advice_runtime"
    advice_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    journey_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    account_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    signal_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    recommended_actions_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    execution_boundary: Mapped[str] = mapped_column(String(96), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# Sprint 3G Proactive Journey Recovery + Option Comparison -------------------
class JourneyRecoveryPlanRow(Base):
    __tablename__ = "journey_recovery_plan"
    plan_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    journey_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    account_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    advice_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    currency: Mapped[str] = mapped_column(String(8), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    selected_option_ids_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    execution_boundary: Mapped[str] = mapped_column(String(96), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class JourneyRecoveryOptionRow(Base):
    __tablename__ = "journey_recovery_option"
    option_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    plan_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    journey_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    account_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    impact_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    vertical: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    order_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    option_type: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    subtitle: Mapped[str] = mapped_column(Text, nullable=False)
    total_delta_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(8), nullable=False)
    rank_score: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    execution_route: Mapped[str] = mapped_column(String(96), nullable=False)
    requires_user_confirmation: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    quote_facts_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

# Sprint 3H One-Click Recovery Orchestrator + Atomic User Intent ------------
class JourneyRecoveryExecutionRow(Base):
    __tablename__ = "journey_recovery_execution"
    execution_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    journey_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    account_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    plan_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    intent_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    intent_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    currency: Mapped[str] = mapped_column(String(8), nullable=False)
    quoted_delta_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    authorized_delta_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completed_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    action_required_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    intent_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class JourneyRecoveryExecutionItemRow(Base):
    __tablename__ = "journey_recovery_execution_item"
    execution_item_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    execution_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    option_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    journey_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    account_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    vertical: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    order_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    rule_version: Mapped[str] = mapped_column(String(64), nullable=False)
    quote_id: Mapped[str] = mapped_column(String(64), nullable=False)
    quoted_delta_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    revalidated_delta_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(8), nullable=False)
    payment_action_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    supplier_command_id: Mapped[str | None] = mapped_column(String(96))
    supplier_confirmation_id: Mapped[str | None] = mapped_column(String(96))
    status: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    failure_reason: Mapped[str | None] = mapped_column(String(96))
    reconciliation_state: Mapped[str] = mapped_column(String(40), nullable=False, default='NOT_REQUIRED', index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    facts_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class JourneyRecoveryExecutionEventRow(Base):
    __tablename__ = "journey_recovery_execution_event"
    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    execution_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    execution_item_id: Mapped[str | None] = mapped_column(String(64), index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    request_id: Mapped[str | None] = mapped_column(String(96))
    evidence_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

# Sprint 3I Durable Recovery Reconciliation + Supplier Adapter Contract ----
class JourneyRecoverySupplierOperationRow(Base):
    __tablename__ = "journey_recovery_supplier_operation"
    supplier_operation_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    execution_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    execution_item_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    vertical: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    adapter_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    supplier_idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    command_type: Mapped[str] = mapped_column(String(48), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    external_operation_id: Mapped[str | None] = mapped_column(String(128), index=True)
    supplier_confirmation_id: Mapped[str | None] = mapped_column(String(128), index=True)
    request_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    response_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class JourneyRecoveryReconciliationJobRow(Base):
    __tablename__ = "journey_recovery_reconciliation_job"
    reconciliation_job_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    supplier_operation_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    execution_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    execution_item_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    state: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    trigger_source: Mapped[str] = mapped_column(String(32), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=8)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    lease_token: Mapped[str | None] = mapped_column(String(96), index=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_error: Mapped[str | None] = mapped_column(Text)
    resolution_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class JourneyRecoveryReconciliationObservationRow(Base):
    __tablename__ = "journey_recovery_reconciliation_observation"
    observation_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    supplier_operation_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    execution_item_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    external_event_id: Mapped[str | None] = mapped_column(String(128), index=True)
    observed_status: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    supplier_confirmation_id: Mapped[str | None] = mapped_column(String(128))
    evidence_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

# Sprint 3J Recovery Command Ledger + Supplier Evidence Chain + Ops Control Plane
class JourneyRecoveryCommandLedgerRow(Base):
    __tablename__ = "journey_recovery_command_ledger"
    command_ledger_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    execution_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    execution_item_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    supplier_operation_id: Mapped[str | None] = mapped_column(String(64), index=True)
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)
    command_kind: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    actor_type: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(64), index=True)
    request_id: Mapped[str | None] = mapped_column(String(96), index=True)
    payment_id: Mapped[str | None] = mapped_column(String(64), index=True)
    refund_id: Mapped[str | None] = mapped_column(String(64), index=True)
    supplier_command_id: Mapped[str | None] = mapped_column(String(96), index=True)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    previous_hash: Mapped[str | None] = mapped_column(String(64))
    entry_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

class JourneyRecoveryEvidenceChainRow(Base):
    __tablename__ = "journey_recovery_evidence_chain"
    evidence_chain_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    execution_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    execution_item_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    supplier_operation_id: Mapped[str | None] = mapped_column(String(64), index=True)
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)
    evidence_kind: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    external_event_id: Mapped[str | None] = mapped_column(String(128), index=True)
    external_operation_id: Mapped[str | None] = mapped_column(String(128), index=True)
    supplier_confirmation_id: Mapped[str | None] = mapped_column(String(128), index=True)
    observed_status: Mapped[str | None] = mapped_column(String(40), index=True)
    evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    previous_hash: Mapped[str | None] = mapped_column(String(64))
    entry_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    evidence_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

class JourneyRecoveryOperationalCaseRow(Base):
    __tablename__ = "journey_recovery_operational_case"
    operational_case_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    execution_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    execution_item_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    supplier_operation_id: Mapped[str | None] = mapped_column(String(64), index=True)
    reconciliation_job_id: Mapped[str | None] = mapped_column(String(64), index=True)
    state: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    assigned_to: Mapped[str | None] = mapped_column(String(64), index=True)
    assignment_note: Mapped[str | None] = mapped_column(Text)
    manual_review_reason: Mapped[str | None] = mapped_column(String(128))
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sla_policy_id: Mapped[str | None] = mapped_column(String(64), index=True)
    queue_key: Mapped[str | None] = mapped_column(String(64), index=True)
    current_escalation_level: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    acknowledge_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    resolution_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    next_escalation_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_escalated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    playbook_key: Mapped[str | None] = mapped_column(String(64))
    closure_evidence_status: Mapped[str | None] = mapped_column(String(32), index=True)

class JourneyRecoverySlaPolicyRow(Base):
    __tablename__ = "journey_recovery_sla_policy"
    sla_policy_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    vertical: Mapped[str | None] = mapped_column(String(32), index=True)
    adapter_key: Mapped[str | None] = mapped_column(String(96), index=True)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    queue_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    acknowledge_sla_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    resolution_sla_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    escalation_steps_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    playbook_key: Mapped[str] = mapped_column(String(64), nullable=False)
    playbook_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    required_evidence_kinds_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class JourneyRecoveryOpsQueueRow(Base):
    __tablename__ = "journey_recovery_ops_queue"
    queue_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    timezone_name: Mapped[str] = mapped_column(String(64), nullable=False, default='UTC')
    on_call_owner: Mapped[str | None] = mapped_column(String(64), index=True)
    backup_owner: Mapped[str | None] = mapped_column(String(64), index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class JourneyRecoveryOperationalEventRow(Base):
    __tablename__ = "journey_recovery_operational_event"
    operational_event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    operational_case_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    actor_type: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(64), index=True)
    from_queue_key: Mapped[str | None] = mapped_column(String(64))
    to_queue_key: Mapped[str | None] = mapped_column(String(64), index=True)
    escalation_level: Mapped[int | None] = mapped_column(Integer)
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

# Sprint 3L Recovery Incident Intelligence + Supplier Reliability Memory
class JourneyRecoveryReliabilityProfileRow(Base):
    __tablename__ = "journey_recovery_reliability_profile"
    reliability_profile_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    vertical: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    adapter_key: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    async_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unknown_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    confirmed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    manual_review_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    avg_confirmation_seconds: Mapped[float | None] = mapped_column(Float)
    avg_webhook_lag_seconds: Mapped[float | None] = mapped_column(Float)
    avg_poll_attempts: Mapped[float | None] = mapped_column(Float)
    timeout_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    manual_review_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    confirmation_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    risk_band: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    recommended_initial_poll_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    recommended_max_poll_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    recommended_max_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    recommended_ack_multiplier: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    recommended_resolution_multiplier: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    metrics_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

class JourneyRecoveryReliabilityDecisionRow(Base):
    __tablename__ = "journey_recovery_reliability_decision"
    reliability_decision_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    execution_item_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    supplier_operation_id: Mapped[str | None] = mapped_column(String(64), index=True)
    reliability_profile_id: Mapped[str | None] = mapped_column(String(96), index=True)
    decision_kind: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    risk_band: Mapped[str] = mapped_column(String(16), nullable=False)
    parameters_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    explanation_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

# Sprint 3M Recovery Adaptive Strategy Governance
class JourneyRecoveryStrategyVersionRow(Base):
    __tablename__ = 'journey_recovery_strategy_version'
    strategy_version_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    min_sample_count: Mapped[int] = mapped_column(Integer, nullable=False, default=20)
    min_confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.8)
    confidence_level: Mapped[float] = mapped_column(Float, nullable=False, default=0.95)
    rollout_percent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    parameter_bounds_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    rollback_thresholds_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    requires_approval: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    approved_by: Mapped[str | None] = mapped_column(String(64), index=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rolled_back_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rollback_reason: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class JourneyRecoveryStrategyEvaluationRow(Base):
    __tablename__ = 'journey_recovery_strategy_evaluation'
    strategy_evaluation_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    strategy_version_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    reliability_profile_id: Mapped[str | None] = mapped_column(String(96), index=True)
    execution_item_id: Mapped[str | None] = mapped_column(String(64), index=True)
    mode: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    eligible: Mapped[bool] = mapped_column(Boolean, nullable=False)
    cohort_bucket: Mapped[int | None] = mapped_column(Integer)
    confidence_intervals_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    proposed_parameters_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    applied_parameters_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    clamp_events_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    reason_codes_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    supplier_fact_unchanged: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

# Sprint 3N Recovery Experimentation + Production Calibration
class JourneyRecoveryExperimentRow(Base):
    __tablename__ = 'journey_recovery_experiment'
    experiment_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    control_strategy_version_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    candidate_strategy_version_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    allocation_percent: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    min_sample_per_arm: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    significance_alpha: Mapped[float] = mapped_column(Float, nullable=False, default=0.05)
    primary_metric: Mapped[str] = mapped_column(String(64), nullable=False, default='confirmation_rate')
    stratification_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    promotion_gate_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    approved_by: Mapped[str | None] = mapped_column(String(64), index=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class JourneyRecoveryExperimentObservationRow(Base):
    __tablename__ = 'journey_recovery_experiment_observation'
    observation_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    experiment_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    execution_item_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    arm: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    vertical: Mapped[str | None] = mapped_column(String(32), index=True)
    adapter_key: Mapped[str | None] = mapped_column(String(96), index=True)
    confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    timeout: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    manual_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    confirmation_seconds: Mapped[float | None] = mapped_column(Float)
    metrics_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

class JourneyRecoveryExperimentDecisionRow(Base):
    __tablename__ = 'journey_recovery_experiment_decision'
    decision_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    experiment_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    decision: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    metrics_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    significance_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    strata_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    gate_results_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    reason_codes_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    supplier_fact_unchanged: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

class JourneyRecoveryCalibrationProfileRow(Base):
    __tablename__ = 'journey_recovery_calibration_profile'
    calibration_profile_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    vertical: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    adapter_key: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_experiment_id: Mapped[str | None] = mapped_column(String(64), index=True)
    calibrated_parameters_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    confidence_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    state: Mapped[str] = mapped_column(String(24), nullable=False, index=True, default='PROVISIONAL')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

# Sprint 3O Recovery Production Learning Registry + Provenance + Benchmark Governance
class JourneyRecoveryLearningRegistryRow(Base):
    __tablename__ = 'journey_recovery_learning_registry'
    learning_registry_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    vertical: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    adapter_key: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    reliability_profile_id: Mapped[str | None] = mapped_column(String(96), index=True)
    strategy_version_id: Mapped[str | None] = mapped_column(String(64), index=True)
    experiment_id: Mapped[str | None] = mapped_column(String(64), index=True)
    calibration_profile_id: Mapped[str | None] = mapped_column(String(96), index=True)
    benchmark_profile_id: Mapped[str | None] = mapped_column(String(96), index=True)
    state: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    freshness_state: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    revalidation_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    provenance_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    governance_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class JourneyRecoveryProvenanceEdgeRow(Base):
    __tablename__ = 'journey_recovery_provenance_edge'
    provenance_edge_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    learning_registry_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    from_kind: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    from_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    to_kind: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    to_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    relation: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    edge_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

class JourneyRecoveryBenchmarkProfileRow(Base):
    __tablename__ = 'journey_recovery_benchmark_profile'
    benchmark_profile_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    vertical: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    cohort_key: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    supplier_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    anonymization_k: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    benchmark_metrics_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    confidence_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    state: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

class JourneyRecoveryDriftAssessmentRow(Base):
    __tablename__ = 'journey_recovery_drift_assessment'
    drift_assessment_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    learning_registry_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    vertical: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    adapter_key: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    baseline_window_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    current_window_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    drift_metrics_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    drift_detected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    supplier_fact_unchanged: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

# Sprint 3P Recovery Data Quality + Benchmark Privacy + Learning Kill Switch
class JourneyRecoverySupplierIdentityMapRow(Base):
    __tablename__ = 'journey_recovery_supplier_identity_map'
    supplier_identity_map_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    vertical: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    adapter_key: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    supplier_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    mapping_state: Mapped[str] = mapped_column(String(24), nullable=False, default='ACTIVE', index=True)
    evidence_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (UniqueConstraint('vertical','adapter_key', name='uq_recovery_supplier_identity_vertical_adapter'),)

class JourneyRecoveryDataQualityAssessmentRow(Base):
    __tablename__ = 'journey_recovery_data_quality_assessment'
    data_quality_assessment_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    vertical: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    adapter_key: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    supplier_id: Mapped[str | None] = mapped_column(String(64), index=True)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    quality_state: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    contamination_detected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    anomaly_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    checks_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    action: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

class JourneyRecoverySampleQuarantineRow(Base):
    __tablename__ = 'journey_recovery_sample_quarantine'
    quarantine_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    vertical: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    adapter_key: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    source_kind: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    source_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    released: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    released_by: Mapped[str | None] = mapped_column(String(64), index=True)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

class JourneyRecoveryPrivacyBudgetRow(Base):
    __tablename__ = 'journey_recovery_privacy_budget'
    privacy_budget_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    scope_key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    epsilon_budget: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    epsilon_used: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    release_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    state: Mapped[str] = mapped_column(String(24), nullable=False, default='AVAILABLE', index=True)
    reset_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    governance_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class JourneyRecoveryLearningKillSwitchRow(Base):
    __tablename__ = 'journey_recovery_learning_kill_switch'
    kill_switch_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    scope_type: Mapped[str] = mapped_column(String(24), nullable=False, index=True)  # GLOBAL|VERTICAL|ADAPTER
    scope_key: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    reason: Mapped[str | None] = mapped_column(String(512))
    activated_by: Mapped[str | None] = mapped_column(String(64), index=True)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    deactivated_by: Mapped[str | None] = mapped_column(String(64), index=True)
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (UniqueConstraint('scope_type','scope_key', name='uq_recovery_learning_kill_scope'),)

# Sprint 3Q Recovery Learning Incident Response + Safe Rollback + Change Control
class JourneyRecoveryLearningIncidentRow(Base):
    __tablename__ = 'journey_recovery_learning_incident'
    incident_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    scope_type: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    scope_key: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    state: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    reason: Mapped[str] = mapped_column(String(512), nullable=False)
    opened_by: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    kill_switch_id: Mapped[str | None] = mapped_column(String(64), index=True)
    rollback_snapshot_id: Mapped[str | None] = mapped_column(String(64), index=True)
    affected_objects_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    postmortem_evidence_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    approved_resume_change_id: Mapped[str | None] = mapped_column(String(64), index=True)
    closed_by: Mapped[str | None] = mapped_column(String(64), index=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class JourneyRecoveryRollbackSnapshotRow(Base):
    __tablename__ = 'journey_recovery_rollback_snapshot'
    rollback_snapshot_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    incident_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    scope_type: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    scope_key: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    baseline_parameters_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    strategy_snapshot_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    experiment_snapshot_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    calibration_snapshot_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    learning_registry_snapshot_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    created_by: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

class JourneyRecoveryLearningChangeRequestRow(Base):
    __tablename__ = 'journey_recovery_learning_change_request'
    change_request_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    incident_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    change_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    state: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    requested_scope_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    resume_plan_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    change_window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    change_window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    requested_by: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    approved_by: Mapped[str | None] = mapped_column(String(64), index=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    executed_by: Mapped[str | None] = mapped_column(String(64), index=True)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    execution_result_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    supplier_fact_unchanged: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

class JourneyRecoveryLearningIncidentEventRow(Base):
    __tablename__ = 'journey_recovery_learning_incident_event'
    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    incident_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    actor_id: Mapped[str | None] = mapped_column(String(64), index=True)
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    supplier_fact_unchanged: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

# Sprint 3R Recovery Production Release Governance + Configuration Registry + Environment Promotion
class JourneyRecoveryConfigVersionRow(Base):
    __tablename__ = 'journey_recovery_config_version'
    config_version_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    config_key: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    config_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    scope_type: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    scope_key: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    source_ref_kind: Mapped[str | None] = mapped_column(String(48), index=True)
    source_ref_id: Mapped[str | None] = mapped_column(String(96), index=True)
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    created_by: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    supplier_fact_unchanged: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    __table_args__ = (UniqueConstraint('config_key','version_number', name='uq_recovery_config_key_version'),)

class JourneyRecoveryEnvironmentBindingRow(Base):
    __tablename__ = 'journey_recovery_environment_binding'
    environment_binding_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    environment: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    config_key: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    active_config_version_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    previous_config_version_id: Mapped[str | None] = mapped_column(String(64), index=True)
    release_manifest_id: Mapped[str | None] = mapped_column(String(64), index=True)
    binding_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    drift_status: Mapped[str] = mapped_column(String(24), nullable=False, default='UNKNOWN', index=True)
    promoted_by: Mapped[str | None] = mapped_column(String(64), index=True)
    promoted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    supplier_fact_unchanged: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    __table_args__ = (UniqueConstraint('environment','config_key', name='uq_recovery_environment_config_key'),)

class JourneyRecoveryReleaseManifestRow(Base):
    __tablename__ = 'journey_recovery_release_manifest'
    release_manifest_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_environment: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    target_environment: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    state: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    entries_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    manifest_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    dry_run_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    staging_evidence_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    rollback_target_manifest_id: Mapped[str | None] = mapped_column(String(64), index=True)
    requested_by: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    approved_by: Mapped[str | None] = mapped_column(String(64), index=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    promoted_by: Mapped[str | None] = mapped_column(String(64), index=True)
    promoted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rolled_back_by: Mapped[str | None] = mapped_column(String(64), index=True)
    rolled_back_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    promotion_result_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    supplier_fact_unchanged: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

class JourneyRecoveryConfigDriftAssessmentRow(Base):
    __tablename__ = 'journey_recovery_config_drift_assessment'
    drift_assessment_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    environment: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    observed_bindings_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    expected_bindings_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    drift_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    drift_detected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    action: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    created_by: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    supplier_fact_unchanged: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

class JourneyRecoveryReleaseEventRow(Base):
    __tablename__ = 'journey_recovery_release_event'
    release_event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    release_manifest_id: Mapped[str | None] = mapped_column(String(64), index=True)
    event_type: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    actor_id: Mapped[str | None] = mapped_column(String(64), index=True)
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    supplier_fact_unchanged: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

# Sprint 3S Recovery Runtime Deployment Attestation + Release Verification + Environment Health Gate
class JourneyRecoveryDeploymentAttestationRow(Base):
    __tablename__='journey_recovery_deployment_attestation'
    deployment_attestation_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    release_manifest_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    runtime_instance: Mapped[str]=mapped_column(String(128),nullable=False,index=True)
    expected_fingerprint: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    observed_fingerprint: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    state: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    attested_by: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    attested_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    payload_json: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryReleaseVerificationRow(Base):
    __tablename__='journey_recovery_release_verification'
    release_verification_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    release_manifest_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    attestation_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    smoke_test_json: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)
    health_slo_json: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)
    state: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    action: Mapped[str]=mapped_column(String(48),nullable=False,index=True)
    verified_by: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    verified_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryReleaseEvidenceSealRow(Base):
    __tablename__='journey_recovery_release_evidence_seal'
    release_evidence_seal_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    release_manifest_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    attestation_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    verification_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    evidence_hash: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    previous_hash: Mapped[str|None]=mapped_column(String(64))
    seal_hash: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    sealed_by: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    sealed_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

# Sprint 3T Recovery Production Runtime Observability + SLO Burn Rate + Automated Release Safety Controller
class JourneyRecoveryRuntimeObservationRow(Base):
    __tablename__='journey_recovery_runtime_observation'
    runtime_observation_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    release_manifest_id: Mapped[str|None]=mapped_column(String(64),index=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    runtime_instance: Mapped[str]=mapped_column(String(128),nullable=False,index=True)
    window_seconds: Mapped[int]=mapped_column(Integer,nullable=False)
    request_count: Mapped[int]=mapped_column(Integer,nullable=False,default=0)
    error_count: Mapped[int]=mapped_column(Integer,nullable=False,default=0)
    error_rate: Mapped[float]=mapped_column(Float,nullable=False,default=0.0)
    availability: Mapped[float]=mapped_column(Float,nullable=False,default=1.0)
    latency_p95_ms: Mapped[float]=mapped_column(Float,nullable=False,default=0.0)
    slo_target: Mapped[float]=mapped_column(Float,nullable=False,default=0.999)
    payload_json: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)
    observed_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryReleaseSafetyAssessmentRow(Base):
    __tablename__='journey_recovery_release_safety_assessment'
    safety_assessment_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    release_manifest_id: Mapped[str|None]=mapped_column(String(64),index=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    state: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    short_burn_rate: Mapped[float]=mapped_column(Float,nullable=False,default=0.0)
    long_burn_rate: Mapped[float]=mapped_column(Float,nullable=False,default=0.0)
    error_budget_remaining: Mapped[float]=mapped_column(Float,nullable=False,default=1.0)
    release_correlated_anomaly: Mapped[bool]=mapped_column(Boolean,nullable=False,default=False,index=True)
    anomaly_json: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)
    action: Mapped[str]=mapped_column(String(48),nullable=False,index=True)
    assessed_by: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    assessed_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryReleaseSafetyControlRow(Base):
    __tablename__='journey_recovery_release_safety_control'
    release_safety_control_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,unique=True,index=True)
    promotion_frozen: Mapped[bool]=mapped_column(Boolean,nullable=False,default=False,index=True)
    freeze_reason: Mapped[str|None]=mapped_column(String(256))
    source_assessment_id: Mapped[str|None]=mapped_column(String(64),index=True)
    updated_by: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryRollbackRecommendationRow(Base):
    __tablename__='journey_recovery_rollback_recommendation'
    rollback_recommendation_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    safety_assessment_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    release_manifest_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    rollback_target_manifest_id: Mapped[str|None]=mapped_column(String(64),index=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    state: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    reason_json: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    acknowledged_by: Mapped[str|None]=mapped_column(String(64),index=True)
    acknowledged_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

# Sprint 3U Runtime Telemetry Provenance + Multi-Window SLO Policy + Automated Incident Correlation
class JourneyRecoveryTelemetrySourceRow(Base):
    __tablename__='journey_recovery_telemetry_source'
    telemetry_source_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    source_key: Mapped[str]=mapped_column(String(128),nullable=False,unique=True,index=True)
    source_type: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    trust_level: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    endpoint_ref: Mapped[str|None]=mapped_column(String(256))
    config_json: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)
    source_fingerprint: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    created_by: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryTelemetryQualityAssessmentRow(Base):
    __tablename__='journey_recovery_telemetry_quality_assessment'
    telemetry_quality_assessment_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    runtime_observation_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    telemetry_source_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    freshness_seconds: Mapped[float]=mapped_column(Float,nullable=False,default=0.0)
    quality_score: Mapped[float]=mapped_column(Float,nullable=False,default=0.0)
    checks_json: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)
    assessed_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoverySloPolicyRow(Base):
    __tablename__='journey_recovery_slo_policy'
    slo_policy_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    policy_key: Mapped[str]=mapped_column(String(128),nullable=False,unique=True,index=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    slo_target: Mapped[float]=mapped_column(Float,nullable=False)
    windows_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    min_quality_score: Mapped[float]=mapped_column(Float,nullable=False,default=0.8)
    min_sources: Mapped[int]=mapped_column(Integer,nullable=False,default=1)
    created_by: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryRuntimeIncidentCorrelationRow(Base):
    __tablename__='journey_recovery_runtime_incident_correlation'
    runtime_incident_correlation_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    safety_assessment_id: Mapped[str|None]=mapped_column(String(64),index=True)
    release_manifest_id: Mapped[str|None]=mapped_column(String(64),index=True)
    deployment_attestation_id: Mapped[str|None]=mapped_column(String(64),index=True)
    release_verification_id: Mapped[str|None]=mapped_column(String(64),index=True)
    learning_incident_id: Mapped[str|None]=mapped_column(String(64),index=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    correlation_state: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    confidence: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    evidence_json: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)
    correlated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

# Sprint 3V Telemetry Trust Chain + Signed Runtime Identity + Incident Automation Policy
class JourneyRecoveryRuntimeIdentityRow(Base):
    __tablename__='journey_recovery_runtime_identity'
    runtime_identity_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    identity_key: Mapped[str]=mapped_column(String(128),nullable=False,unique=True,index=True)
    identity_type: Mapped[str]=mapped_column(String(24),nullable=False,index=True)  # WORKLOAD/COLLECTOR
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    subject_ref: Mapped[str]=mapped_column(String(256),nullable=False)
    verification_key_ref: Mapped[str]=mapped_column(String(128),nullable=False)
    identity_fingerprint: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    created_by: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoverySignedTelemetryEnvelopeRow(Base):
    __tablename__='journey_recovery_signed_telemetry_envelope'
    telemetry_envelope_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    telemetry_source_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    workload_identity_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    collector_identity_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    runtime_observation_id: Mapped[str|None]=mapped_column(String(64),index=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    nonce: Mapped[str]=mapped_column(String(128),nullable=False,unique=True,index=True)
    sequence_no: Mapped[int]=mapped_column(Integer,nullable=False,index=True)
    observed_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    received_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    payload_hash: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    signature: Mapped[str]=mapped_column(String(128),nullable=False)
    verification_state: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    verification_json: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryTelemetryTrustAssessmentRow(Base):
    __tablename__='journey_recovery_telemetry_trust_assessment'
    telemetry_trust_assessment_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    state: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    evidence_level: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    source_quorum: Mapped[int]=mapped_column(Integer,nullable=False)
    verified_source_count: Mapped[int]=mapped_column(Integer,nullable=False)
    evidence_json: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)
    assessed_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryIncidentAutomationPolicyRow(Base):
    __tablename__='journey_recovery_incident_automation_policy'
    incident_automation_policy_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    policy_key: Mapped[str]=mapped_column(String(128),nullable=False,unique=True,index=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    min_evidence_level_for_freeze: Mapped[str]=mapped_column(String(16),nullable=False)
    min_source_quorum: Mapped[int]=mapped_column(Integer,nullable=False,default=2)
    max_clock_skew_seconds: Mapped[int]=mapped_column(Integer,nullable=False,default=120)
    envelope_freshness_seconds: Mapped[int]=mapped_column(Integer,nullable=False,default=300)
    allow_auto_freeze: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)
    allow_auto_rollback_recommendation: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)
    policy_json: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)
    created_by: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

# Sprint 3W Runtime Identity Rotation + Trust Revocation + Telemetry Key Lifecycle
class JourneyRecoveryTelemetryKeyVersionRow(Base):
    __tablename__='journey_recovery_telemetry_key_version'
    telemetry_key_version_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    runtime_identity_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    version_no: Mapped[int]=mapped_column(Integer,nullable=False,index=True)
    key_ref: Mapped[str]=mapped_column(String(128),nullable=False,index=True)
    state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)  # ACTIVE/OVERLAP/RETIRED/REVOKED
    valid_from: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    valid_until: Mapped[datetime|None]=mapped_column(DateTime(timezone=True),index=True)
    previous_key_version_id: Mapped[str|None]=mapped_column(String(64),index=True)
    transition_payload_hash: Mapped[str|None]=mapped_column(String(64),index=True)
    transition_signature: Mapped[str|None]=mapped_column(String(128))
    evidence_json: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)
    created_by: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryIdentityRevocationRow(Base):
    __tablename__='journey_recovery_identity_revocation'
    identity_revocation_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    runtime_identity_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    reason_code: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    evidence_reference: Mapped[str]=mapped_column(String(256),nullable=False)
    effective_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    revoked_by: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    propagation_state: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    cache_epoch: Mapped[int]=mapped_column(Integer,nullable=False)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryTelemetrySecurityIncidentRow(Base):
    __tablename__='journey_recovery_telemetry_security_incident'
    telemetry_security_incident_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    runtime_identity_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    severity: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    reason_code: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    quarantine_state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    evidence_json: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)
    opened_by: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    opened_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    contained_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True),index=True)
    closed_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True),index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryTrustCacheInvalidationRow(Base):
    __tablename__='journey_recovery_trust_cache_invalidation'
    trust_cache_invalidation_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    runtime_identity_id: Mapped[str|None]=mapped_column(String(64),index=True)
    previous_epoch: Mapped[int]=mapped_column(Integer,nullable=False)
    new_epoch: Mapped[int]=mapped_column(Integer,nullable=False,index=True)
    reason_code: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    invalidated_by: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    invalidated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

# Sprint 3X Runtime Identity Re-Issuance + Hardware Trust Attestation + Credential Recovery Governance
class JourneyRecoveryIdentityReissuanceRequestRow(Base):
    __tablename__='journey_recovery_identity_reissuance_request'
    identity_reissuance_request_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    predecessor_identity_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    replacement_identity_id: Mapped[str|None]=mapped_column(String(64),index=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    identity_type: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    replacement_identity_key: Mapped[str]=mapped_column(String(128),nullable=False,unique=True,index=True)
    replacement_subject_ref: Mapped[str]=mapped_column(String(256),nullable=False)
    replacement_key_ref: Mapped[str]=mapped_column(String(128),nullable=False)
    state: Mapped[str]=mapped_column(String(32),nullable=False,index=True)  # REQUESTED/ATTESTED/APPROVED/ISSUED/REJECTED
    break_glass: Mapped[bool]=mapped_column(Boolean,nullable=False,default=False,index=True)
    reason_code: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    request_evidence_reference: Mapped[str]=mapped_column(String(256),nullable=False)
    attestation_key_ref: Mapped[str]=mapped_column(String(128),nullable=False)
    requested_by: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    approved_by: Mapped[str|None]=mapped_column(String(64),index=True)
    approval_evidence_reference: Mapped[str|None]=mapped_column(String(256))
    requested_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    approved_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True),index=True)
    issued_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True),index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryRuntimeAttestationEvidenceRow(Base):
    __tablename__='journey_recovery_runtime_attestation_evidence'
    runtime_attestation_evidence_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    identity_reissuance_request_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    predecessor_identity_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    attestation_type: Mapped[str]=mapped_column(String(32),nullable=False,index=True)  # TPM/TEE/CLOUD_WORKLOAD/ENGINEERING
    challenge_nonce: Mapped[str]=mapped_column(String(128),nullable=False,unique=True,index=True)
    workload_measurement: Mapped[str]=mapped_column(String(256),nullable=False,index=True)
    evidence_reference: Mapped[str]=mapped_column(String(256),nullable=False)
    evidence_hash: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    attestation_signature: Mapped[str]=mapped_column(String(128),nullable=False)
    verification_state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    verification_json: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)
    verified_by: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    verified_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryRuntimeIdentityLineageRow(Base):
    __tablename__='journey_recovery_runtime_identity_lineage'
    runtime_identity_lineage_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    predecessor_identity_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    replacement_identity_id: Mapped[str]=mapped_column(String(64),nullable=False,unique=True,index=True)
    identity_reissuance_request_id: Mapped[str]=mapped_column(String(64),nullable=False,unique=True,index=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    lineage_hash: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    created_by: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryRevokedIdentityTombstoneRow(Base):
    __tablename__='journey_recovery_revoked_identity_tombstone'
    revoked_identity_tombstone_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    runtime_identity_id: Mapped[str]=mapped_column(String(64),nullable=False,unique=True,index=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    identity_fingerprint: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    terminal_state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    reason_code: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    evidence_reference: Mapped[str]=mapped_column(String(256),nullable=False)
    tombstone_hash: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    replacement_identity_id: Mapped[str|None]=mapped_column(String(64),index=True)
    created_by: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

# Sprint 3Y Credential Issuance Authority + Attestation Policy Registry + Hardware Root-of-Trust Federation
class JourneyRecoveryHardwareTrustRootRow(Base):
    __tablename__='journey_recovery_hardware_trust_root'
    hardware_trust_root_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    root_key: Mapped[str]=mapped_column(String(128),nullable=False,unique=True,index=True)
    provider: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    trust_class: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    root_fingerprint: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    valid_from: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    valid_until: Mapped[datetime|None]=mapped_column(DateTime(timezone=True),index=True)
    metadata_json: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)
    created_by: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryCredentialIssuerRow(Base):
    __tablename__='journey_recovery_credential_issuer'
    credential_issuer_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    issuer_key: Mapped[str]=mapped_column(String(128),nullable=False,unique=True,index=True)
    issuer_type: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    hardware_trust_root_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    issuer_fingerprint: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    verification_key_ref: Mapped[str]=mapped_column(String(128),nullable=False)
    created_by: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryAttestationPolicyRow(Base):
    __tablename__='journey_recovery_attestation_policy'
    attestation_policy_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    policy_key: Mapped[str]=mapped_column(String(128),nullable=False,index=True)
    version_no: Mapped[int]=mapped_column(Integer,nullable=False,index=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    identity_type: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    min_trust_class: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    allowed_attestation_types_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    allowed_issuer_ids_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    min_verifier_quorum: Mapped[int]=mapped_column(Integer,nullable=False,default=2)
    policy_json: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)
    created_by: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    activated_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True),index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryCredentialIssuanceRow(Base):
    __tablename__='journey_recovery_credential_issuance'
    credential_issuance_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    runtime_identity_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    attestation_policy_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    credential_issuer_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    hardware_trust_root_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    runtime_attestation_evidence_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    state: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    credential_id: Mapped[str|None]=mapped_column(String(128),unique=True,index=True)
    credential_fingerprint: Mapped[str|None]=mapped_column(String(64),index=True)
    eligibility_state: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    predecessor_credential_id: Mapped[str|None]=mapped_column(String(128),index=True)
    requested_by: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    requested_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    issued_by: Mapped[str|None]=mapped_column(String(64),index=True)
    issued_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True),index=True)
    revoked_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True),index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryAttestationVerificationRow(Base):
    __tablename__='journey_recovery_attestation_verification'
    attestation_verification_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    credential_issuance_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    verifier_id: Mapped[str]=mapped_column(String(128),nullable=False,index=True)
    verdict: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    evidence_reference: Mapped[str]=mapped_column(String(256),nullable=False)
    verification_hash: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    verified_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryCredentialLineageRow(Base):
    __tablename__='journey_recovery_credential_lineage'
    credential_lineage_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    credential_issuance_id: Mapped[str]=mapped_column(String(64),nullable=False,unique=True,index=True)
    runtime_identity_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    predecessor_credential_id: Mapped[str|None]=mapped_column(String(128),index=True)
    credential_id: Mapped[str]=mapped_column(String(128),nullable=False,unique=True,index=True)
    lineage_hash: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    created_by: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryRevocationSyncRow(Base):
    __tablename__='journey_recovery_revocation_sync'
    revocation_sync_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    authority_type: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    authority_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    revocation_version: Mapped[int]=mapped_column(Integer,nullable=False,index=True)
    revoked_credential_ids_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    propagation_state: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    evidence_reference: Mapped[str]=mapped_column(String(256),nullable=False)
    synchronized_by: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    synchronized_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

# Sprint 3Z Certificate Transparency + Credential Status Distribution + Federated Trust Policy Enforcement
class JourneyRecoveryTrustFederationRow(Base):
    __tablename__='journey_recovery_trust_federation'
    trust_federation_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    federation_key: Mapped[str]=mapped_column(String(128),nullable=False,unique=True,index=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    cluster_scope: Mapped[str]=mapped_column(String(128),nullable=False,index=True)
    hardware_trust_root_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    peer_fingerprint: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    policy_version: Mapped[int]=mapped_column(Integer,nullable=False,default=1,index=True)
    last_synchronized_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True),index=True)
    created_by: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryCredentialStatusDistributionRow(Base):
    __tablename__='journey_recovery_credential_status_distribution'
    credential_status_distribution_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    credential_id: Mapped[str]=mapped_column(String(128),nullable=False,index=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    status: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    status_version: Mapped[int]=mapped_column(Integer,nullable=False,index=True)
    this_update_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    next_update_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    issuer_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    root_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    status_hash: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    publication_state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    evidence_reference: Mapped[str]=mapped_column(String(256),nullable=False)
    published_by: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    published_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryTrustTransparencyLogRow(Base):
    __tablename__='journey_recovery_trust_transparency_log'
    transparency_log_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    sequence_no: Mapped[int]=mapped_column(Integer,nullable=False,unique=True,index=True)
    event_type: Mapped[str]=mapped_column(String(48),nullable=False,index=True)
    subject_type: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    subject_id: Mapped[str]=mapped_column(String(128),nullable=False,index=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    payload_hash: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    previous_hash: Mapped[str|None]=mapped_column(String(64),index=True)
    entry_hash: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    evidence_reference: Mapped[str]=mapped_column(String(256),nullable=False)
    created_by: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryIssuerCompromiseRow(Base):
    __tablename__='journey_recovery_issuer_compromise'
    issuer_compromise_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    credential_issuer_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    severity: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    affected_credential_ids_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    fanout_count: Mapped[int]=mapped_column(Integer,nullable=False,default=0)
    evidence_reference: Mapped[str]=mapped_column(String(256),nullable=False)
    opened_by: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    opened_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    contained_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True),index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryFederatedAdmissionPolicyRow(Base):
    __tablename__='journey_recovery_federated_admission_policy'
    federated_admission_policy_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    policy_key: Mapped[str]=mapped_column(String(128),nullable=False,index=True)
    version_no: Mapped[int]=mapped_column(Integer,nullable=False,index=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    cluster_scope: Mapped[str]=mapped_column(String(128),nullable=False,index=True)
    state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    min_status_freshness_seconds: Mapped[int]=mapped_column(Integer,nullable=False,default=300)
    allowed_federation_ids_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    require_transparency_log: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)
    policy_json: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)
    created_by: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryFederatedAdmissionDecisionRow(Base):
    __tablename__='journey_recovery_federated_admission_decision'
    federated_admission_decision_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    runtime_identity_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    credential_id: Mapped[str]=mapped_column(String(128),nullable=False,index=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    cluster_id: Mapped[str]=mapped_column(String(128),nullable=False,index=True)
    policy_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    decision: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    reason_codes_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    status_distribution_id: Mapped[str|None]=mapped_column(String(64),index=True)
    transparency_log_id: Mapped[str|None]=mapped_column(String(64),index=True)
    decided_by: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    decided_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

# Sprint 4A External Trust Witness + Merkle Transparency Proof + Multi-Region Admission Consensus
class JourneyRecoveryMerkleCheckpointRow(Base):
    __tablename__='journey_recovery_merkle_checkpoint'
    merkle_checkpoint_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    tree_size: Mapped[int]=mapped_column(Integer,nullable=False,index=True)
    root_hash: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    first_sequence_no: Mapped[int]=mapped_column(Integer,nullable=False)
    last_sequence_no: Mapped[int]=mapped_column(Integer,nullable=False,index=True)
    checkpoint_hash: Mapped[str]=mapped_column(String(64),nullable=False,unique=True,index=True)
    state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    created_by: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryExternalTrustWitnessRow(Base):
    __tablename__='journey_recovery_external_trust_witness'
    external_trust_witness_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    witness_key: Mapped[str]=mapped_column(String(128),nullable=False,unique=True,index=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    verification_key_ref: Mapped[str]=mapped_column(String(256),nullable=False)
    witness_fingerprint: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    created_by: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryWitnessCosignatureRow(Base):
    __tablename__='journey_recovery_witness_cosignature'
    witness_cosignature_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    merkle_checkpoint_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    external_trust_witness_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    checkpoint_hash: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    signature: Mapped[str]=mapped_column(String(128),nullable=False)
    evidence_reference: Mapped[str]=mapped_column(String(256),nullable=False)
    verification_state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    signed_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryRegionTrustReplicaRow(Base):
    __tablename__='journey_recovery_region_trust_replica'
    region_trust_replica_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    region_key: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    credential_id: Mapped[str]=mapped_column(String(128),nullable=False,index=True)
    credential_status: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    status_version: Mapped[int]=mapped_column(Integer,nullable=False)
    checkpoint_hash: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    tree_size: Mapped[int]=mapped_column(Integer,nullable=False)
    replica_digest: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    observed_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    expires_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    evidence_reference: Mapped[str]=mapped_column(String(256),nullable=False)
    published_by: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryMultiRegionAdmissionPolicyRow(Base):
    __tablename__='journey_recovery_multi_region_admission_policy'
    multi_region_admission_policy_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    policy_key: Mapped[str]=mapped_column(String(128),nullable=False,index=True)
    version_no: Mapped[int]=mapped_column(Integer,nullable=False,index=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    required_regions_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    minimum_witness_cosignatures: Mapped[int]=mapped_column(Integer,nullable=False,default=1)
    max_replica_age_seconds: Mapped[int]=mapped_column(Integer,nullable=False,default=300)
    split_view_action: Mapped[str]=mapped_column(String(32),nullable=False,default='FAIL_SAFE_DENY')
    state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    created_by: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryMultiRegionAdmissionDecisionRow(Base):
    __tablename__='journey_recovery_multi_region_admission_decision'
    multi_region_admission_decision_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    runtime_identity_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    credential_id: Mapped[str]=mapped_column(String(128),nullable=False,index=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    cluster_id: Mapped[str]=mapped_column(String(128),nullable=False,index=True)
    policy_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    decision: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    consensus_state: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    split_view_detected: Mapped[bool]=mapped_column(Boolean,nullable=False,default=False,index=True)
    region_states_json: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)
    checkpoint_hash: Mapped[str|None]=mapped_column(String(64),index=True)
    witness_count: Mapped[int]=mapped_column(Integer,nullable=False,default=0)
    reason_codes_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    decided_by: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    decided_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryCheckpointGossipRow(Base):
    __tablename__='journey_recovery_checkpoint_gossip'
    checkpoint_gossip_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    observer_key: Mapped[str]=mapped_column(String(128),nullable=False,index=True)
    region_key: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    tree_size: Mapped[int]=mapped_column(Integer,nullable=False,index=True)
    root_hash: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    checkpoint_hash: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    evidence_reference: Mapped[str]=mapped_column(String(256),nullable=False)
    observed_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryWitnessFederationRow(Base):
    __tablename__='journey_recovery_witness_federation'
    witness_federation_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    federation_key: Mapped[str]=mapped_column(String(128),nullable=False,index=True)
    version_no: Mapped[int]=mapped_column(Integer,nullable=False,index=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    witness_ids_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    minimum_quorum: Mapped[int]=mapped_column(Integer,nullable=False)
    state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    created_by: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryConsistencyProofRow(Base):
    __tablename__='journey_recovery_consistency_proof'
    consistency_proof_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    old_checkpoint_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    new_checkpoint_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    old_tree_size: Mapped[int]=mapped_column(Integer,nullable=False)
    new_tree_size: Mapped[int]=mapped_column(Integer,nullable=False)
    old_root_hash: Mapped[str]=mapped_column(String(64),nullable=False)
    new_root_hash: Mapped[str]=mapped_column(String(64),nullable=False)
    old_leaf_hashes_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    appended_leaf_hashes_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    proof_hash: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    verification_state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    created_by: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoverySplitViewIncidentRow(Base):
    __tablename__='journey_recovery_split_view_incident'
    split_view_incident_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    tree_size: Mapped[int]=mapped_column(Integer,nullable=False,index=True)
    observer_states_json: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)
    conflicting_checkpoint_hashes_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    affected_regions_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    severity: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    evidence_reference: Mapped[str]=mapped_column(String(256),nullable=False)
    opened_by: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    opened_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    resolved_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True),index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryRegionIsolationRow(Base):
    __tablename__='journey_recovery_region_isolation'
    region_isolation_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    region_key: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    split_view_incident_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    reason_code: Mapped[str]=mapped_column(String(64),nullable=False)
    isolated_by: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    isolated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    rejoined_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True),index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryTrustRecoveryRow(Base):
    __tablename__='journey_recovery_trust_recovery'
    trust_recovery_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    split_view_incident_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    region_key: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    target_checkpoint_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    consistency_proof_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    witness_federation_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    witness_quorum_count: Mapped[int]=mapped_column(Integer,nullable=False)
    evidence_reference: Mapped[str]=mapped_column(String(256),nullable=False)
    state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    requested_by: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    requested_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    completed_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True),index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryWitnessOperatorRow(Base):
    __tablename__='journey_recovery_witness_operator'
    witness_operator_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    operator_key: Mapped[str]=mapped_column(String(128),nullable=False,unique=True,index=True)
    organization_ref: Mapped[str]=mapped_column(String(256),nullable=False)
    control_domain: Mapped[str]=mapped_column(String(128),nullable=False,index=True)
    cloud_provider: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    key_authority: Mapped[str]=mapped_column(String(128),nullable=False,index=True)
    state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    created_by: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryWitnessIndependenceBindingRow(Base):
    __tablename__='journey_recovery_witness_independence_binding'
    witness_independence_binding_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    external_trust_witness_id: Mapped[str]=mapped_column(String(64),nullable=False,unique=True,index=True)
    witness_operator_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    region_key: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    failure_domain: Mapped[str]=mapped_column(String(128),nullable=False,index=True)
    cloud_provider: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    key_authority: Mapped[str]=mapped_column(String(128),nullable=False,index=True)
    evidence_reference: Mapped[str]=mapped_column(String(256),nullable=False)
    bound_by: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    bound_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryWitnessIndependencePolicyRow(Base):
    __tablename__='journey_recovery_witness_independence_policy'
    witness_independence_policy_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    policy_key: Mapped[str]=mapped_column(String(128),nullable=False,index=True)
    version_no: Mapped[int]=mapped_column(Integer,nullable=False,index=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    minimum_operator_quorum: Mapped[int]=mapped_column(Integer,nullable=False)
    minimum_failure_domains: Mapped[int]=mapped_column(Integer,nullable=False)
    minimum_cloud_providers: Mapped[int]=mapped_column(Integer,nullable=False)
    minimum_key_authorities: Mapped[int]=mapped_column(Integer,nullable=False)
    max_witnesses_per_operator: Mapped[int]=mapped_column(Integer,nullable=False,default=1)
    state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    created_by: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryWitnessIndependenceAssessmentRow(Base):
    __tablename__='journey_recovery_witness_independence_assessment'
    witness_independence_assessment_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    witness_federation_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    witness_independence_policy_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    operator_count: Mapped[int]=mapped_column(Integer,nullable=False)
    failure_domain_count: Mapped[int]=mapped_column(Integer,nullable=False)
    cloud_provider_count: Mapped[int]=mapped_column(Integer,nullable=False)
    key_authority_count: Mapped[int]=mapped_column(Integer,nullable=False)
    effective_independent_quorum: Mapped[int]=mapped_column(Integer,nullable=False)
    state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    reason_codes_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    assessed_by: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    assessed_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryCrossOperatorGossipRow(Base):
    __tablename__='journey_recovery_cross_operator_gossip'
    cross_operator_gossip_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    witness_operator_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    region_key: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    merkle_checkpoint_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    tree_size: Mapped[int]=mapped_column(Integer,nullable=False,index=True)
    root_hash: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    checkpoint_hash: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    peer_digest: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    evidence_reference: Mapped[str]=mapped_column(String(256),nullable=False)
    observed_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryCheckpointArchiveRow(Base):
    __tablename__='journey_recovery_checkpoint_archive'
    checkpoint_archive_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    merkle_checkpoint_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    tree_size: Mapped[int]=mapped_column(Integer,nullable=False)
    root_hash: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    checkpoint_hash: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    leaf_hashes_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    archive_hash: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    storage_reference: Mapped[str]=mapped_column(String(512),nullable=False)
    state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    archived_by: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    archived_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryTrustPlaneDisasterIncidentRow(Base):
    __tablename__='journey_recovery_trust_plane_disaster_incident'
    trust_plane_disaster_incident_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    failure_scope: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    failure_domain_key: Mapped[str]=mapped_column(String(128),nullable=False,index=True)
    affected_regions_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    severity: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    drill_mode: Mapped[bool]=mapped_column(Boolean,nullable=False,default=False,index=True)
    evidence_reference: Mapped[str]=mapped_column(String(256),nullable=False)
    opened_by: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    opened_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    recovered_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True),index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryTrustPlaneRebuildRow(Base):
    __tablename__='journey_recovery_trust_plane_rebuild'
    trust_plane_rebuild_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    trust_plane_disaster_incident_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    checkpoint_archive_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    target_region_key: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    rebuilt_root_hash: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    rebuilt_checkpoint_hash: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    verification_state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    witness_independence_assessment_id: Mapped[str|None]=mapped_column(String(64),index=True)
    evidence_reference: Mapped[str]=mapped_column(String(256),nullable=False)
    started_by: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    started_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    completed_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True),index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryTrustPlaneRecoveryDrillRow(Base):
    __tablename__='journey_recovery_trust_plane_recovery_drill'
    trust_plane_recovery_drill_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    trust_plane_disaster_incident_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    trust_plane_rebuild_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    recovery_time_seconds: Mapped[int]=mapped_column(Integer,nullable=False)
    result: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    evidence_reference: Mapped[str]=mapped_column(String(256),nullable=False)
    recorded_by: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    recorded_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryChaosPolicyRow(Base):
    __tablename__='journey_recovery_chaos_policy'
    chaos_policy_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    policy_key: Mapped[str]=mapped_column(String(128),nullable=False,index=True)
    version_no: Mapped[int]=mapped_column(Integer,nullable=False,index=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    required_scenarios_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    minimum_readiness_score: Mapped[float]=mapped_column(Float,nullable=False,default=90.0)
    max_rto_seconds: Mapped[int]=mapped_column(Integer,nullable=False)
    max_rpo_seconds: Mapped[int]=mapped_column(Integer,nullable=False)
    evidence_ttl_seconds: Mapped[int]=mapped_column(Integer,nullable=False)
    state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    created_by: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryChaosCampaignRow(Base):
    __tablename__='journey_recovery_chaos_campaign'
    chaos_campaign_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    chaos_policy_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    campaign_key: Mapped[str]=mapped_column(String(128),nullable=False,index=True)
    scenarios_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    requested_by: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    requested_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    completed_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True),index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryChaosExecutionRow(Base):
    __tablename__='journey_recovery_chaos_execution'
    chaos_execution_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    chaos_campaign_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    scenario_type: Mapped[str]=mapped_column(String(48),nullable=False,index=True)
    fault_parameters_json: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)
    expected_safety_action: Mapped[str]=mapped_column(String(64),nullable=False)
    observed_safety_action: Mapped[str]=mapped_column(String(64),nullable=False)
    recovery_state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    rto_seconds: Mapped[int]=mapped_column(Integer,nullable=False)
    rpo_seconds: Mapped[int]=mapped_column(Integer,nullable=False)
    evidence_hash: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    evidence_reference: Mapped[str]=mapped_column(String(256),nullable=False)
    executed_by: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    started_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    completed_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryReadinessAssessmentRow(Base):
    __tablename__='journey_recovery_readiness_assessment'
    readiness_assessment_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    chaos_policy_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    chaos_campaign_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    scenario_coverage_json: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)
    readiness_score: Mapped[float]=mapped_column(Float,nullable=False)
    max_observed_rto_seconds: Mapped[int]=mapped_column(Integer,nullable=False)
    max_observed_rpo_seconds: Mapped[int]=mapped_column(Integer,nullable=False)
    evidence_fresh: Mapped[bool]=mapped_column(Boolean,nullable=False)
    state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    reason_codes_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    assessed_by: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    assessed_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryProductionReadinessGateRow(Base):
    __tablename__='journey_recovery_production_readiness_gate'
    production_readiness_gate_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    readiness_assessment_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    gate_state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    readiness_score: Mapped[float]=mapped_column(Float,nullable=False)
    reason_codes_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    evidence_reference: Mapped[str]=mapped_column(String(256),nullable=False)
    evaluated_by: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    evaluated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    valid_until: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryChaosScheduleRow(Base):
    __tablename__='journey_recovery_chaos_schedule'
    chaos_schedule_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    chaos_policy_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    schedule_key: Mapped[str]=mapped_column(String(128),nullable=False,index=True)
    cadence_seconds: Mapped[int]=mapped_column(Integer,nullable=False)
    scenarios_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    last_run_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True),index=True)
    next_run_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    created_by: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryReadinessTrendRow(Base):
    __tablename__='journey_recovery_readiness_trend'
    readiness_trend_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    chaos_policy_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    latest_assessment_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    previous_assessment_id: Mapped[str|None]=mapped_column(String(64),index=True)
    score_delta: Mapped[float]=mapped_column(Float,nullable=False)
    rto_delta_seconds: Mapped[int]=mapped_column(Integer,nullable=False)
    rpo_delta_seconds: Mapped[int]=mapped_column(Integer,nullable=False)
    evidence_age_seconds: Mapped[int]=mapped_column(Integer,nullable=False)
    trend_state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    reason_codes_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    evaluated_by: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    evaluated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryProductionReleaseWaiverRow(Base):
    __tablename__='journey_recovery_production_release_waiver'
    production_release_waiver_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    reason: Mapped[str]=mapped_column(String(512),nullable=False)
    risk_summary: Mapped[str]=mapped_column(String(1024),nullable=False)
    evidence_reference: Mapped[str]=mapped_column(String(256),nullable=False)
    risk_acceptor: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    requested_by: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    requested_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    starts_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    expires_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    approver_one: Mapped[str|None]=mapped_column(String(64),index=True)
    approver_one_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True),index=True)
    approver_two: Mapped[str|None]=mapped_column(String(64),index=True)
    approver_two_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True),index=True)
    state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryReleaseGateHistoryRow(Base):
    __tablename__='journey_recovery_release_gate_history'
    release_gate_history_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    release_manifest_id: Mapped[str|None]=mapped_column(String(64),index=True)
    gate_id: Mapped[str|None]=mapped_column(String(64),index=True)
    waiver_id: Mapped[str|None]=mapped_column(String(64),index=True)
    decision: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    decision_reason: Mapped[str]=mapped_column(String(128),nullable=False)
    evidence_json: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)
    actor: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    evaluated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryWaiverExposurePolicyRow(Base):
    __tablename__='journey_recovery_waiver_exposure_policy'
    waiver_exposure_policy_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    policy_key: Mapped[str]=mapped_column(String(128),nullable=False,index=True)
    version_no: Mapped[int]=mapped_column(Integer,nullable=False,index=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    rolling_window_hours: Mapped[int]=mapped_column(Integer,nullable=False)
    max_waiver_count: Mapped[int]=mapped_column(Integer,nullable=False)
    max_consecutive_waiver_releases: Mapped[int]=mapped_column(Integer,nullable=False)
    max_exposure_seconds: Mapped[int]=mapped_column(Integer,nullable=False)
    max_exception_debt_points: Mapped[float]=mapped_column(Float,nullable=False)
    remediation_sla_seconds: Mapped[int]=mapped_column(Integer,nullable=False)
    escalation_after_seconds: Mapped[int]=mapped_column(Integer,nullable=False)
    state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    created_by: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryExceptionDebtRow(Base):
    __tablename__='journey_recovery_exception_debt'
    exception_debt_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    waiver_exposure_policy_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    rolling_window_start: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    rolling_waiver_count: Mapped[int]=mapped_column(Integer,nullable=False)
    consecutive_waiver_releases: Mapped[int]=mapped_column(Integer,nullable=False)
    exposure_seconds: Mapped[int]=mapped_column(Integer,nullable=False)
    open_remediation_count: Mapped[int]=mapped_column(Integer,nullable=False)
    overdue_remediation_count: Mapped[int]=mapped_column(Integer,nullable=False)
    debt_points: Mapped[float]=mapped_column(Float,nullable=False)
    debt_state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    reason_codes_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    evaluated_by: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    evaluated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryWaiverRemediationRow(Base):
    __tablename__='journey_recovery_waiver_remediation'
    waiver_remediation_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    waiver_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    remediation_owner: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    remediation_summary: Mapped[str]=mapped_column(String(1024),nullable=False)
    opened_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    due_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    acknowledged_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True),index=True)
    resolved_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True),index=True)
    resolution_evidence_reference: Mapped[str|None]=mapped_column(String(256))
    escalation_level: Mapped[int]=mapped_column(Integer,nullable=False,default=0)
    last_escalated_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True),index=True)
    state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryWaiverExposureEventRow(Base):
    __tablename__='journey_recovery_waiver_exposure_event'
    waiver_exposure_event_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    waiver_id: Mapped[str|None]=mapped_column(String(64),index=True)
    remediation_id: Mapped[str|None]=mapped_column(String(64),index=True)
    event_type: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    evidence_json: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)
    actor: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryDebtBurnDownPolicyRow(Base):
    __tablename__='journey_recovery_debt_burn_down_policy'
    debt_burn_down_policy_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    policy_key: Mapped[str]=mapped_column(String(128),nullable=False,index=True)
    version_no: Mapped[int]=mapped_column(Integer,nullable=False,index=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    freeze_trigger_debt_points: Mapped[float]=mapped_column(Float,nullable=False)
    release_threshold_debt_points: Mapped[float]=mapped_column(Float,nullable=False)
    max_debt_age_seconds: Mapped[int]=mapped_column(Integer,nullable=False)
    plan_due_seconds: Mapped[int]=mapped_column(Integer,nullable=False)
    milestone_overdue_escalation_seconds: Mapped[int]=mapped_column(Integer,nullable=False)
    executive_acceptance_max_seconds: Mapped[int]=mapped_column(Integer,nullable=False)
    state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    created_by: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryDebtAgingAssessmentRow(Base):
    __tablename__='journey_recovery_debt_aging_assessment'
    debt_aging_assessment_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    exception_debt_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    debt_burn_down_policy_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    debt_points: Mapped[float]=mapped_column(Float,nullable=False)
    debt_state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    debt_age_seconds: Mapped[int]=mapped_column(Integer,nullable=False)
    aging_state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    reason_codes_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    assessed_by: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    assessed_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryDebtBurnDownPlanRow(Base):
    __tablename__='journey_recovery_debt_burn_down_plan'
    debt_burn_down_plan_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    source_exception_debt_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    plan_owner: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    executive_sponsor: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    objective: Mapped[str]=mapped_column(String(1024),nullable=False)
    starting_debt_points: Mapped[float]=mapped_column(Float,nullable=False)
    target_debt_points: Mapped[float]=mapped_column(Float,nullable=False)
    opened_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    due_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    progress_percent: Mapped[float]=mapped_column(Float,nullable=False,default=0)
    state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    closure_evidence_reference: Mapped[str|None]=mapped_column(String(256))
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryDebtBurnDownMilestoneRow(Base):
    __tablename__='journey_recovery_debt_burn_down_milestone'
    debt_burn_down_milestone_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    debt_burn_down_plan_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    sequence_no: Mapped[int]=mapped_column(Integer,nullable=False,index=True)
    title: Mapped[str]=mapped_column(String(256),nullable=False)
    owner_team: Mapped[str]=mapped_column(String(128),nullable=False,index=True)
    accountable_owner: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    target_debt_reduction_points: Mapped[float]=mapped_column(Float,nullable=False)
    due_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    completed_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True),index=True)
    evidence_reference: Mapped[str|None]=mapped_column(String(256))
    escalation_level: Mapped[int]=mapped_column(Integer,nullable=False,default=0)
    state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryDebtResponsibilityRow(Base):
    __tablename__='journey_recovery_debt_responsibility'
    debt_responsibility_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    debt_burn_down_plan_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    team_key: Mapped[str]=mapped_column(String(128),nullable=False,index=True)
    responsible_owner: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    accountable_executive: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    consulted_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    informed_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryWaiverFreezeRow(Base):
    __tablename__='journey_recovery_waiver_freeze'
    waiver_freeze_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    source_exception_debt_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    source_aging_assessment_id: Mapped[str|None]=mapped_column(String(64),index=True)
    reason_codes_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    activated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    released_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True),index=True)
    released_by: Mapped[str|None]=mapped_column(String(64),index=True)
    release_evidence_reference: Mapped[str|None]=mapped_column(String(256))
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryExecutiveRiskAcceptanceRow(Base):
    __tablename__='journey_recovery_executive_risk_acceptance'
    executive_risk_acceptance_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    debt_burn_down_plan_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    residual_risk_summary: Mapped[str]=mapped_column(String(2048),nullable=False)
    evidence_reference: Mapped[str]=mapped_column(String(256),nullable=False)
    requested_by: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    requested_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    executive_approver_one: Mapped[str|None]=mapped_column(String(64),index=True)
    executive_approver_two: Mapped[str|None]=mapped_column(String(64),index=True)
    starts_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    expires_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryDebtGovernanceEventRow(Base):
    __tablename__='journey_recovery_debt_governance_event'
    debt_governance_event_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    plan_id: Mapped[str|None]=mapped_column(String(64),index=True)
    freeze_id: Mapped[str|None]=mapped_column(String(64),index=True)
    executive_acceptance_id: Mapped[str|None]=mapped_column(String(64),index=True)
    event_type: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    evidence_json: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)
    actor: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryEnterpriseRiskLimitRow(Base):
    __tablename__='journey_recovery_enterprise_risk_limit'
    enterprise_risk_limit_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    limit_key: Mapped[str]=mapped_column(String(128),nullable=False,index=True)
    version_no: Mapped[int]=mapped_column(Integer,nullable=False)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    max_aggregate_exposure_points: Mapped[float]=mapped_column(Float,nullable=False)
    max_team_concentration_pct: Mapped[float]=mapped_column(Float,nullable=False)
    max_risk_domain_concentration_pct: Mapped[float]=mapped_column(Float,nullable=False)
    max_correlated_exposure_points: Mapped[float]=mapped_column(Float,nullable=False)
    max_active_acceptances: Mapped[int]=mapped_column(Integer,nullable=False)
    requested_by: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    board_approver_one: Mapped[str|None]=mapped_column(String(64),index=True)
    board_approver_two: Mapped[str|None]=mapped_column(String(64),index=True)
    state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryExecutiveRiskPositionRow(Base):
    __tablename__='journey_recovery_executive_risk_position'
    risk_position_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    executive_risk_acceptance_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    team_key: Mapped[str]=mapped_column(String(128),nullable=False,index=True)
    risk_domain: Mapped[str]=mapped_column(String(128),nullable=False,index=True)
    exposure_points: Mapped[float]=mapped_column(Float,nullable=False)
    correlation_keys_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    registered_by: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    registered_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryExecutiveRiskPortfolioAssessmentRow(Base):
    __tablename__='journey_recovery_executive_risk_portfolio_assessment'
    portfolio_assessment_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    enterprise_risk_limit_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    active_acceptance_count: Mapped[int]=mapped_column(Integer,nullable=False)
    aggregate_exposure_points: Mapped[float]=mapped_column(Float,nullable=False)
    max_team_concentration_pct: Mapped[float]=mapped_column(Float,nullable=False)
    max_risk_domain_concentration_pct: Mapped[float]=mapped_column(Float,nullable=False)
    max_correlated_exposure_points: Mapped[float]=mapped_column(Float,nullable=False)
    portfolio_state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    reason_codes_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    metrics_json: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)
    assessed_by: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    assessed_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryResidualRiskConcentrationRow(Base):
    __tablename__='journey_recovery_residual_risk_concentration'
    concentration_assessment_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    portfolio_assessment_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    dimension: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    dimension_key: Mapped[str]=mapped_column(String(128),nullable=False,index=True)
    exposure_points: Mapped[float]=mapped_column(Float,nullable=False)
    concentration_pct: Mapped[float]=mapped_column(Float,nullable=False)
    breached: Mapped[bool]=mapped_column(Boolean,nullable=False,default=False)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryPortfolioFreezeRow(Base):
    __tablename__='journey_recovery_portfolio_freeze'
    portfolio_freeze_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    source_portfolio_assessment_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    reason_codes_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    activated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    released_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True),index=True)
    released_by: Mapped[str|None]=mapped_column(String(64),index=True)
    release_evidence_reference: Mapped[str|None]=mapped_column(String(256))
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryEnterpriseRiskEventRow(Base):
    __tablename__='journey_recovery_enterprise_risk_event'
    enterprise_risk_event_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    event_type: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    risk_position_id: Mapped[str|None]=mapped_column(String(64),index=True)
    portfolio_assessment_id: Mapped[str|None]=mapped_column(String(64),index=True)
    portfolio_freeze_id: Mapped[str|None]=mapped_column(String(64),index=True)
    evidence_json: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)
    actor: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryRiskAppetiteEnvelopeRow(Base):
    __tablename__='journey_recovery_risk_appetite_envelope'
    risk_appetite_envelope_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    appetite_key: Mapped[str]=mapped_column(String(128),nullable=False,index=True)
    version_no: Mapped[int]=mapped_column(Integer,nullable=False)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    max_current_exposure_points: Mapped[float]=mapped_column(Float,nullable=False)
    max_stressed_exposure_points: Mapped[float]=mapped_column(Float,nullable=False)
    min_headroom_points: Mapped[float]=mapped_column(Float,nullable=False)
    min_capacity_buffer_pct: Mapped[float]=mapped_column(Float,nullable=False)
    max_sensitivity_pct: Mapped[float]=mapped_column(Float,nullable=False)
    requested_by: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    board_approver_one: Mapped[str|None]=mapped_column(String(64),index=True)
    board_approver_two: Mapped[str|None]=mapped_column(String(64),index=True)
    state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryRiskStressScenarioRow(Base):
    __tablename__='journey_recovery_risk_stress_scenario'
    stress_scenario_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    scenario_key: Mapped[str]=mapped_column(String(128),nullable=False,index=True)
    scenario_type: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    shock_multiplier: Mapped[float]=mapped_column(Float,nullable=False)
    correlation_amplifier: Mapped[float]=mapped_column(Float,nullable=False)
    affected_correlation_keys_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    affected_risk_domains_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    created_by: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryRiskStressAssessmentRow(Base):
    __tablename__='journey_recovery_risk_stress_assessment'
    stress_assessment_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    risk_appetite_envelope_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    portfolio_assessment_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    scenario_ids_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    current_exposure_points: Mapped[float]=mapped_column(Float,nullable=False)
    stressed_exposure_points: Mapped[float]=mapped_column(Float,nullable=False)
    headroom_points: Mapped[float]=mapped_column(Float,nullable=False)
    capacity_buffer_pct: Mapped[float]=mapped_column(Float,nullable=False)
    sensitivity_pct: Mapped[float]=mapped_column(Float,nullable=False)
    assessment_state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    reason_codes_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    metrics_json: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)
    assessed_by: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    assessed_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryRiskCapacityBufferRow(Base):
    __tablename__='journey_recovery_risk_capacity_buffer'
    capacity_buffer_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    stress_assessment_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    dimension: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    dimension_key: Mapped[str]=mapped_column(String(128),nullable=False,index=True)
    baseline_exposure_points: Mapped[float]=mapped_column(Float,nullable=False)
    stressed_exposure_points: Mapped[float]=mapped_column(Float,nullable=False)
    sensitivity_pct: Mapped[float]=mapped_column(Float,nullable=False)
    headroom_points: Mapped[float]=mapped_column(Float,nullable=False)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryStressPreemptiveFreezeRow(Base):
    __tablename__='journey_recovery_stress_preemptive_freeze'
    stress_freeze_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    source_stress_assessment_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    reason_codes_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    activated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    released_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True),index=True)
    released_by: Mapped[str|None]=mapped_column(String(64),index=True)
    release_evidence_reference: Mapped[str|None]=mapped_column(String(256))
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryRiskAppetiteEventRow(Base):
    __tablename__='journey_recovery_risk_appetite_event'
    risk_appetite_event_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    event_type: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    stress_assessment_id: Mapped[str|None]=mapped_column(String(64),index=True)
    stress_freeze_id: Mapped[str|None]=mapped_column(String(64),index=True)
    evidence_json: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)
    actor: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

# Sprint 4J - Enterprise Risk Forecast + EWI + Dynamic Capacity Allocation
class JourneyRecoveryRiskForecastPolicyRow(Base):
    __tablename__='journey_recovery_risk_forecast_policy'
    risk_forecast_policy_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    policy_key: Mapped[str]=mapped_column(String(128),nullable=False,index=True)
    version_no: Mapped[int]=mapped_column(Integer,nullable=False)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    warning_capacity_utilization_pct: Mapped[float]=mapped_column(Float,nullable=False)
    restrict_capacity_utilization_pct: Mapped[float]=mapped_column(Float,nullable=False)
    reserve_capacity_pct: Mapped[float]=mapped_column(Float,nullable=False)
    requested_by: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    board_approver_one: Mapped[str|None]=mapped_column(String(64),index=True)
    board_approver_two: Mapped[str|None]=mapped_column(String(64),index=True)
    state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryRiskIndicatorRow(Base):
    __tablename__='journey_recovery_risk_indicator'
    risk_indicator_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    indicator_key: Mapped[str]=mapped_column(String(128),nullable=False,index=True)
    indicator_type: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    dimension: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    dimension_key: Mapped[str|None]=mapped_column(String(128),index=True)
    observed_value: Mapped[float]=mapped_column(Float,nullable=False)
    threshold_value: Mapped[float]=mapped_column(Float,nullable=False)
    direction: Mapped[str]=mapped_column(String(16),nullable=False)
    weight: Mapped[float]=mapped_column(Float,nullable=False)
    signal_state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    evidence_json: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)
    observed_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryRiskForecastRow(Base):
    __tablename__='journey_recovery_risk_forecast'
    risk_forecast_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    risk_forecast_policy_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    horizon_hours: Mapped[int]=mapped_column(Integer,nullable=False,index=True)
    current_exposure_points: Mapped[float]=mapped_column(Float,nullable=False)
    projected_exposure_points: Mapped[float]=mapped_column(Float,nullable=False)
    projected_capacity_consumption_pct: Mapped[float]=mapped_column(Float,nullable=False)
    projected_headroom_points: Mapped[float]=mapped_column(Float,nullable=False)
    weighted_risk_signal: Mapped[float]=mapped_column(Float,nullable=False)
    forecast_state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    reason_codes_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    inputs_json: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)
    forecasted_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    valid_until: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryDynamicRiskCapacityRow(Base):
    __tablename__='journey_recovery_dynamic_risk_capacity'
    risk_capacity_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    risk_forecast_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    dimension: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    dimension_key: Mapped[str]=mapped_column(String(128),nullable=False,index=True)
    allocated_capacity_points: Mapped[float]=mapped_column(Float,nullable=False)
    current_exposure_points: Mapped[float]=mapped_column(Float,nullable=False)
    projected_exposure_points: Mapped[float]=mapped_column(Float,nullable=False)
    capacity_utilization_pct: Mapped[float]=mapped_column(Float,nullable=False)
    available_capacity_points: Mapped[float]=mapped_column(Float,nullable=False)
    allocation_state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryRiskEarlyWarningRow(Base):
    __tablename__='journey_recovery_risk_early_warning'
    early_warning_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    risk_forecast_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    warning_type: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    severity: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    reason_codes_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    acknowledged_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True),index=True)
    acknowledged_by: Mapped[str|None]=mapped_column(String(64),index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryForecastRiskRestrictionRow(Base):
    __tablename__='journey_recovery_forecast_risk_restriction'
    forecast_restriction_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    source_risk_forecast_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    restriction_scope: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    reason_codes_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    activated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    released_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True),index=True)
    released_by: Mapped[str|None]=mapped_column(String(64),index=True)
    release_evidence_reference: Mapped[str|None]=mapped_column(String(256))
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryRiskForecastEventRow(Base):
    __tablename__='journey_recovery_risk_forecast_event'
    risk_forecast_event_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    event_type: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    risk_forecast_id: Mapped[str|None]=mapped_column(String(64),index=True)
    forecast_restriction_id: Mapped[str|None]=mapped_column(String(64),index=True)
    evidence_json: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)
    actor: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

# Sprint 4K - Risk Forecast Calibration + Accuracy + Capacity Allocation Governance
class JourneyRecoveryRiskForecastModelVersionRow(Base):
    __tablename__='journey_recovery_risk_forecast_model_version'
    risk_forecast_model_version_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    model_key: Mapped[str]=mapped_column(String(128),nullable=False,index=True)
    version_no: Mapped[int]=mapped_column(Integer,nullable=False)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    algorithm_key: Mapped[str]=mapped_column(String(64),nullable=False)
    parameters_json: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)
    conservative_parameters_json: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)
    minimum_samples: Mapped[int]=mapped_column(Integer,nullable=False,default=5)
    max_mae_points: Mapped[float]=mapped_column(Float,nullable=False)
    max_brier_score: Mapped[float]=mapped_column(Float,nullable=False)
    max_false_positive_rate: Mapped[float]=mapped_column(Float,nullable=False)
    max_false_negative_rate: Mapped[float]=mapped_column(Float,nullable=False)
    max_capacity_drift_pct: Mapped[float]=mapped_column(Float,nullable=False)
    requested_by: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    board_approver_one: Mapped[str|None]=mapped_column(String(64),index=True)
    board_approver_two: Mapped[str|None]=mapped_column(String(64),index=True)
    state: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryRiskForecastOutcomeRow(Base):
    __tablename__='journey_recovery_risk_forecast_outcome'
    risk_forecast_outcome_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    risk_forecast_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    risk_forecast_model_version_id: Mapped[str|None]=mapped_column(String(64),index=True)
    horizon_hours: Mapped[int]=mapped_column(Integer,nullable=False,index=True)
    predicted_exposure_points: Mapped[float]=mapped_column(Float,nullable=False)
    predicted_breach_probability: Mapped[float]=mapped_column(Float,nullable=False)
    actual_exposure_points: Mapped[float]=mapped_column(Float,nullable=False)
    actual_breach: Mapped[bool]=mapped_column(Boolean,nullable=False)
    absolute_error_points: Mapped[float]=mapped_column(Float,nullable=False)
    squared_probability_error: Mapped[float]=mapped_column(Float,nullable=False)
    observed_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    evidence_json: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryRiskForecastAccuracyAssessmentRow(Base):
    __tablename__='journey_recovery_risk_forecast_accuracy_assessment'
    risk_forecast_accuracy_assessment_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    risk_forecast_model_version_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    horizon_hours: Mapped[int]=mapped_column(Integer,nullable=False,index=True)
    sample_count: Mapped[int]=mapped_column(Integer,nullable=False)
    mae_points: Mapped[float]=mapped_column(Float,nullable=False)
    brier_score: Mapped[float]=mapped_column(Float,nullable=False)
    false_positive_rate: Mapped[float]=mapped_column(Float,nullable=False)
    false_negative_rate: Mapped[float]=mapped_column(Float,nullable=False)
    mean_capacity_drift_pct: Mapped[float]=mapped_column(Float,nullable=False)
    calibration_error_pct: Mapped[float]=mapped_column(Float,nullable=False)
    accuracy_state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    reason_codes_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    evaluated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryRiskForecastCalibrationRow(Base):
    __tablename__='journey_recovery_risk_forecast_calibration'
    risk_forecast_calibration_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    risk_forecast_model_version_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    horizon_hours: Mapped[int]=mapped_column(Integer,nullable=False,index=True)
    sample_count: Mapped[int]=mapped_column(Integer,nullable=False)
    predicted_breach_rate: Mapped[float]=mapped_column(Float,nullable=False)
    actual_breach_rate: Mapped[float]=mapped_column(Float,nullable=False)
    calibration_error_pct: Mapped[float]=mapped_column(Float,nullable=False)
    calibration_state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    valid_until: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryRiskCapacityAllocationDriftRow(Base):
    __tablename__='journey_recovery_risk_capacity_allocation_drift'
    risk_capacity_allocation_drift_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    risk_forecast_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    dimension: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    dimension_key: Mapped[str]=mapped_column(String(128),nullable=False,index=True)
    allocated_capacity_points: Mapped[float]=mapped_column(Float,nullable=False)
    projected_exposure_points: Mapped[float]=mapped_column(Float,nullable=False)
    actual_exposure_points: Mapped[float]=mapped_column(Float,nullable=False)
    allocation_drift_pct: Mapped[float]=mapped_column(Float,nullable=False)
    drift_state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    observed_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryRiskForecastSafetyControlRow(Base):
    __tablename__='journey_recovery_risk_forecast_safety_control'
    risk_forecast_safety_control_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    risk_forecast_model_version_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    control_mode: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    source_accuracy_assessment_id: Mapped[str|None]=mapped_column(String(64),index=True)
    reason_codes_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    activated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    released_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True),index=True)
    release_evidence_reference: Mapped[str|None]=mapped_column(String(256))
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryRiskForecastCalibrationEventRow(Base):
    __tablename__='journey_recovery_risk_forecast_calibration_event'
    risk_forecast_calibration_event_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    event_type: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    model_version_id: Mapped[str|None]=mapped_column(String(64),index=True)
    accuracy_assessment_id: Mapped[str|None]=mapped_column(String(64),index=True)
    evidence_json: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)
    actor: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

# Sprint 4L - Forecast Champion/Challenger + Backtesting + Model Promotion Governance
class JourneyRecoveryForecastModelRoleRow(Base):
    __tablename__='journey_recovery_forecast_model_role'
    forecast_model_role_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    model_version_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    role: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    assigned_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryForecastBacktestRunRow(Base):
    __tablename__='journey_recovery_forecast_backtest_run'
    forecast_backtest_run_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    champion_model_version_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    challenger_model_version_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    window_key: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    horizons_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    segments_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryForecastBacktestMetricRow(Base):
    __tablename__='journey_recovery_forecast_backtest_metric'
    forecast_backtest_metric_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    forecast_backtest_run_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    model_version_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    horizon_hours: Mapped[int]=mapped_column(Integer,nullable=False,index=True)
    segment_key: Mapped[str]=mapped_column(String(128),nullable=False,index=True)
    sample_count: Mapped[int]=mapped_column(Integer,nullable=False)
    mae_points: Mapped[float]=mapped_column(Float,nullable=False)
    brier_score: Mapped[float]=mapped_column(Float,nullable=False)
    false_positive_rate: Mapped[float]=mapped_column(Float,nullable=False)
    false_negative_rate: Mapped[float]=mapped_column(Float,nullable=False)
    capacity_drift_pct: Mapped[float]=mapped_column(Float,nullable=False)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryForecastShadowEvaluationRow(Base):
    __tablename__='journey_recovery_forecast_shadow_evaluation'
    forecast_shadow_evaluation_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    challenger_model_version_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    horizon_hours: Mapped[int]=mapped_column(Integer,nullable=False,index=True)
    segment_key: Mapped[str]=mapped_column(String(128),nullable=False,index=True)
    sample_count: Mapped[int]=mapped_column(Integer,nullable=False)
    improvement_pct: Mapped[float]=mapped_column(Float,nullable=False)
    safety_delta_pct: Mapped[float]=mapped_column(Float,nullable=False)
    evaluation_state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryForecastPromotionDecisionRow(Base):
    __tablename__='journey_recovery_forecast_promotion_decision'
    forecast_promotion_decision_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    champion_model_version_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    challenger_model_version_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    decision: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    reason_codes_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    evidence_json: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)
    decided_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

# Sprint 4M - Statistical Significance + Promotion Stability + Automated Rollback Governance
class JourneyRecoveryForecastPromotionPolicyRow(Base):
    __tablename__='journey_recovery_forecast_promotion_policy'
    forecast_promotion_policy_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    version_no: Mapped[int]=mapped_column(Integer,nullable=False)
    minimum_sample_count: Mapped[int]=mapped_column(Integer,nullable=False)
    significance_alpha: Mapped[float]=mapped_column(Float,nullable=False)
    minimum_effect_size_pct: Mapped[float]=mapped_column(Float,nullable=False)
    stability_evaluations_required: Mapped[int]=mapped_column(Integer,nullable=False)
    required_segments_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    probation_seconds: Mapped[int]=mapped_column(Integer,nullable=False)
    max_mae_regression_pct: Mapped[float]=mapped_column(Float,nullable=False)
    max_brier_regression_pct: Mapped[float]=mapped_column(Float,nullable=False)
    max_safety_regression_pct: Mapped[float]=mapped_column(Float,nullable=False)
    requested_by: Mapped[str]=mapped_column(String(64),nullable=False)
    approver_one: Mapped[str|None]=mapped_column(String(64),index=True)
    approver_two: Mapped[str|None]=mapped_column(String(64),index=True)
    state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryForecastStatisticalAssessmentRow(Base):
    __tablename__='journey_recovery_forecast_statistical_assessment'
    forecast_statistical_assessment_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    policy_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    champion_model_version_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    challenger_model_version_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    horizon_hours: Mapped[int]=mapped_column(Integer,nullable=False,index=True)
    segment_key: Mapped[str]=mapped_column(String(128),nullable=False,index=True)
    sample_count: Mapped[int]=mapped_column(Integer,nullable=False)
    effect_size_pct: Mapped[float]=mapped_column(Float,nullable=False)
    z_score: Mapped[float]=mapped_column(Float,nullable=False)
    p_value: Mapped[float]=mapped_column(Float,nullable=False)
    significance_state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    reason_codes_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    evaluated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryForecastPromotionProbationRow(Base):
    __tablename__='journey_recovery_forecast_promotion_probation'
    forecast_promotion_probation_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    policy_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    promotion_decision_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    previous_champion_model_version_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    promoted_model_version_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    started_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    probation_until: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    latest_evaluation_json: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)
    rollback_reason_codes_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    completed_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True),index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryForecastModelRollbackEventRow(Base):
    __tablename__='journey_recovery_forecast_model_rollback_event'
    forecast_model_rollback_event_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    probation_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    from_model_version_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    to_model_version_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    reason_codes_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    evidence_json: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)
    rolled_back_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

# Sprint 4N - Model Drift Detection + Population Stability + Challenger Auto-Generation Governance
class JourneyRecoveryForecastDriftPolicyRow(Base):
    __tablename__='journey_recovery_forecast_drift_policy'
    forecast_drift_policy_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    version_no: Mapped[int]=mapped_column(Integer,nullable=False)
    minimum_sample_count: Mapped[int]=mapped_column(Integer,nullable=False)
    max_population_psi: Mapped[float]=mapped_column(Float,nullable=False)
    max_segment_psi: Mapped[float]=mapped_column(Float,nullable=False)
    max_residual_drift_pct: Mapped[float]=mapped_column(Float,nullable=False)
    consecutive_breaches_required: Mapped[int]=mapped_column(Integer,nullable=False)
    baseline_window_key: Mapped[str]=mapped_column(String(64),nullable=False)
    comparison_window_key: Mapped[str]=mapped_column(String(64),nullable=False)
    requested_by: Mapped[str]=mapped_column(String(64),nullable=False)
    approver_one: Mapped[str|None]=mapped_column(String(64),index=True)
    approver_two: Mapped[str|None]=mapped_column(String(64),index=True)
    state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryForecastDriftAssessmentRow(Base):
    __tablename__='journey_recovery_forecast_drift_assessment'
    forecast_drift_assessment_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    policy_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    champion_model_version_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    horizon_hours: Mapped[int]=mapped_column(Integer,nullable=False,index=True)
    sample_count: Mapped[int]=mapped_column(Integer,nullable=False)
    population_psi: Mapped[float]=mapped_column(Float,nullable=False)
    max_segment_psi: Mapped[float]=mapped_column(Float,nullable=False)
    residual_drift_pct: Mapped[float]=mapped_column(Float,nullable=False)
    drift_state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    segment_metrics_json: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)
    reason_codes_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    evaluated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryForecastRetrainingRequestRow(Base):
    __tablename__='journey_recovery_forecast_retraining_request'
    forecast_retraining_request_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    source_drift_assessment_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    champion_model_version_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    requested_model_key: Mapped[str]=mapped_column(String(128),nullable=False)
    refresh_reason_codes_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    requested_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    requested_by: Mapped[str]=mapped_column(String(64),nullable=False)
    evidence_json: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryForecastRefreshPipelineRow(Base):
    __tablename__='journey_recovery_forecast_refresh_pipeline'
    forecast_refresh_pipeline_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    retraining_request_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    source_champion_model_version_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    challenger_model_version_id: Mapped[str|None]=mapped_column(String(64),index=True)
    pipeline_state: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    governance_next_step: Mapped[str]=mapped_column(String(64),nullable=False)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryForecastDriftEventRow(Base):
    __tablename__='journey_recovery_forecast_drift_event'
    forecast_drift_event_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    event_type: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    drift_assessment_id: Mapped[str|None]=mapped_column(String(64),index=True)
    retraining_request_id: Mapped[str|None]=mapped_column(String(64),index=True)
    challenger_model_version_id: Mapped[str|None]=mapped_column(String(64),index=True)
    evidence_json: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)
    actor: Mapped[str]=mapped_column(String(64),nullable=False)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

# Sprint 4O - Model Training Data Lineage + Feature Registry + Reproducible Model Build Governance
class JourneyRecoveryForecastTrainingPolicyRow(Base):
    __tablename__='journey_recovery_forecast_training_policy'
    forecast_training_policy_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    version_no: Mapped[int]=mapped_column(Integer,nullable=False)
    minimum_training_rows: Mapped[int]=mapped_column(Integer,nullable=False)
    max_missing_rate: Mapped[float]=mapped_column(Float,nullable=False)
    max_duplicate_rate: Mapped[float]=mapped_column(Float,nullable=False)
    max_invalid_rate: Mapped[float]=mapped_column(Float,nullable=False)
    reproducibility_required: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)
    requested_by: Mapped[str]=mapped_column(String(64),nullable=False)
    approver_one: Mapped[str|None]=mapped_column(String(64))
    approver_two: Mapped[str|None]=mapped_column(String(64))
    state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryForecastFeatureVersionRow(Base):
    __tablename__='journey_recovery_forecast_feature_version'
    forecast_feature_version_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    feature_key: Mapped[str]=mapped_column(String(128),nullable=False,index=True)
    version_no: Mapped[int]=mapped_column(Integer,nullable=False)
    data_type: Mapped[str]=mapped_column(String(32),nullable=False)
    definition_json: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)
    transform_hash: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    created_by: Mapped[str]=mapped_column(String(64),nullable=False)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryForecastTrainingDatasetSnapshotRow(Base):
    __tablename__='journey_recovery_forecast_training_dataset_snapshot'
    training_dataset_snapshot_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    dataset_key: Mapped[str]=mapped_column(String(128),nullable=False,index=True)
    snapshot_version: Mapped[int]=mapped_column(Integer,nullable=False)
    row_count: Mapped[int]=mapped_column(Integer,nullable=False)
    schema_hash: Mapped[str]=mapped_column(String(64),nullable=False)
    content_hash: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    source_refs_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    feature_version_ids_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryForecastTrainingDataQualityRow(Base):
    __tablename__='journey_recovery_forecast_training_data_quality'
    training_data_quality_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    training_dataset_snapshot_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    policy_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    row_count: Mapped[int]=mapped_column(Integer,nullable=False)
    missing_rate: Mapped[float]=mapped_column(Float,nullable=False)
    duplicate_rate: Mapped[float]=mapped_column(Float,nullable=False)
    invalid_rate: Mapped[float]=mapped_column(Float,nullable=False)
    quality_state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    reason_codes_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    evidence_json: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)
    assessed_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryForecastTrainingLineageRow(Base):
    __tablename__='journey_recovery_forecast_training_lineage'
    forecast_training_lineage_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    challenger_model_version_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    training_dataset_snapshot_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    feature_version_ids_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    source_retraining_request_id: Mapped[str|None]=mapped_column(String(64),index=True)
    lineage_hash: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    lineage_state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryForecastTrainingManifestRow(Base):
    __tablename__='journey_recovery_forecast_training_manifest'
    forecast_training_manifest_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    challenger_model_version_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    training_lineage_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    code_ref: Mapped[str]=mapped_column(String(256),nullable=False)
    code_hash: Mapped[str]=mapped_column(String(64),nullable=False)
    algorithm_key: Mapped[str]=mapped_column(String(128),nullable=False)
    hyperparameters_json: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)
    random_seed: Mapped[int]=mapped_column(Integer,nullable=False)
    build_hash: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    manifest_state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryForecastReproducibilityCheckRow(Base):
    __tablename__='journey_recovery_forecast_reproducibility_check'
    forecast_reproducibility_check_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    challenger_model_version_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    training_manifest_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    expected_build_hash: Mapped[str]=mapped_column(String(64),nullable=False)
    reproduced_build_hash: Mapped[str]=mapped_column(String(64),nullable=False)
    reproducibility_state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    evidence_reference: Mapped[str]=mapped_column(String(256),nullable=False)
    checked_by: Mapped[str]=mapped_column(String(64),nullable=False)
    checked_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryForecastModelBuildEligibilityRow(Base):
    __tablename__='journey_recovery_forecast_model_build_eligibility'
    forecast_model_build_eligibility_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    challenger_model_version_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    training_manifest_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    data_quality_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    reproducibility_check_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    eligibility_state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    reason_codes_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    evaluated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryForecastTrainingGovernanceEventRow(Base):
    __tablename__='journey_recovery_forecast_training_governance_event'
    forecast_training_governance_event_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    event_type: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    challenger_model_version_id: Mapped[str|None]=mapped_column(String(64),index=True)
    evidence_json: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)
    actor: Mapped[str]=mapped_column(String(64),nullable=False)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryForecastArtifactPolicyRow(Base):
    __tablename__='journey_recovery_forecast_artifact_policy'
    forecast_artifact_policy_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    version_no: Mapped[int]=mapped_column(Integer,nullable=False)
    require_sbom: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)
    require_signed_attestation: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)
    require_promotion_binding: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)
    allowed_package_formats_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    allowed_builder_key_refs_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    requested_by: Mapped[str]=mapped_column(String(64),nullable=False)
    approver_one: Mapped[str|None]=mapped_column(String(64))
    approver_two: Mapped[str|None]=mapped_column(String(64))
    state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryForecastModelArtifactRow(Base):
    __tablename__='journey_recovery_forecast_model_artifact'
    forecast_model_artifact_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    challenger_model_version_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    training_manifest_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    build_hash: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    package_ref: Mapped[str]=mapped_column(String(512),nullable=False)
    package_format: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    artifact_digest: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    artifact_size_bytes: Mapped[int]=mapped_column(Integer,nullable=False)
    registry_namespace: Mapped[str]=mapped_column(String(128),nullable=False,index=True)
    state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    registered_by: Mapped[str]=mapped_column(String(64),nullable=False)
    registered_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryForecastArtifactSbomRow(Base):
    __tablename__='journey_recovery_forecast_artifact_sbom'
    forecast_artifact_sbom_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    forecast_model_artifact_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    sbom_format: Mapped[str]=mapped_column(String(32),nullable=False)
    components_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    sbom_digest: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    provenance_json: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryForecastBuildAttestationRow(Base):
    __tablename__='journey_recovery_forecast_build_attestation'
    forecast_build_attestation_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    forecast_model_artifact_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    training_manifest_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    build_hash: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    artifact_digest: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    sbom_digest: Mapped[str]=mapped_column(String(64),nullable=False)
    builder_identity: Mapped[str]=mapped_column(String(128),nullable=False,index=True)
    signing_key_ref: Mapped[str]=mapped_column(String(256),nullable=False)
    attestation_payload_hash: Mapped[str]=mapped_column(String(64),nullable=False)
    signature: Mapped[str]=mapped_column(String(128),nullable=False)
    verification_state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    evidence_reference: Mapped[str]=mapped_column(String(512),nullable=False)
    verified_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryForecastArtifactPromotionBindingRow(Base):
    __tablename__='journey_recovery_forecast_artifact_promotion_binding'
    forecast_artifact_promotion_binding_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    challenger_model_version_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    forecast_model_artifact_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    training_manifest_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    forecast_build_attestation_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    build_hash: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    artifact_digest: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    binding_hash: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    binding_state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    bound_by: Mapped[str]=mapped_column(String(64),nullable=False)
    bound_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryForecastArtifactIntegrityAssessmentRow(Base):
    __tablename__='journey_recovery_forecast_artifact_integrity_assessment'
    forecast_artifact_integrity_assessment_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    forecast_model_artifact_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    expected_artifact_digest: Mapped[str]=mapped_column(String(64),nullable=False)
    observed_artifact_digest: Mapped[str]=mapped_column(String(64),nullable=False)
    expected_build_hash: Mapped[str]=mapped_column(String(64),nullable=False)
    observed_build_hash: Mapped[str]=mapped_column(String(64),nullable=False)
    integrity_state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    reason_codes_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    evidence_reference: Mapped[str]=mapped_column(String(512),nullable=False)
    assessed_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryForecastArtifactGovernanceEventRow(Base):
    __tablename__='journey_recovery_forecast_artifact_governance_event'
    forecast_artifact_governance_event_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    event_type: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    challenger_model_version_id: Mapped[str|None]=mapped_column(String(64),index=True)
    forecast_model_artifact_id: Mapped[str|None]=mapped_column(String(64),index=True)
    evidence_json: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)
    actor: Mapped[str]=mapped_column(String(64),nullable=False)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryForecastServingPolicyRow(Base):
    __tablename__='journey_recovery_forecast_serving_policy'
    forecast_serving_policy_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    version_no: Mapped[int]=mapped_column(Integer,nullable=False)
    require_serving_attestation: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)
    require_runtime_fingerprint: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)
    require_artifact_binding: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)
    requested_by: Mapped[str]=mapped_column(String(64),nullable=False)
    approver_one: Mapped[str|None]=mapped_column(String(64))
    approver_two: Mapped[str|None]=mapped_column(String(64))
    state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryForecastArtifactDeploymentBindingRow(Base):
    __tablename__='journey_recovery_forecast_artifact_deployment_binding'
    forecast_artifact_deployment_binding_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    model_version_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    forecast_model_artifact_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    forecast_artifact_promotion_binding_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    deployment_key: Mapped[str]=mapped_column(String(128),nullable=False,index=True)
    expected_artifact_digest: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    expected_build_hash: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    binding_hash: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    bound_by: Mapped[str]=mapped_column(String(64),nullable=False)
    bound_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryForecastRuntimeModelIdentityRow(Base):
    __tablename__='journey_recovery_forecast_runtime_model_identity'
    forecast_runtime_model_identity_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    deployment_key: Mapped[str]=mapped_column(String(128),nullable=False,index=True)
    runtime_instance_ref: Mapped[str]=mapped_column(String(256),nullable=False,index=True)
    model_version_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    forecast_model_artifact_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    runtime_model_fingerprint: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    registered_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryForecastModelServingAttestationRow(Base):
    __tablename__='journey_recovery_forecast_model_serving_attestation'
    forecast_model_serving_attestation_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    forecast_artifact_deployment_binding_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    forecast_runtime_model_identity_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    model_version_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    forecast_model_artifact_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    expected_artifact_digest: Mapped[str]=mapped_column(String(64),nullable=False)
    loaded_artifact_digest: Mapped[str]=mapped_column(String(64),nullable=False)
    expected_build_hash: Mapped[str]=mapped_column(String(64),nullable=False)
    loaded_build_hash: Mapped[str]=mapped_column(String(64),nullable=False)
    expected_runtime_fingerprint: Mapped[str]=mapped_column(String(64),nullable=False)
    observed_runtime_fingerprint: Mapped[str]=mapped_column(String(64),nullable=False)
    attestation_state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    reason_codes_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    evidence_reference: Mapped[str]=mapped_column(String(512),nullable=False)
    attested_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryForecastModelDeploymentLineageRow(Base):
    __tablename__='journey_recovery_forecast_model_deployment_lineage'
    forecast_model_deployment_lineage_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    deployment_key: Mapped[str]=mapped_column(String(128),nullable=False,index=True)
    previous_binding_id: Mapped[str|None]=mapped_column(String(64),index=True)
    current_binding_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    transition_type: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    transition_hash: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    evidence_reference: Mapped[str]=mapped_column(String(512),nullable=False)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryForecastServingSafetyControlRow(Base):
    __tablename__='journey_recovery_forecast_serving_safety_control'
    forecast_serving_safety_control_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    model_version_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    deployment_key: Mapped[str]=mapped_column(String(128),nullable=False,index=True)
    control_state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    reason_codes_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    activated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    released_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
    release_evidence_reference: Mapped[str|None]=mapped_column(String(512))
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryForecastServingGovernanceEventRow(Base):
    __tablename__='journey_recovery_forecast_serving_governance_event'
    forecast_serving_governance_event_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    event_type: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    model_version_id: Mapped[str|None]=mapped_column(String(64),index=True)
    deployment_key: Mapped[str|None]=mapped_column(String(128),index=True)
    evidence_json: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)
    actor: Mapped[str]=mapped_column(String(64),nullable=False)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryForecastTrafficPolicyRow(Base):
    __tablename__='journey_recovery_forecast_traffic_policy'
    forecast_traffic_policy_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    version_no: Mapped[int]=mapped_column(Integer,nullable=False)
    champion_deployment_key: Mapped[str]=mapped_column(String(128),nullable=False,index=True)
    candidate_deployment_key: Mapped[str]=mapped_column(String(128),nullable=False,index=True)
    allowed_canary_steps_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    min_requests_per_step: Mapped[int]=mapped_column(Integer,nullable=False,default=100)
    max_error_rate: Mapped[float]=mapped_column(Float,nullable=False,default=.02)
    max_timeout_rate: Mapped[float]=mapped_column(Float,nullable=False,default=.01)
    max_p95_latency_ms: Mapped[float]=mapped_column(Float,nullable=False,default=1000)
    max_shadow_divergence: Mapped[float]=mapped_column(Float,nullable=False,default=.25)
    requested_by: Mapped[str]=mapped_column(String(64),nullable=False)
    approver_one: Mapped[str|None]=mapped_column(String(64))
    approver_two: Mapped[str|None]=mapped_column(String(64))
    state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryForecastTrafficAllocationRow(Base):
    __tablename__='journey_recovery_forecast_traffic_allocation'
    forecast_traffic_allocation_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    forecast_traffic_policy_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    champion_percentage: Mapped[int]=mapped_column(Integer,nullable=False)
    canary_percentage: Mapped[int]=mapped_column(Integer,nullable=False)
    allocation_version: Mapped[int]=mapped_column(Integer,nullable=False)
    state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    reason_codes_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    activated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryForecastPredictionProvenanceRow(Base):
    __tablename__='journey_recovery_forecast_prediction_provenance'
    prediction_request_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    forecast_traffic_policy_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    forecast_traffic_allocation_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    subject_key_hash: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    serving_role: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    deployment_key: Mapped[str]=mapped_column(String(128),nullable=False,index=True)
    forecast_artifact_deployment_binding_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    forecast_runtime_model_identity_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    model_version_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    forecast_model_artifact_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    artifact_digest: Mapped[str]=mapped_column(String(64),nullable=False)
    prediction_json: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)
    latency_ms: Mapped[float]=mapped_column(Float,nullable=False)
    serving_status: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryForecastShadowComparisonRow(Base):
    __tablename__='journey_recovery_forecast_shadow_comparison'
    forecast_shadow_comparison_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    champion_prediction_request_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    candidate_model_version_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    candidate_deployment_key: Mapped[str]=mapped_column(String(128),nullable=False,index=True)
    champion_value: Mapped[float]=mapped_column(Float,nullable=False)
    shadow_value: Mapped[float]=mapped_column(Float,nullable=False)
    divergence: Mapped[float]=mapped_column(Float,nullable=False)
    comparison_state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    evidence_json: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryForecastServingBudgetAssessmentRow(Base):
    __tablename__='journey_recovery_forecast_serving_budget_assessment'
    forecast_serving_budget_assessment_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    forecast_traffic_policy_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    canary_percentage: Mapped[int]=mapped_column(Integer,nullable=False)
    request_count: Mapped[int]=mapped_column(Integer,nullable=False)
    error_rate: Mapped[float]=mapped_column(Float,nullable=False)
    timeout_rate: Mapped[float]=mapped_column(Float,nullable=False)
    p95_latency_ms: Mapped[float]=mapped_column(Float,nullable=False)
    invalid_prediction_rate: Mapped[float]=mapped_column(Float,nullable=False)
    fallback_rate: Mapped[float]=mapped_column(Float,nullable=False)
    availability: Mapped[float]=mapped_column(Float,nullable=False)
    attestation_mismatch_rate: Mapped[float]=mapped_column(Float,nullable=False)
    assessment_state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    reason_codes_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    assessed_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryForecastCanaryProgressionRow(Base):
    __tablename__='journey_recovery_forecast_canary_progression'
    forecast_canary_progression_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    forecast_traffic_policy_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    from_percentage: Mapped[int]=mapped_column(Integer,nullable=False)
    to_percentage: Mapped[int]=mapped_column(Integer,nullable=False)
    gate_state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    reason_codes_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    evidence_reference: Mapped[str]=mapped_column(String(512),nullable=False)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryForecastTrafficGovernanceEventRow(Base):
    __tablename__='journey_recovery_forecast_traffic_governance_event'
    forecast_traffic_governance_event_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    event_type: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    forecast_traffic_policy_id: Mapped[str|None]=mapped_column(String(64),index=True)
    evidence_json: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)
    actor: Mapped[str]=mapped_column(String(64),nullable=False)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)


class JourneyRecoveryForecastOutcomeAttributionRow(Base):
    __tablename__='journey_recovery_forecast_outcome_attribution'
    forecast_outcome_attribution_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    prediction_request_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True,unique=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    serving_role: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    deployment_key: Mapped[str]=mapped_column(String(128),nullable=False,index=True)
    model_version_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    predicted_value: Mapped[float]=mapped_column(Float,nullable=False)
    actual_value: Mapped[float]=mapped_column(Float,nullable=False)
    absolute_error: Mapped[float]=mapped_column(Float,nullable=False)
    squared_error: Mapped[float]=mapped_column(Float,nullable=False)
    brier_score: Mapped[float|None]=mapped_column(Float)
    horizon_hours: Mapped[int]=mapped_column(Integer,nullable=False)
    outcome_state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    evidence_reference: Mapped[str]=mapped_column(String(512),nullable=False)
    observed_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    attributed_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryForecastLivePerformanceAssessmentRow(Base):
    __tablename__='journey_recovery_forecast_live_performance_assessment'
    forecast_live_performance_assessment_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    deployment_key: Mapped[str]=mapped_column(String(128),nullable=False,index=True)
    model_version_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    serving_role: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    sample_count: Mapped[int]=mapped_column(Integer,nullable=False)
    mae: Mapped[float]=mapped_column(Float,nullable=False)
    rmse: Mapped[float]=mapped_column(Float,nullable=False)
    mean_brier_score: Mapped[float|None]=mapped_column(Float)
    performance_state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    reason_codes_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    assessed_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryForecastServingAutoDegradeControlRow(Base):
    __tablename__='journey_recovery_forecast_serving_auto_degrade_control'
    forecast_serving_auto_degrade_control_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    deployment_key: Mapped[str]=mapped_column(String(128),nullable=False,index=True)
    control_state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    trigger_assessment_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    reason_codes_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    previous_canary_percentage: Mapped[int]=mapped_column(Integer,nullable=False)
    applied_canary_percentage: Mapped[int]=mapped_column(Integer,nullable=False)
    evidence_reference: Mapped[str]=mapped_column(String(512),nullable=False)
    activated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    released_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
    release_evidence_reference: Mapped[str|None]=mapped_column(String(512))
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryForecastOnlineFeedbackEventRow(Base):
    __tablename__='journey_recovery_forecast_online_feedback_event'
    forecast_online_feedback_event_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    event_type: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    prediction_request_id: Mapped[str|None]=mapped_column(String(64),index=True)
    deployment_key: Mapped[str|None]=mapped_column(String(128),index=True)
    evidence_json: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)
    actor: Mapped[str]=mapped_column(String(64),nullable=False)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryForecastOnlineSegmentPolicyRow(Base):
    __tablename__='journey_recovery_forecast_online_segment_policy'
    forecast_online_segment_policy_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    version_no: Mapped[int]=mapped_column(Integer,nullable=False)
    minimum_segment_samples: Mapped[int]=mapped_column(Integer,nullable=False)
    max_segment_mae: Mapped[float]=mapped_column(Float,nullable=False)
    max_segment_rmse: Mapped[float]=mapped_column(Float,nullable=False)
    max_segment_brier: Mapped[float]=mapped_column(Float,nullable=False)
    consecutive_breaches_required: Mapped[int]=mapped_column(Integer,nullable=False)
    requested_by: Mapped[str]=mapped_column(String(64),nullable=False)
    approver_one: Mapped[str|None]=mapped_column(String(64))
    approver_two: Mapped[str|None]=mapped_column(String(64))
    state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryForecastSegmentPerformanceObservationRow(Base):
    __tablename__='journey_recovery_forecast_segment_performance_observation'
    forecast_segment_performance_observation_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    forecast_outcome_attribution_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True,unique=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    deployment_key: Mapped[str]=mapped_column(String(128),nullable=False,index=True)
    model_version_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    team_key: Mapped[str]=mapped_column(String(128),nullable=False,index=True)
    risk_domain: Mapped[str]=mapped_column(String(128),nullable=False,index=True)
    horizon_hours: Mapped[int]=mapped_column(Integer,nullable=False,index=True)
    absolute_error: Mapped[float]=mapped_column(Float,nullable=False)
    squared_error: Mapped[float]=mapped_column(Float,nullable=False)
    brier_score: Mapped[float|None]=mapped_column(Float)
    observed_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryForecastSegmentPerformanceAssessmentRow(Base):
    __tablename__='journey_recovery_forecast_segment_performance_assessment'
    forecast_segment_performance_assessment_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    deployment_key: Mapped[str]=mapped_column(String(128),nullable=False,index=True)
    model_version_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    team_key: Mapped[str]=mapped_column(String(128),nullable=False,index=True)
    risk_domain: Mapped[str]=mapped_column(String(128),nullable=False,index=True)
    horizon_hours: Mapped[int]=mapped_column(Integer,nullable=False,index=True)
    sample_count: Mapped[int]=mapped_column(Integer,nullable=False)
    mae: Mapped[float]=mapped_column(Float,nullable=False)
    rmse: Mapped[float]=mapped_column(Float,nullable=False)
    mean_brier_score: Mapped[float|None]=mapped_column(Float)
    performance_state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    reason_codes_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    assessed_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryForecastAutomaticRefreshTriggerRow(Base):
    __tablename__='journey_recovery_forecast_automatic_refresh_trigger'
    forecast_automatic_refresh_trigger_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    source_segment_assessment_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    retraining_request_id: Mapped[str|None]=mapped_column(String(64),index=True)
    trigger_state: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    reason_codes_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    evidence_reference: Mapped[str]=mapped_column(String(512),nullable=False)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryForecastOnlineSegmentEventRow(Base):
    __tablename__='journey_recovery_forecast_online_segment_event'
    forecast_online_segment_event_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    event_type: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    segment_assessment_id: Mapped[str|None]=mapped_column(String(64),index=True)
    retraining_request_id: Mapped[str|None]=mapped_column(String(64),index=True)
    evidence_json: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)
    actor: Mapped[str]=mapped_column(String(64),nullable=False)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryForecastRemediationPolicyRow(Base):
    __tablename__='journey_recovery_forecast_remediation_policy'
    forecast_remediation_policy_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    version_no: Mapped[int]=mapped_column(Integer,nullable=False)
    minimum_target_improvement_pct: Mapped[float]=mapped_column(Float,nullable=False)
    max_cross_segment_regression_pct: Mapped[float]=mapped_column(Float,nullable=False)
    minimum_validation_samples: Mapped[int]=mapped_column(Integer,nullable=False)
    requested_by: Mapped[str]=mapped_column(String(64),nullable=False)
    approver_one: Mapped[str|None]=mapped_column(String(64))
    approver_two: Mapped[str|None]=mapped_column(String(64))
    state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryForecastRemediationTargetRow(Base):
    __tablename__='journey_recovery_forecast_remediation_target'
    forecast_remediation_target_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    retraining_request_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True,unique=True)
    source_segment_assessment_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    champion_model_version_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    team_key: Mapped[str]=mapped_column(String(128),nullable=False,index=True)
    risk_domain: Mapped[str]=mapped_column(String(128),nullable=False,index=True)
    horizon_hours: Mapped[int]=mapped_column(Integer,nullable=False,index=True)
    baseline_mae: Mapped[float]=mapped_column(Float,nullable=False)
    baseline_rmse: Mapped[float]=mapped_column(Float,nullable=False)
    baseline_brier: Mapped[float|None]=mapped_column(Float)
    required_improvement_pct: Mapped[float]=mapped_column(Float,nullable=False)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryForecastSegmentValidationRow(Base):
    __tablename__='journey_recovery_forecast_segment_validation'
    forecast_segment_validation_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    remediation_target_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    challenger_model_version_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    team_key: Mapped[str]=mapped_column(String(128),nullable=False,index=True)
    risk_domain: Mapped[str]=mapped_column(String(128),nullable=False,index=True)
    horizon_hours: Mapped[int]=mapped_column(Integer,nullable=False,index=True)
    sample_count: Mapped[int]=mapped_column(Integer,nullable=False)
    challenger_mae: Mapped[float]=mapped_column(Float,nullable=False)
    improvement_pct: Mapped[float]=mapped_column(Float,nullable=False)
    validation_state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    reason_codes_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    evaluated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryForecastCrossSegmentRegressionRow(Base):
    __tablename__='journey_recovery_forecast_cross_segment_regression'
    forecast_cross_segment_regression_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    remediation_target_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    challenger_model_version_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    segment_key: Mapped[str]=mapped_column(String(256),nullable=False,index=True)
    baseline_mae: Mapped[float]=mapped_column(Float,nullable=False)
    challenger_mae: Mapped[float]=mapped_column(Float,nullable=False)
    regression_pct: Mapped[float]=mapped_column(Float,nullable=False)
    regression_state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    evaluated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryForecastRemediationAssessmentRow(Base):
    __tablename__='journey_recovery_forecast_remediation_assessment'
    forecast_remediation_assessment_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    remediation_target_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    challenger_model_version_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    effectiveness_state: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    target_improvement_pct: Mapped[float]=mapped_column(Float,nullable=False)
    max_cross_segment_regression_pct: Mapped[float]=mapped_column(Float,nullable=False)
    reason_codes_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    promotion_eligible: Mapped[bool]=mapped_column(Boolean,nullable=False,default=False)
    evidence_json: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)
    evaluated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryForecastRemediationEventRow(Base):
    __tablename__='journey_recovery_forecast_remediation_event'
    forecast_remediation_event_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    event_type: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    remediation_target_id: Mapped[str|None]=mapped_column(String(64),index=True)
    challenger_model_version_id: Mapped[str|None]=mapped_column(String(64),index=True)
    evidence_json: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)
    actor: Mapped[str]=mapped_column(String(64),nullable=False)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryForecastGeneralizationPolicyRow(Base):
    __tablename__='journey_recovery_forecast_generalization_policy'
    forecast_generalization_policy_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    version_no: Mapped[int]=mapped_column(Integer,nullable=False)
    minimum_adjacent_samples: Mapped[int]=mapped_column(Integer,nullable=False)
    max_adjacent_regression_pct: Mapped[float]=mapped_column(Float,nullable=False)
    max_holdout_regression_pct: Mapped[float]=mapped_column(Float,nullable=False)
    minimum_target_sustain_improvement_pct: Mapped[float]=mapped_column(Float,nullable=False)
    requested_by: Mapped[str]=mapped_column(String(64),nullable=False)
    approver_one: Mapped[str|None]=mapped_column(String(64))
    approver_two: Mapped[str|None]=mapped_column(String(64))
    state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryForecastGeneralizationValidationRow(Base):
    __tablename__='journey_recovery_forecast_generalization_validation'
    forecast_generalization_validation_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    remediation_target_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    challenger_model_version_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    segment_key: Mapped[str]=mapped_column(String(256),nullable=False,index=True)
    sample_count: Mapped[int]=mapped_column(Integer,nullable=False)
    baseline_mae: Mapped[float]=mapped_column(Float,nullable=False)
    challenger_mae: Mapped[float]=mapped_column(Float,nullable=False)
    regression_pct: Mapped[float]=mapped_column(Float,nullable=False)
    validation_state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    reason_codes_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    evaluated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryForecastHoldoutValidationRow(Base):
    __tablename__='journey_recovery_forecast_holdout_validation'
    forecast_holdout_validation_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    remediation_target_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    challenger_model_version_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    holdout_segment_key: Mapped[str]=mapped_column(String(256),nullable=False,index=True)
    sample_count: Mapped[int]=mapped_column(Integer,nullable=False)
    baseline_mae: Mapped[float]=mapped_column(Float,nullable=False)
    challenger_mae: Mapped[float]=mapped_column(Float,nullable=False)
    regression_pct: Mapped[float]=mapped_column(Float,nullable=False)
    validation_state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    reason_codes_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    evaluated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryForecastPostPromotionProofRow(Base):
    __tablename__='journey_recovery_forecast_post_promotion_proof'
    forecast_post_promotion_proof_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    remediation_target_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    promoted_model_version_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    target_live_improvement_pct: Mapped[float]=mapped_column(Float,nullable=False)
    max_adjacent_regression_pct: Mapped[float]=mapped_column(Float,nullable=False)
    max_holdout_regression_pct: Mapped[float]=mapped_column(Float,nullable=False)
    global_performance_state: Mapped[str]=mapped_column(String(24),nullable=False)
    proof_state: Mapped[str]=mapped_column(String(40),nullable=False,index=True)
    rollback_required: Mapped[bool]=mapped_column(Boolean,nullable=False,default=False)
    reason_codes_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    evidence_json: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)
    evaluated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryForecastGeneralizationEventRow(Base):
    __tablename__='journey_recovery_forecast_generalization_event'
    forecast_generalization_event_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    event_type: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    remediation_target_id: Mapped[str|None]=mapped_column(String(64),index=True)
    model_version_id: Mapped[str|None]=mapped_column(String(64),index=True)
    evidence_json: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)
    actor: Mapped[str]=mapped_column(String(64),nullable=False)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryForecastRemediationPortfolioRow(Base):
    __tablename__='journey_recovery_forecast_remediation_portfolio'
    forecast_remediation_portfolio_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    champion_model_version_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    target_ids_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    objectives_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    protected_segment_keys_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    portfolio_state: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    created_by: Mapped[str]=mapped_column(String(64),nullable=False)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryForecastSegmentConflictRow(Base):
    __tablename__='journey_recovery_forecast_segment_conflict'
    forecast_segment_conflict_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    portfolio_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    target_a_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    target_b_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    conflict_state: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    resolution_state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    conflict_penalty_pct: Mapped[float]=mapped_column(Float,nullable=False,default=0)
    shared_root_cause_json: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)
    evidence_json: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)
    assessed_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryForecastPortfolioCandidateRow(Base):
    __tablename__='journey_recovery_forecast_portfolio_candidate'
    forecast_portfolio_candidate_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    portfolio_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    challenger_model_version_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    strategy: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    covered_target_ids_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    candidate_state: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    registered_by: Mapped[str]=mapped_column(String(64),nullable=False)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryForecastPortfolioAssessmentRow(Base):
    __tablename__='journey_recovery_forecast_portfolio_assessment'
    forecast_portfolio_assessment_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    portfolio_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    portfolio_candidate_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    challenger_model_version_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    must_fix_total: Mapped[int]=mapped_column(Integer,nullable=False)
    must_fix_passed: Mapped[int]=mapped_column(Integer,nullable=False)
    average_target_improvement_pct: Mapped[float]=mapped_column(Float,nullable=False)
    max_cross_segment_regression_pct: Mapped[float]=mapped_column(Float,nullable=False)
    conflict_penalty_pct: Mapped[float]=mapped_column(Float,nullable=False)
    portfolio_score: Mapped[float]=mapped_column(Float,nullable=False)
    assessment_state: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    reason_codes_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    evidence_json: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)
    evaluated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryForecastCandidateArbitrationRow(Base):
    __tablename__='journey_recovery_forecast_candidate_arbitration'
    forecast_candidate_arbitration_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    portfolio_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    winner_candidate_id: Mapped[str|None]=mapped_column(String(64),index=True)
    winner_model_version_id: Mapped[str|None]=mapped_column(String(64),index=True)
    decision_state: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    rankings_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    reason_codes_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    evidence_json: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)
    decided_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryForecastPortfolioPromotionGateRow(Base):
    __tablename__='journey_recovery_forecast_portfolio_promotion_gate'
    forecast_portfolio_promotion_gate_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    portfolio_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    portfolio_candidate_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    challenger_model_version_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    arbitration_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    gate_state: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    promotion_eligible: Mapped[bool]=mapped_column(Boolean,nullable=False,default=False)
    reason_codes_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    evidence_json: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)
    evaluated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryForecastPortfolioEventRow(Base):
    __tablename__='journey_recovery_forecast_portfolio_event'
    forecast_portfolio_event_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    portfolio_id: Mapped[str|None]=mapped_column(String(64),index=True)
    portfolio_candidate_id: Mapped[str|None]=mapped_column(String(64),index=True)
    event_type: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    evidence_json: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)
    actor: Mapped[str]=mapped_column(String(64),nullable=False)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryForecastPortfolioChampionStateRow(Base):
    __tablename__='journey_recovery_forecast_portfolio_champion_state'
    forecast_portfolio_champion_state_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    portfolio_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    champion_model_version_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    previous_stable_champion_model_version_id: Mapped[str|None]=mapped_column(String(64),index=True)
    objective_snapshot_json: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)
    champion_state: Mapped[str]=mapped_column(String(40),nullable=False,index=True)
    assigned_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryForecastChampionContinuityAssessmentRow(Base):
    __tablename__='journey_recovery_forecast_champion_continuity_assessment'
    forecast_champion_continuity_assessment_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    champion_state_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    champion_model_version_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    portfolio_objective_score: Mapped[float]=mapped_column(Float,nullable=False)
    target_health_state: Mapped[str]=mapped_column(String(24),nullable=False)
    protected_segment_state: Mapped[str]=mapped_column(String(24),nullable=False)
    serving_health_state: Mapped[str]=mapped_column(String(24),nullable=False)
    holdout_state: Mapped[str]=mapped_column(String(24),nullable=False)
    continuity_state: Mapped[str]=mapped_column(String(40),nullable=False,index=True)
    reason_codes_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    evidence_json: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)
    assessed_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryForecastChampionChallengeRow(Base):
    __tablename__='journey_recovery_forecast_champion_challenge'
    forecast_champion_challenge_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    portfolio_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    champion_state_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    current_champion_model_version_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    portfolio_candidate_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    candidate_model_version_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    challenge_state: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    opened_by: Mapped[str]=mapped_column(String(64),nullable=False)
    opened_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryForecastChampionCandidateComparisonRow(Base):
    __tablename__='journey_recovery_forecast_champion_candidate_comparison'
    forecast_champion_candidate_comparison_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    challenge_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    champion_model_version_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    candidate_model_version_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    champion_portfolio_score: Mapped[float]=mapped_column(Float,nullable=False)
    candidate_portfolio_score: Mapped[float]=mapped_column(Float,nullable=False)
    improvement_pct: Mapped[float]=mapped_column(Float,nullable=False)
    protected_segment_safe: Mapped[bool]=mapped_column(Boolean,nullable=False)
    generalization_pass: Mapped[bool]=mapped_column(Boolean,nullable=False)
    serving_health_pass: Mapped[bool]=mapped_column(Boolean,nullable=False)
    statistical_confidence_pass: Mapped[bool]=mapped_column(Boolean,nullable=False)
    comparison_state: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    reason_codes_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    evidence_json: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)
    compared_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryForecastChampionReplacementDecisionRow(Base):
    __tablename__='journey_recovery_forecast_champion_replacement_decision'
    forecast_champion_replacement_decision_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    challenge_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    comparison_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    from_model_version_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    to_model_version_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    decision_state: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    approved: Mapped[bool]=mapped_column(Boolean,nullable=False,default=False)
    reason_codes_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    evidence_json: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)
    decided_by: Mapped[str]=mapped_column(String(64),nullable=False)
    decided_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryForecastChampionTransitionRow(Base):
    __tablename__='journey_recovery_forecast_champion_transition'
    forecast_champion_transition_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    replacement_decision_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    from_model_version_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    to_model_version_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    transition_state: Mapped[str]=mapped_column(String(40),nullable=False,index=True)
    canary_percentage: Mapped[int]=mapped_column(Integer,nullable=False,default=0)
    previous_stable_champion_model_version_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    evidence_json: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)
    transitioned_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

class JourneyRecoveryForecastChampionGovernanceEventRow(Base):
    __tablename__='journey_recovery_forecast_champion_governance_event'
    forecast_champion_governance_event_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    environment: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    event_type: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    champion_state_id: Mapped[str|None]=mapped_column(String(64),index=True)
    challenge_id: Mapped[str|None]=mapped_column(String(64),index=True)
    evidence_json: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)
    actor: Mapped[str]=mapped_column(String(64),nullable=False)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    supplier_fact_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)

# Mother Plan Production Build 1 — Hotel Partner Self-Operating Core.
# These tables intentionally keep recommendation governance outside the commercial
# supply graph. Partner edits can change supplier facts only through the explicit
# publish/change-request workflows implemented by the partner service.
class HotelPartnerPropertyRow(Base):
    __tablename__='hotel_partner_property'
    property_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    supplier_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    name_zh: Mapped[str]=mapped_column(String(256),nullable=False)
    name_en: Mapped[str|None]=mapped_column(String(256))
    property_type: Mapped[str]=mapped_column(String(48),nullable=False)
    group_name: Mapped[str|None]=mapped_column(String(128))
    brand_name: Mapped[str|None]=mapped_column(String(128))
    address_json: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)
    latitude: Mapped[float|None]=mapped_column(Float)
    longitude: Mapped[float|None]=mapped_column(Float)
    contacts_json: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)
    legal_json: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)
    operations_json: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)
    poi_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    publication_state: Mapped[str]=mapped_column(String(24),nullable=False,default='DRAFT',index=True)
    version: Mapped[int]=mapped_column(Integer,nullable=False,default=1)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)

class HotelPartnerChangeRequestRow(Base):
    __tablename__='hotel_partner_change_request'
    change_request_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    property_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    field_group: Mapped[str]=mapped_column(String(48),nullable=False,index=True)
    proposed_value_json: Mapped[dict]=mapped_column(JSON,nullable=False)
    evidence_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    state: Mapped[str]=mapped_column(String(24),nullable=False,default='SUBMITTED',index=True)
    requested_by: Mapped[str]=mapped_column(String(64),nullable=False)
    reviewed_by: Mapped[str|None]=mapped_column(String(64))
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
    reviewed_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True))

class HotelPartnerRoomTypeRow(Base):
    __tablename__='hotel_partner_room_type'
    room_type_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    property_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    name_zh: Mapped[str]=mapped_column(String(256),nullable=False)
    name_en: Mapped[str|None]=mapped_column(String(256))
    sale_unit: Mapped[str]=mapped_column(String(24),nullable=False,default='WHOLE_ROOM')
    physical_room_count: Mapped[int]=mapped_column(Integer,nullable=False)
    occupancy_json: Mapped[dict]=mapped_column(JSON,nullable=False)
    bed_configurations_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    attributes_json: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)
    media_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    state: Mapped[str]=mapped_column(String(24),nullable=False,default='ACTIVE',index=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)

class HotelPartnerSellableProductRow(Base):
    __tablename__='hotel_partner_sellable_product'
    sellable_product_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    property_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    room_type_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    name: Mapped[str]=mapped_column(String(256),nullable=False)
    occupancy_offer_json: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)
    state: Mapped[str]=mapped_column(String(24),nullable=False,default='ACTIVE',index=True)

class HotelPartnerRatePlanRow(Base):
    __tablename__='hotel_partner_rate_plan'
    rate_plan_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    property_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    sellable_product_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    name: Mapped[str]=mapped_column(String(256),nullable=False)
    payment_type: Mapped[str]=mapped_column(String(24),nullable=False)
    meal_plan_json: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)
    cancellation_tiers_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    restrictions_json: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)
    default_ari_json: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)
    state: Mapped[str]=mapped_column(String(24),nullable=False,default='ACTIVE',index=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)

class HotelPartnerFacilityDefinitionRow(Base):
    __tablename__='hotel_partner_facility_definition'
    facility_definition_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    code: Mapped[str]=mapped_column(String(96),nullable=False,unique=True)
    category: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    name_zh: Mapped[str]=mapped_column(String(128),nullable=False)
    name_en: Mapped[str|None]=mapped_column(String(128))
    attribute_schema_json: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)

class HotelPartnerFacilityAssignmentRow(Base):
    __tablename__='hotel_partner_facility_assignment'
    facility_assignment_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    property_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    room_type_id: Mapped[str|None]=mapped_column(String(64),index=True)
    facility_definition_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    status: Mapped[str]=mapped_column(String(24),nullable=False)
    inherited: Mapped[bool]=mapped_column(Boolean,nullable=False,default=False)
    attributes_json: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)
    evidence_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
    __table_args__=(UniqueConstraint('property_id','room_type_id','facility_definition_id',name='uq_partner_facility_scope'),)

class HotelPartnerPolicyRow(Base):
    __tablename__='hotel_partner_policy'
    policy_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    property_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    policy_type: Mapped[str]=mapped_column(String(48),nullable=False,index=True)
    rule_json: Mapped[dict]=mapped_column(JSON,nullable=False)
    effective_from: Mapped[str|None]=mapped_column(String(10))
    effective_to: Mapped[str|None]=mapped_column(String(10))
    state: Mapped[str]=mapped_column(String(24),nullable=False,default='ACTIVE')
    version: Mapped[int]=mapped_column(Integer,nullable=False,default=1)
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)

class HotelPartnerAriOverrideRow(Base):
    __tablename__='hotel_partner_ari_override'
    ari_override_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    property_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    room_type_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    rate_plan_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    stay_date: Mapped[str]=mapped_column(String(10),nullable=False,index=True)
    sell_status: Mapped[str]=mapped_column(String(16),nullable=False)
    inventory_mode: Mapped[str]=mapped_column(String(16),nullable=False)
    remaining_rooms: Mapped[int|None]=mapped_column(Integer)
    exhaustion_policy: Mapped[str]=mapped_column(String(24),nullable=False)
    inventory_sharing: Mapped[str]=mapped_column(String(24),nullable=False)
    price_json: Mapped[dict]=mapped_column(JSON,nullable=False)
    restrictions_json: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)
    override_fields_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    evidence_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    updated_by: Mapped[str]=mapped_column(String(64),nullable=False)
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
    __table_args__=(UniqueConstraint('rate_plan_id','stay_date',name='uq_partner_ari_rate_date'),)

class HotelPartnerOperationalInboxRow(Base):
    __tablename__='hotel_partner_operational_inbox'
    inbox_item_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    property_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    item_type: Mapped[str]=mapped_column(String(48),nullable=False,index=True)
    priority: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    sla_due_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True),index=True)
    owner_id: Mapped[str|None]=mapped_column(String(64),index=True)
    state: Mapped[str]=mapped_column(String(24),nullable=False,default='OPEN',index=True)
    subject: Mapped[str]=mapped_column(String(256),nullable=False)
    payload_json: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)
    evidence_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)

class HotelPartnerGoOfferAuthorityRow(Base):
    __tablename__='hotel_partner_go_offer_authority'
    go_offer_authority_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    property_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    requirement_type: Mapped[str]=mapped_column(String(32),nullable=False)
    quote_mode: Mapped[str]=mapped_column(String(24),nullable=False)
    authorized_inventory_json: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)
    authorized_rules_json: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)
    packages_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    price_floor_json: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)
    validity_json: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)
    conditions_json: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)
    source_scope: Mapped[str]=mapped_column(String(32),nullable=False,default='GO_OFFER_DEDICATED')
    state: Mapped[str]=mapped_column(String(24),nullable=False,default='ACTIVE')
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
    __table_args__=(UniqueConstraint('property_id','requirement_type',name='uq_partner_offer_authority_type'),)

class HotelPartnerAuditEventRow(Base):
    __tablename__='hotel_partner_audit_event'
    audit_event_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    property_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    event_type: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    aggregate_type: Mapped[str]=mapped_column(String(48),nullable=False)
    aggregate_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    payload_json: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)
    actor_id: Mapped[str]=mapped_column(String(64),nullable=False)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)

# Mother Plan Production Build 2 — Commercial Constitution + GO Admin Commercial OS.
class CommercialPolicyVersionRow(Base):
    __tablename__='commercial_policy_version'
    policy_version_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    policy_key: Mapped[str]=mapped_column(String(96),nullable=False,index=True)
    version_no: Mapped[int]=mapped_column(Integer,nullable=False)
    scope: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    rule_json: Mapped[dict]=mapped_column(JSON,nullable=False)
    content_hash: Mapped[str]=mapped_column(String(64),nullable=False)
    state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    requested_by: Mapped[str]=mapped_column(String(64),nullable=False)
    approved_by: Mapped[str|None]=mapped_column(String(64))
    effective_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
    __table_args__=(UniqueConstraint('policy_key','version_no',name='uq_commercial_policy_version'),)

class CommercialDecisionRow(Base):
    __tablename__='commercial_decision'
    commercial_decision_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    decision_type: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    supplier_id: Mapped[str|None]=mapped_column(String(64),index=True)
    property_id: Mapped[str|None]=mapped_column(String(64),index=True)
    policy_version_ids_json: Mapped[list]=mapped_column(JSON,nullable=False)
    input_json: Mapped[dict]=mapped_column(JSON,nullable=False)
    output_json: Mapped[dict]=mapped_column(JSON,nullable=False)
    reason_codes_json: Mapped[list]=mapped_column(JSON,nullable=False)
    decided_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)

class CommercialEvidenceRow(Base):
    __tablename__='commercial_evidence'
    commercial_evidence_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    decision_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    evidence_type: Mapped[str]=mapped_column(String(48),nullable=False,index=True)
    reference: Mapped[str]=mapped_column(String(512),nullable=False)
    payload_hash: Mapped[str]=mapped_column(String(64),nullable=False)
    captured_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)

class SupplierSubscriptionRow(Base):
    __tablename__='supplier_subscription'
    supplier_subscription_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    supplier_id: Mapped[str]=mapped_column(String(64),nullable=False,unique=True,index=True)
    qualifying_order_count: Mapped[int]=mapped_column(Integer,nullable=False,default=0)
    free_order_limit: Mapped[int]=mapped_column(Integer,nullable=False,default=20)
    state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    triggered_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
    current_plan: Mapped[str|None]=mapped_column(String(48))
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)

class T20QualifyingOrderRow(Base):
    __tablename__='t20_qualifying_order'
    t20_order_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    order_id: Mapped[str]=mapped_column(String(64),nullable=False,unique=True,index=True)
    supplier_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    property_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    source_type: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    order_state: Mapped[str]=mapped_column(String(32),nullable=False)
    qualifies: Mapped[bool]=mapped_column(Boolean,nullable=False,index=True)
    exclusion_reason: Mapped[str|None]=mapped_column(String(64))
    counted_sequence: Mapped[int|None]=mapped_column(Integer)
    evidence_json: Mapped[list]=mapped_column(JSON,nullable=False)
    evidence_hash: Mapped[str]=mapped_column(String(64),nullable=False)
    occurred_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)

class SupplierCommercialCohortRow(Base):
    __tablename__='supplier_commercial_cohort'
    commercial_cohort_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    supplier_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    property_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    recommendation_cohort: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    activation_cohort: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    t20_reached_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
    __table_args__=(UniqueConstraint('supplier_id','property_id',name='uq_supplier_commercial_cohort'),)

class SubscriptionInvoiceRow(Base):
    __tablename__='subscription_invoice'
    subscription_invoice_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    invoice_number: Mapped[str]=mapped_column(String(64),nullable=False,unique=True)
    supplier_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    billing_period: Mapped[str]=mapped_column(String(7),nullable=False,index=True)
    plan: Mapped[str]=mapped_column(String(32),nullable=False)
    amount_minor: Mapped[int]=mapped_column(BigInteger,nullable=False)
    currency: Mapped[str]=mapped_column(String(3),nullable=False)
    state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    policy_version_id: Mapped[str]=mapped_column(String(64),nullable=False)
    due_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
    __table_args__=(UniqueConstraint('supplier_id','billing_period',name='uq_subscription_invoice_period'),)

class SubscriptionWaiverRow(Base):
    __tablename__='subscription_waiver'
    subscription_waiver_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    supplier_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    billing_period: Mapped[str]=mapped_column(String(7),nullable=False,index=True)
    reason: Mapped[str]=mapped_column(String(512),nullable=False)
    evidence_reference: Mapped[str]=mapped_column(String(512),nullable=False)
    state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    requested_by: Mapped[str]=mapped_column(String(64),nullable=False)
    approved_by: Mapped[str|None]=mapped_column(String(64))
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
    decided_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
    __table_args__=(UniqueConstraint('supplier_id','billing_period',name='uq_subscription_waiver_period'),)

class CommercialAuditEventRow(Base):
    __tablename__='commercial_audit_event'
    commercial_audit_event_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    event_type: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    aggregate_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    actor_id: Mapped[str]=mapped_column(String(64),nullable=False)
    payload_json: Mapped[dict]=mapped_column(JSON,nullable=False)
    previous_hash: Mapped[str|None]=mapped_column(String(64))
    event_hash: Mapped[str]=mapped_column(String(64),nullable=False,unique=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)

# Build 20 — channel-neutral payment, ledger and reconciliation core.
class OmnichannelMerchantBindingRow(Base):
    __tablename__='omnichannel_merchant_binding'
    merchant_binding_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    owner_type: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    owner_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    channel: Mapped[str]=mapped_column(String(40),nullable=False,index=True)
    market: Mapped[str]=mapped_column(String(8),nullable=False,index=True)
    merchant_reference: Mapped[str]=mapped_column(String(256),nullable=False)
    credential_reference: Mapped[str]=mapped_column(String(512),nullable=False)
    webhook_key_reference: Mapped[str]=mapped_column(String(512),nullable=False)
    capabilities_json: Mapped[list]=mapped_column(JSON,nullable=False)
    state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
    __table_args__=(UniqueConstraint('owner_type','owner_id','channel','market',name='uq_omni_merchant_channel'),)

class OmnichannelPaymentIntentRow(Base):
    __tablename__='omnichannel_payment_intent'
    payment_intent_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    business_type: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    business_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    payer_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    payee_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    operation: Mapped[str]=mapped_column(String(24),nullable=False)
    amount_minor: Mapped[int]=mapped_column(BigInteger,nullable=False)
    currency: Mapped[str]=mapped_column(String(3),nullable=False)
    channel_priority_json: Mapped[list]=mapped_column(JSON,nullable=False)
    selected_channel: Mapped[str|None]=mapped_column(String(40),index=True)
    state: Mapped[str]=mapped_column(String(40),nullable=False,index=True)
    idempotency_key: Mapped[str]=mapped_column(String(128),nullable=False,unique=True)
    automatic_fallback_allowed: Mapped[bool]=mapped_column(Boolean,nullable=False,default=False)
    user_channel_consent_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)

class OmnichannelPaymentAttemptRow(Base):
    __tablename__='omnichannel_payment_attempt'
    payment_attempt_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    payment_intent_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    channel: Mapped[str]=mapped_column(String(40),nullable=False,index=True)
    attempt_no: Mapped[int]=mapped_column(Integer,nullable=False)
    external_operation_id: Mapped[str|None]=mapped_column(String(128),unique=True)
    channel_idempotency_key: Mapped[str]=mapped_column(String(128),nullable=False,unique=True)
    state: Mapped[str]=mapped_column(String(40),nullable=False,index=True)
    external_invoked: Mapped[bool]=mapped_column(Boolean,nullable=False)
    failure_code: Mapped[str|None]=mapped_column(String(96))
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
    __table_args__=(UniqueConstraint('payment_intent_id','attempt_no',name='uq_omni_attempt_no'),)

class OmnichannelWebhookReceiptRow(Base):
    __tablename__='omnichannel_webhook_receipt'
    webhook_receipt_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    channel: Mapped[str]=mapped_column(String(40),nullable=False,index=True)
    external_event_id: Mapped[str]=mapped_column(String(128),nullable=False)
    payment_attempt_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    signature_verified: Mapped[bool]=mapped_column(Boolean,nullable=False)
    payload_hash: Mapped[str]=mapped_column(String(64),nullable=False)
    received_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
    __table_args__=(UniqueConstraint('channel','external_event_id',name='uq_omni_webhook_event'),)

class OmnichannelLedgerEntryRow(Base):
    __tablename__='omnichannel_ledger_entry'
    ledger_entry_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    transaction_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    payment_intent_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    account_code: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    direction: Mapped[str]=mapped_column(String(8),nullable=False)
    amount_minor: Mapped[int]=mapped_column(BigInteger,nullable=False)
    currency: Mapped[str]=mapped_column(String(3),nullable=False)
    entry_type: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    evidence_hash: Mapped[str]=mapped_column(String(64),nullable=False)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)

class OmnichannelReconciliationRow(Base):
    __tablename__='omnichannel_reconciliation'
    reconciliation_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    payment_intent_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    channel: Mapped[str]=mapped_column(String(40),nullable=False,index=True)
    channel_amount_minor: Mapped[int|None]=mapped_column(BigInteger)
    bank_amount_minor: Mapped[int|None]=mapped_column(BigInteger)
    ledger_amount_minor: Mapped[int]=mapped_column(BigInteger,nullable=False)
    fee_minor: Mapped[int]=mapped_column(BigInteger,nullable=False,default=0)
    tax_minor: Mapped[int]=mapped_column(BigInteger,nullable=False,default=0)
    fx_minor: Mapped[int]=mapped_column(BigInteger,nullable=False,default=0)
    state: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    difference_minor: Mapped[int]=mapped_column(BigInteger,nullable=False)
    evidence_json: Mapped[list]=mapped_column(JSON,nullable=False)
    reconciled_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)

class OmnichannelPayoutRow(Base):
    __tablename__='omnichannel_payout'
    payout_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    beneficiary_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    source_intent_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    amount_minor: Mapped[int]=mapped_column(BigInteger,nullable=False)
    currency: Mapped[str]=mapped_column(String(3),nullable=False)
    channel: Mapped[str]=mapped_column(String(40),nullable=False)
    state: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    idempotency_key: Mapped[str]=mapped_column(String(128),nullable=False,unique=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)

class OmnichannelMoneyMovementRow(Base):
    __tablename__='omnichannel_money_movement'
    money_movement_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    root_payment_intent_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    parent_movement_id: Mapped[str|None]=mapped_column(String(64),index=True)
    movement_type: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    business_type: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    business_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    amount_minor: Mapped[int]=mapped_column(BigInteger,nullable=False)
    currency: Mapped[str]=mapped_column(String(3),nullable=False)
    state: Mapped[str]=mapped_column(String(40),nullable=False,index=True)
    idempotency_key: Mapped[str]=mapped_column(String(128),nullable=False,unique=True)
    external_reference: Mapped[str|None]=mapped_column(String(128))
    evidence_json: Mapped[list]=mapped_column(JSON,nullable=False)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)

class FinanceCloseBatchRow(Base):
    __tablename__='finance_close_batch'
    finance_close_batch_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    close_date: Mapped[str]=mapped_column(String(10),nullable=False,unique=True,index=True)
    state: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    movement_count: Mapped[int]=mapped_column(Integer,nullable=False)
    debit_minor: Mapped[int]=mapped_column(BigInteger,nullable=False)
    credit_minor: Mapped[int]=mapped_column(BigInteger,nullable=False)
    difference_minor: Mapped[int]=mapped_column(BigInteger,nullable=False)
    blockers_json: Mapped[list]=mapped_column(JSON,nullable=False)
    evidence_hash: Mapped[str]=mapped_column(String(64),nullable=False)
    requested_by: Mapped[str]=mapped_column(String(64),nullable=False)
    approved_by: Mapped[str|None]=mapped_column(String(64))
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
    closed_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True))

class FinanceCloseLineRow(Base):
    __tablename__='finance_close_line'
    finance_close_line_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    finance_close_batch_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    source_type: Mapped[str]=mapped_column(String(32),nullable=False)
    source_id: Mapped[str]=mapped_column(String(64),nullable=False)
    state: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    amount_minor: Mapped[int]=mapped_column(BigInteger,nullable=False)
    evidence_hash: Mapped[str]=mapped_column(String(64),nullable=False)
    __table_args__=(UniqueConstraint('finance_close_batch_id','source_type','source_id',name='uq_finance_close_source'),)

class SupplierVerticalCapabilityRow(Base):
    __tablename__='supplier_vertical_capability'
    supplier_vertical_capability_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    supplier_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    vertical: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    capability: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    mode: Mapped[str]=mapped_column(String(32),nullable=False)
    authority_reference: Mapped[str]=mapped_column(String(512),nullable=False)
    state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
    __table_args__=(UniqueConstraint('supplier_id','vertical','capability',name='uq_supplier_vertical_capability'),)

class SupplierCertificationRunRow(Base):
    __tablename__='supplier_certification_run'
    supplier_certification_run_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    supplier_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    vertical: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    checks_json: Mapped[dict]=mapped_column(JSON,nullable=False)
    evidence_json: Mapped[list]=mapped_column(JSON,nullable=False)
    state: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    blockers_json: Mapped[list]=mapped_column(JSON,nullable=False)
    requested_by: Mapped[str]=mapped_column(String(64),nullable=False)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)

class ConsumerUnifiedLifecycleRow(Base):
    __tablename__='consumer_unified_lifecycle'
    consumer_unified_lifecycle_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    account_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    vertical: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    order_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    supplier_id: Mapped[str|None]=mapped_column(String(64),index=True)
    title: Mapped[str]=mapped_column(String(256),nullable=False)
    lifecycle_state: Mapped[str]=mapped_column(String(40),nullable=False,index=True)
    payment_state: Mapped[str]=mapped_column(String(40),nullable=False)
    refund_state: Mapped[str]=mapped_column(String(40),nullable=False)
    change_allowed: Mapped[bool]=mapped_column(Boolean,nullable=False)
    cancel_allowed: Mapped[bool]=mapped_column(Boolean,nullable=False)
    facts_json: Mapped[dict]=mapped_column(JSON,nullable=False)
    evidence_reference: Mapped[str]=mapped_column(String(512),nullable=False)
    source_updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
    __table_args__=(UniqueConstraint('vertical','order_id',name='uq_consumer_unified_vertical_order'),)

class ConsumerUnifiedLifecycleEventRow(Base):
    __tablename__='consumer_unified_lifecycle_event'
    consumer_unified_lifecycle_event_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    consumer_unified_lifecycle_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    event_type: Mapped[str]=mapped_column(String(48),nullable=False,index=True)
    state: Mapped[str]=mapped_column(String(40),nullable=False)
    evidence_reference: Mapped[str]=mapped_column(String(512),nullable=False)
    occurred_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)

class DistributionAuthorityRow(Base):
    __tablename__='distribution_authority'
    distribution_authority_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    supplier_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    property_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    direct_enabled: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)
    fallback_enabled: Mapped[bool]=mapped_column(Boolean,nullable=False,default=False)
    fallback_connectors_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    authority_evidence_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)

class CommercialPoolMembershipRow(Base):
    __tablename__='commercial_pool_membership'
    commercial_pool_membership_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    property_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    pool_type: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    eligible: Mapped[bool]=mapped_column(Boolean,nullable=False)
    basis_json: Mapped[dict]=mapped_column(JSON,nullable=False)
    decision_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    evaluated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
    __table_args__=(UniqueConstraint('property_id','pool_type',name='uq_commercial_pool_property'),)

class HotelNetGuardAssessmentRow(Base):
    __tablename__='hotel_net_guard_assessment'
    hotel_net_guard_assessment_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    property_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    currency: Mapped[str]=mapped_column(String(3),nullable=False)
    supplier_net_minor: Mapped[int]=mapped_column(BigInteger,nullable=False)
    authorized_floor_minor: Mapped[int]=mapped_column(BigInteger,nullable=False)
    assessment_state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    reason_codes_json: Mapped[list]=mapped_column(JSON,nullable=False)
    decision_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    assessed_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)

class CommercialCaseRow(Base):
    __tablename__='commercial_case'
    commercial_case_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    case_type: Mapped[str]=mapped_column(String(48),nullable=False,index=True)
    supplier_id: Mapped[str|None]=mapped_column(String(64),index=True)
    property_id: Mapped[str|None]=mapped_column(String(64),index=True)
    priority: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    owner_id: Mapped[str|None]=mapped_column(String(64),index=True)
    state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    sla_due_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
    payload_json: Mapped[dict]=mapped_column(JSON,nullable=False)
    evidence_json: Mapped[list]=mapped_column(JSON,nullable=False)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)

# Mother Plan Production Build 3 — GO Good Hotel Standard governance.
class GoodHotelStandardVersionRow(Base):
    __tablename__='good_hotel_standard_version'
    good_hotel_standard_version_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    version_no: Mapped[int]=mapped_column(Integer,nullable=False,unique=True)
    standard_key: Mapped[str]=mapped_column(String(64),nullable=False,default='GO_GOOD_HOTEL_STANDARD')
    dimensions_json: Mapped[list]=mapped_column(JSON,nullable=False)
    thresholds_json: Mapped[dict]=mapped_column(JSON,nullable=False)
    disqualifiers_json: Mapped[list]=mapped_column(JSON,nullable=False)
    evidence_requirements_json: Mapped[dict]=mapped_column(JSON,nullable=False)
    content_hash: Mapped[str]=mapped_column(String(64),nullable=False,unique=True)
    state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    requested_by: Mapped[str]=mapped_column(String(64),nullable=False)
    approved_by: Mapped[str|None]=mapped_column(String(64))
    effective_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
    retired_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)

class GoodHotelStandardAssessmentRow(Base):
    __tablename__='good_hotel_standard_assessment'
    good_hotel_standard_assessment_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    hotel_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    good_hotel_standard_version_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    evidence_package_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    dimension_result_json: Mapped[dict]=mapped_column(JSON,nullable=False)
    disqualifier_result_json: Mapped[list]=mapped_column(JSON,nullable=False)
    assessment_state: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    reason_codes_json: Mapped[list]=mapped_column(JSON,nullable=False)
    assessed_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)

class GoodHotelStandardGovernanceEventRow(Base):
    __tablename__='good_hotel_standard_governance_event'
    good_hotel_standard_governance_event_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    good_hotel_standard_version_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    event_type: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    payload_json: Mapped[dict]=mapped_column(JSON,nullable=False)
    actor_id: Mapped[str]=mapped_column(String(64),nullable=False)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)

# Mother Plan Production Build 4 — production connector certification and live gate.
class ProductionConnectorRow(Base):
    __tablename__='production_connector_registry'
    connector_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    connector_key: Mapped[str]=mapped_column(String(96),nullable=False,unique=True)
    display_name: Mapped[str]=mapped_column(String(160),nullable=False)
    vertical: Mapped[str]=mapped_column(String(48),nullable=False,index=True)
    supplier_legal_name: Mapped[str]=mapped_column(String(200),nullable=False)
    environment: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    lifecycle_state: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    active_capability_version: Mapped[int]=mapped_column(Integer,nullable=False,default=1)
    created_by: Mapped[str]=mapped_column(String(64),nullable=False)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)

class ConnectorCapabilityMatrixRow(Base):
    __tablename__='connector_capability_matrix'
    capability_matrix_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    connector_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    version_no: Mapped[int]=mapped_column(Integer,nullable=False)
    capabilities_json: Mapped[dict]=mapped_column(JSON,nullable=False)
    content_hash: Mapped[str]=mapped_column(String(64),nullable=False)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
    __table_args__=(UniqueConstraint('connector_id','version_no',name='uq_connector_capability_version'),)

class ConnectorAuthorityRow(Base):
    __tablename__='connector_contract_authority'
    connector_authority_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    connector_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    contract_reference: Mapped[str]=mapped_column(String(256),nullable=False)
    authority_scope_json: Mapped[list]=mapped_column(JSON,nullable=False)
    evidence_json: Mapped[list]=mapped_column(JSON,nullable=False)
    valid_from: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
    valid_to: Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
    state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)

class ConnectorCredentialReferenceRow(Base):
    __tablename__='connector_credential_reference'
    credential_reference_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    connector_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    credential_kind: Mapped[str]=mapped_column(String(48),nullable=False)
    secret_reference: Mapped[str]=mapped_column(String(512),nullable=False)
    key_fingerprint: Mapped[str|None]=mapped_column(String(128))
    expires_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
    state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)

class ConnectorCertificationRunRow(Base):
    __tablename__='connector_certification_run'
    certification_run_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    connector_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    environment: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    suite_version: Mapped[str]=mapped_column(String(64),nullable=False)
    result: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    checks_json: Mapped[dict]=mapped_column(JSON,nullable=False)
    evidence_json: Mapped[list]=mapped_column(JSON,nullable=False)
    evidence_hash: Mapped[str]=mapped_column(String(64),nullable=False)
    executed_by: Mapped[str]=mapped_column(String(64),nullable=False)
    completed_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)

class ConnectorRuntimeHealthRow(Base):
    __tablename__='connector_runtime_health'
    connector_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    health_state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    slo_json: Mapped[dict]=mapped_column(JSON,nullable=False)
    telemetry_binding_json: Mapped[dict]=mapped_column(JSON,nullable=False)
    last_observed_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)

class ConnectorLiveGateAssessmentRow(Base):
    __tablename__='connector_live_gate_assessment'
    live_gate_assessment_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    connector_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    policy_version: Mapped[str]=mapped_column(String(64),nullable=False)
    gate_state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    checks_json: Mapped[dict]=mapped_column(JSON,nullable=False)
    blockers_json: Mapped[list]=mapped_column(JSON,nullable=False)
    evidence_hash: Mapped[str]=mapped_column(String(64),nullable=False)
    assessed_by: Mapped[str]=mapped_column(String(64),nullable=False)
    assessed_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)

class ConnectorActivationChangeRow(Base):
    __tablename__='connector_activation_change'
    activation_change_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    connector_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    target_state: Mapped[str]=mapped_column(String(24),nullable=False)
    live_gate_assessment_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    change_window_json: Mapped[dict]=mapped_column(JSON,nullable=False)
    rollback_plan_json: Mapped[dict]=mapped_column(JSON,nullable=False)
    smoke_test_json: Mapped[dict]=mapped_column(JSON,nullable=False)
    state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    requested_by: Mapped[str]=mapped_column(String(64),nullable=False)
    approved_by: Mapped[str|None]=mapped_column(String(64))
    executed_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)

class ConnectorKillSwitchRow(Base):
    __tablename__='connector_kill_switch'
    connector_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    engaged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=False)
    fallback_mode: Mapped[str]=mapped_column(String(32),nullable=False,default='FAIL_CLOSED')
    reason: Mapped[str|None]=mapped_column(String(512))
    changed_by: Mapped[str]=mapped_column(String(64),nullable=False)
    changed_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)

class ConnectorGovernanceEventRow(Base):
    __tablename__='connector_governance_event'
    connector_governance_event_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    connector_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    event_type: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    payload_json: Mapped[dict]=mapped_column(JSON,nullable=False)
    payload_hash: Mapped[str]=mapped_column(String(64),nullable=False)
    actor_id: Mapped[str]=mapped_column(String(64),nullable=False)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)

# Mother Plan Production Build 5 — connector runtime enforcement.
class ConnectorRuntimeAuthorizationRow(Base):
    __tablename__='connector_runtime_authorization'
    runtime_authorization_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    connector_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    operation_type: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    decision: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    reason_codes_json: Mapped[list]=mapped_column(JSON,nullable=False)
    evidence_hash: Mapped[str]=mapped_column(String(64),nullable=False)
    decided_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)

class ConnectorRuntimeOperationRow(Base):
    __tablename__='connector_runtime_operation'
    runtime_operation_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    connector_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    operation_type: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    idempotency_key: Mapped[str]=mapped_column(String(128),nullable=False)
    request_hash: Mapped[str]=mapped_column(String(64),nullable=False)
    request_json: Mapped[dict]=mapped_column(JSON,nullable=False)
    state: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    external_operation_id: Mapped[str|None]=mapped_column(String(128),index=True)
    response_json: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)
    authorization_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
    __table_args__=(UniqueConstraint('connector_id','idempotency_key',name='uq_connector_runtime_idempotency'),)

class ConnectorWebhookReceiptRow(Base):
    __tablename__='connector_webhook_receipt'
    webhook_receipt_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    connector_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    delivery_id: Mapped[str]=mapped_column(String(128),nullable=False)
    signature_fingerprint: Mapped[str]=mapped_column(String(64),nullable=False)
    payload_hash: Mapped[str]=mapped_column(String(64),nullable=False)
    signature_valid: Mapped[bool]=mapped_column(Boolean,nullable=False)
    replay_rejected: Mapped[bool]=mapped_column(Boolean,nullable=False,default=False)
    state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    received_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
    __table_args__=(UniqueConstraint('connector_id','delivery_id',name='uq_connector_webhook_delivery'),)

class ConnectorRuntimeObservationRow(Base):
    __tablename__='connector_runtime_observation'
    runtime_observation_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    runtime_operation_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    source: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    external_state: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    supplier_reference: Mapped[str|None]=mapped_column(String(128))
    evidence_json: Mapped[dict]=mapped_column(JSON,nullable=False)
    evidence_hash: Mapped[str]=mapped_column(String(64),nullable=False)
    observed_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)

class ConnectorRuntimeReconciliationRow(Base):
    __tablename__='connector_runtime_reconciliation'
    reconciliation_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    runtime_operation_id: Mapped[str]=mapped_column(String(64),nullable=False,unique=True,index=True)
    state: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    attempt_count: Mapped[int]=mapped_column(Integer,nullable=False,default=0)
    max_attempts: Mapped[int]=mapped_column(Integer,nullable=False,default=8)
    next_attempt_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
    manual_review_reason: Mapped[str|None]=mapped_column(String(256))
    claimed_by: Mapped[str|None]=mapped_column(String(64))
    lease_expires_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
    evidence_due_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
    resolution_requested_by: Mapped[str|None]=mapped_column(String(64))
    checker_id: Mapped[str|None]=mapped_column(String(64))
    escalation_level: Mapped[int]=mapped_column(Integer,nullable=False,default=0)
    operator_sla_due_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
    resolution_payload_json: Mapped[dict|None]=mapped_column(JSON)
    resolution_evidence_digest: Mapped[str|None]=mapped_column(String(64))
    checker_evidence_reference: Mapped[str|None]=mapped_column(String(512))
    resolution_result_json: Mapped[dict|None]=mapped_column(JSON)
    resolved_by: Mapped[str|None]=mapped_column(String(64))
    superseded_reason: Mapped[str|None]=mapped_column(String(256))
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)

class ConnectorRuntimeSafetyEventRow(Base):
    __tablename__='connector_runtime_safety_event'
    runtime_safety_event_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    connector_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    event_type: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    severity: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    reason_codes_json: Mapped[list]=mapped_column(JSON,nullable=False)
    evidence_hash: Mapped[str]=mapped_column(String(64),nullable=False)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)

# Mother Plan Production Build 6 — first real connector activation readiness.
class ConnectorOnboardingProfileRow(Base):
    __tablename__='connector_onboarding_profile'
    onboarding_profile_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    connector_id: Mapped[str]=mapped_column(String(64),nullable=False,unique=True,index=True)
    template_key: Mapped[str]=mapped_column(String(64),nullable=False)
    supplier_materials_json: Mapped[dict]=mapped_column(JSON,nullable=False)
    contacts_json: Mapped[list]=mapped_column(JSON,nullable=False)
    state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)

class ConnectorKmsBindingRow(Base):
    __tablename__='connector_kms_binding'
    kms_binding_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    connector_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    provider: Mapped[str]=mapped_column(String(32),nullable=False)
    resource_reference: Mapped[str]=mapped_column(String(512),nullable=False)
    purpose: Mapped[str]=mapped_column(String(48),nullable=False)
    access_test_json: Mapped[dict]=mapped_column(JSON,nullable=False)
    state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)

class ConnectorProductionAccountRow(Base):
    __tablename__='connector_production_account'
    production_account_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    connector_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    supplier_account_reference: Mapped[str]=mapped_column(String(256),nullable=False)
    legal_entity_reference: Mapped[str]=mapped_column(String(256),nullable=False)
    contract_reference: Mapped[str]=mapped_column(String(256),nullable=False)
    authority_scopes_json: Mapped[list]=mapped_column(JSON,nullable=False)
    evidence_json: Mapped[list]=mapped_column(JSON,nullable=False)
    state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    verified_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True))

class ConnectorIpAllowlistRow(Base):
    __tablename__='connector_ip_allowlist'
    ip_allowlist_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    connector_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    direction: Mapped[str]=mapped_column(String(16),nullable=False)
    cidrs_json: Mapped[list]=mapped_column(JSON,nullable=False)
    environment: Mapped[str]=mapped_column(String(24),nullable=False)
    verification_json: Mapped[dict]=mapped_column(JSON,nullable=False)
    state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)

class ConnectorWebhookEndpointRow(Base):
    __tablename__='connector_webhook_endpoint'
    webhook_endpoint_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    connector_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    endpoint_reference: Mapped[str]=mapped_column(String(512),nullable=False)
    signature_scheme: Mapped[str]=mapped_column(String(32),nullable=False)
    active_key_reference: Mapped[str]=mapped_column(String(512),nullable=False)
    previous_key_reference: Mapped[str|None]=mapped_column(String(512))
    certificate_reference: Mapped[str|None]=mapped_column(String(512))
    certificate_expires_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
    rotation_state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    verification_json: Mapped[dict]=mapped_column(JSON,nullable=False)
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)

class ConnectorReadinessCertificationRow(Base):
    __tablename__='connector_readiness_certification'
    readiness_certification_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    connector_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    environment: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    suite_key: Mapped[str]=mapped_column(String(64),nullable=False)
    checks_json: Mapped[dict]=mapped_column(JSON,nullable=False)
    evidence_json: Mapped[list]=mapped_column(JSON,nullable=False)
    result: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    executed_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)

class ConnectorActivationDrillRow(Base):
    __tablename__='connector_activation_drill'
    activation_drill_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    connector_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    drill_type: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    plan_json: Mapped[dict]=mapped_column(JSON,nullable=False)
    result_json: Mapped[dict]=mapped_column(JSON,nullable=False)
    evidence_json: Mapped[list]=mapped_column(JSON,nullable=False)
    result: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    executed_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)

class ConnectorFinancialClosureRow(Base):
    __tablename__='connector_financial_closure'
    financial_closure_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    connector_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    settlement_verified: Mapped[bool]=mapped_column(Boolean,nullable=False)
    refund_verified: Mapped[bool]=mapped_column(Boolean,nullable=False)
    reconciliation_verified: Mapped[bool]=mapped_column(Boolean,nullable=False)
    evidence_json: Mapped[list]=mapped_column(JSON,nullable=False)
    evidence_hash: Mapped[str]=mapped_column(String(64),nullable=False)
    verified_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)

class ConnectorActivationReadinessRow(Base):
    __tablename__='connector_activation_readiness'
    activation_readiness_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    connector_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    readiness_state: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    checks_json: Mapped[dict]=mapped_column(JSON,nullable=False)
    blockers_json: Mapped[list]=mapped_column(JSON,nullable=False)
    evidence_hash: Mapped[str]=mapped_column(String(64),nullable=False)
    assessed_by: Mapped[str]=mapped_column(String(64),nullable=False)
    assessed_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)

# Mother Plan Production Build 7 — paired Hotel + PSP pilot integration.
class ConnectorPilotPairRow(Base):
    __tablename__='connector_pilot_pair'
    pilot_pair_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    hotel_connector_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    psp_connector_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    mode: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    hotel_adapter_key: Mapped[str]=mapped_column(String(96),nullable=False)
    psp_adapter_key: Mapped[str]=mapped_column(String(96),nullable=False)
    state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)

class ConnectorPilotScenarioRow(Base):
    __tablename__='connector_pilot_scenario'
    pilot_scenario_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    pilot_pair_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    scenario_key: Mapped[str]=mapped_column(String(64),nullable=False)
    order_payload_json: Mapped[dict]=mapped_column(JSON,nullable=False)
    expected_flow_json: Mapped[list]=mapped_column(JSON,nullable=False)
    state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)

class ConnectorPilotExecutionRow(Base):
    __tablename__='connector_pilot_execution'
    pilot_execution_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    pilot_scenario_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    mode: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    idempotency_key: Mapped[str]=mapped_column(String(128),nullable=False,unique=True)
    state: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    hotel_order_reference: Mapped[str|None]=mapped_column(String(128))
    payment_reference: Mapped[str|None]=mapped_column(String(128))
    refund_reference: Mapped[str|None]=mapped_column(String(128))
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)

class ConnectorPilotOperationRow(Base):
    __tablename__='connector_pilot_operation'
    pilot_operation_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    pilot_execution_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    vertical: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    operation_type: Mapped[str]=mapped_column(String(48),nullable=False,index=True)
    idempotency_key: Mapped[str]=mapped_column(String(128),nullable=False,unique=True)
    external_reference: Mapped[str|None]=mapped_column(String(128))
    state: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    request_hash: Mapped[str]=mapped_column(String(64),nullable=False)
    result_json: Mapped[dict]=mapped_column(JSON,nullable=False)
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)

class ConnectorPilotCallbackRow(Base):
    __tablename__='connector_pilot_callback'
    pilot_callback_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    pilot_execution_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    source_vertical: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    delivery_id: Mapped[str]=mapped_column(String(128),nullable=False,unique=True)
    event_type: Mapped[str]=mapped_column(String(64),nullable=False)
    signature_verified: Mapped[bool]=mapped_column(Boolean,nullable=False)
    payload_hash: Mapped[str]=mapped_column(String(64),nullable=False)
    received_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)

class ConnectorPilotEvidenceRow(Base):
    __tablename__='connector_pilot_evidence'
    pilot_evidence_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    pilot_execution_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    sequence_no: Mapped[int]=mapped_column(Integer,nullable=False)
    evidence_type: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    payload_json: Mapped[dict]=mapped_column(JSON,nullable=False)
    previous_hash: Mapped[str]=mapped_column(String(64),nullable=False)
    entry_hash: Mapped[str]=mapped_column(String(64),nullable=False,unique=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
    __table_args__=(UniqueConstraint('pilot_execution_id','sequence_no',name='uq_pilot_evidence_sequence'),)

class ConnectorPilotReconciliationRow(Base):
    __tablename__='connector_pilot_reconciliation'
    pilot_reconciliation_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    pilot_execution_id: Mapped[str]=mapped_column(String(64),nullable=False,unique=True,index=True)
    order_state: Mapped[str]=mapped_column(String(32),nullable=False)
    payment_state: Mapped[str]=mapped_column(String(32),nullable=False)
    refund_state: Mapped[str]=mapped_column(String(32),nullable=False)
    settlement_state: Mapped[str]=mapped_column(String(32),nullable=False)
    result: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    blockers_json: Mapped[list]=mapped_column(JSON,nullable=False)
    evidence_hash: Mapped[str]=mapped_column(String(64),nullable=False)
    reconciled_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)

class ConnectorPilotControlRow(Base):
    __tablename__='connector_pilot_control'
    pilot_pair_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    canary_limit: Mapped[int]=mapped_column(Integer,nullable=False,default=1)
    completed_count: Mapped[int]=mapped_column(Integer,nullable=False,default=0)
    kill_switch_engaged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=False)
    rollback_ready: Mapped[bool]=mapped_column(Boolean,nullable=False,default=False)
    smoke_passed: Mapped[bool]=mapped_column(Boolean,nullable=False,default=False)
    state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)

# Mother Plan Production Build 8 — external supplier sandbox certification workbench.
class ExternalSandboxSupplierIntakeRow(Base):
    __tablename__='external_sandbox_supplier_intake'
    supplier_intake_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    pilot_pair_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    hotel_supplier_name: Mapped[str|None]=mapped_column(String(256))
    psp_supplier_name: Mapped[str|None]=mapped_column(String(256))
    contract_reference: Mapped[str|None]=mapped_column(String(512))
    authority_reference: Mapped[str|None]=mapped_column(String(512))
    hotel_sandbox_endpoint: Mapped[str|None]=mapped_column(String(512))
    psp_sandbox_endpoint: Mapped[str|None]=mapped_column(String(512))
    ip_allowlist_reference: Mapped[str|None]=mapped_column(String(512))
    test_hotel_reference: Mapped[str|None]=mapped_column(String(256))
    test_account_reference: Mapped[str|None]=mapped_column(String(256))
    certification_window_start: Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
    certification_window_end: Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
    state: Mapped[str]=mapped_column(String(40),nullable=False,index=True)
    blockers_json: Mapped[list]=mapped_column(JSON,nullable=False)
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)

class ExternalSandboxCredentialBindingRow(Base):
    __tablename__='external_sandbox_credential_binding'
    credential_binding_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    supplier_intake_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    vertical: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    vault_provider: Mapped[str]=mapped_column(String(64),nullable=False)
    secret_reference: Mapped[str]=mapped_column(String(512),nullable=False)
    credential_fingerprint: Mapped[str]=mapped_column(String(64),nullable=False)
    access_test_state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
    __table_args__=(UniqueConstraint('supplier_intake_id','vertical',name='uq_external_sandbox_credential_vertical'),)

class ExternalSandboxCertificationSuiteRow(Base):
    __tablename__='external_sandbox_certification_suite'
    certification_suite_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    supplier_intake_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    suite_version: Mapped[int]=mapped_column(Integer,nullable=False)
    required_scenarios_json: Mapped[list]=mapped_column(JSON,nullable=False)
    state: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)

class ExternalSandboxCertificationRunRow(Base):
    __tablename__='external_sandbox_certification_run'
    certification_run_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    certification_suite_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    execution_mode: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    idempotency_key: Mapped[str]=mapped_column(String(128),nullable=False,unique=True)
    state: Mapped[str]=mapped_column(String(40),nullable=False,index=True)
    scenario_results_json: Mapped[dict]=mapped_column(JSON,nullable=False)
    started_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
    completed_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True))

class ExternalSandboxEvidenceImportRow(Base):
    __tablename__='external_sandbox_evidence_import'
    evidence_import_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    certification_run_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    evidence_type: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    external_reference: Mapped[str]=mapped_column(String(512),nullable=False)
    payload_hash: Mapped[str]=mapped_column(String(64),nullable=False)
    source_attested: Mapped[bool]=mapped_column(Boolean,nullable=False)
    imported_by: Mapped[str]=mapped_column(String(64),nullable=False)
    imported_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)

class ExternalSandboxCallbackProofRow(Base):
    __tablename__='external_sandbox_callback_proof'
    callback_proof_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    certification_run_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    source_vertical: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    delivery_id: Mapped[str]=mapped_column(String(128),nullable=False,unique=True)
    signature_scheme: Mapped[str]=mapped_column(String(64),nullable=False)
    signature_verified: Mapped[bool]=mapped_column(Boolean,nullable=False)
    payload_hash: Mapped[str]=mapped_column(String(64),nullable=False)
    verified_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)

class ExternalSandboxCertificationDecisionRow(Base):
    __tablename__='external_sandbox_certification_decision'
    certification_decision_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    certification_run_id: Mapped[str]=mapped_column(String(64),nullable=False,unique=True,index=True)
    order_verified: Mapped[bool]=mapped_column(Boolean,nullable=False)
    cancellation_verified: Mapped[bool]=mapped_column(Boolean,nullable=False)
    refund_verified: Mapped[bool]=mapped_column(Boolean,nullable=False)
    query_verified: Mapped[bool]=mapped_column(Boolean,nullable=False)
    callbacks_verified: Mapped[bool]=mapped_column(Boolean,nullable=False)
    reconciliation_verified: Mapped[bool]=mapped_column(Boolean,nullable=False)
    decision: Mapped[str]=mapped_column(String(40),nullable=False,index=True)
    blockers_json: Mapped[list]=mapped_column(JSON,nullable=False)
    evidence_hash: Mapped[str]=mapped_column(String(64),nullable=False)
    decided_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)

# Mother Plan Production Build 9 — named supplier adapter and external execution gate.
class NamedSupplierAdapterRow(Base):
    __tablename__='named_supplier_adapter'
    named_adapter_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    supplier_intake_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    vertical: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    supplier_name: Mapped[str]=mapped_column(String(256),nullable=False)
    adapter_key: Mapped[str]=mapped_column(String(128),nullable=False,unique=True)
    adapter_version: Mapped[int]=mapped_column(Integer,nullable=False)
    capability_manifest_json: Mapped[list]=mapped_column(JSON,nullable=False)
    implementation_reference: Mapped[str]=mapped_column(String(512),nullable=False)
    state: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)

class NamedSupplierAdapterBindingRow(Base):
    __tablename__='named_supplier_adapter_binding'
    adapter_binding_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    named_adapter_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    endpoint_reference: Mapped[str]=mapped_column(String(512),nullable=False)
    credential_binding_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    allowlist_reference: Mapped[str]=mapped_column(String(512),nullable=False)
    test_resource_reference: Mapped[str]=mapped_column(String(256),nullable=False)
    configuration_attested: Mapped[bool]=mapped_column(Boolean,nullable=False)
    state: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)

class ExternalSandboxExecutionAuthorizationRow(Base):
    __tablename__='external_sandbox_execution_authorization'
    execution_authorization_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    certification_suite_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    hotel_adapter_binding_id: Mapped[str]=mapped_column(String(64),nullable=False)
    psp_adapter_binding_id: Mapped[str]=mapped_column(String(64),nullable=False)
    maker_id: Mapped[str]=mapped_column(String(64),nullable=False)
    checker_id: Mapped[str|None]=mapped_column(String(64))
    evidence_reference: Mapped[str|None]=mapped_column(String(512))
    state: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    approved_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)

class ExternalSandboxExecutionAttemptRow(Base):
    __tablename__='external_sandbox_execution_attempt'
    execution_attempt_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    execution_authorization_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    idempotency_key: Mapped[str]=mapped_column(String(128),nullable=False,unique=True)
    state: Mapped[str]=mapped_column(String(40),nullable=False,index=True)
    blocker_code: Mapped[str|None]=mapped_column(String(128))
    transport_invoked: Mapped[bool]=mapped_column(Boolean,nullable=False)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)

class ExternalSandboxTransportEvidenceRow(Base):
    __tablename__='external_sandbox_transport_evidence'
    transport_evidence_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    execution_attempt_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    operation_type: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    supplier_reference: Mapped[str]=mapped_column(String(256),nullable=False)
    request_hash: Mapped[str]=mapped_column(String(64),nullable=False)
    response_hash: Mapped[str]=mapped_column(String(64),nullable=False)
    source_attested: Mapped[bool]=mapped_column(Boolean,nullable=False)
    recorded_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)

class ExternalSandboxExecutionDecisionRow(Base):
    __tablename__='external_sandbox_execution_decision'
    execution_decision_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    execution_attempt_id: Mapped[str]=mapped_column(String(64),nullable=False,unique=True,index=True)
    required_operations_json: Mapped[list]=mapped_column(JSON,nullable=False)
    observed_operations_json: Mapped[list]=mapped_column(JSON,nullable=False)
    decision: Mapped[str]=mapped_column(String(48),nullable=False,index=True)
    blockers_json: Mapped[list]=mapped_column(JSON,nullable=False)
    evidence_hash: Mapped[str]=mapped_column(String(64),nullable=False)
    decided_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)

# Production Build 10 — GO-hosted hotel direct-booking pilot (no simulated payment).
class HostedDirectHotelRow(Base):
    __tablename__='hosted_direct_hotel'
    hosted_hotel_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    supplier_name: Mapped[str]=mapped_column(String(256),nullable=False)
    page_slug: Mapped[str]=mapped_column(String(128),nullable=False,unique=True,index=True)
    city: Mapped[str]=mapped_column(String(128),nullable=False)
    contact_json: Mapped[dict]=mapped_column(JSON,nullable=False)
    state: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)

class HostedDirectRoomOfferRow(Base):
    __tablename__='hosted_direct_room_offer'
    hosted_offer_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    hosted_hotel_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    room_name: Mapped[str]=mapped_column(String(256),nullable=False)
    rate_name: Mapped[str]=mapped_column(String(256),nullable=False)
    price_minor: Mapped[int]=mapped_column(Integer,nullable=False)
    currency: Mapped[str]=mapped_column(String(8),nullable=False)
    inventory: Mapped[int]=mapped_column(Integer,nullable=False)
    cancellation_policy: Mapped[str]=mapped_column(String(512),nullable=False)
    state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)

class HostedDirectReservationRow(Base):
    __tablename__='hosted_direct_reservation'
    hosted_reservation_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    hosted_offer_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    idempotency_key: Mapped[str]=mapped_column(String(128),nullable=False,unique=True)
    guest_name: Mapped[str]=mapped_column(String(128),nullable=False)
    guest_contact: Mapped[str]=mapped_column(String(256),nullable=False)
    check_in: Mapped[str]=mapped_column(String(10),nullable=False)
    check_out: Mapped[str]=mapped_column(String(10),nullable=False)
    amount_minor: Mapped[int]=mapped_column(Integer,nullable=False)
    currency: Mapped[str]=mapped_column(String(8),nullable=False)
    reservation_state: Mapped[str]=mapped_column(String(40),nullable=False,index=True)
    payment_state: Mapped[str]=mapped_column(String(40),nullable=False,index=True)
    hotel_confirmation_reference: Mapped[str|None]=mapped_column(String(128))
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)

class HostedDirectReservationEventRow(Base):
    __tablename__='hosted_direct_reservation_event'
    hosted_event_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    hosted_reservation_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    event_type: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    actor_id: Mapped[str]=mapped_column(String(64),nullable=False)
    payload_json: Mapped[dict]=mapped_column(JSON,nullable=False)
    occurred_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)

class HostedDirectPaymentReadinessRow(Base):
    __tablename__='hosted_direct_payment_readiness'
    hosted_hotel_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    provider: Mapped[str]=mapped_column(String(32),nullable=False)
    merchant_account_name: Mapped[str]=mapped_column(String(256),nullable=False)
    application_state: Mapped[str]=mapped_column(String(40),nullable=False,index=True)
    sandbox_app_id_reference: Mapped[str|None]=mapped_column(String(256))
    kms_reference: Mapped[str|None]=mapped_column(String(512))
    blockers_json: Mapped[list]=mapped_column(JSON,nullable=False)
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)

class HostedDirectInventoryPoolRow(Base):
    __tablename__='hosted_direct_inventory_pool'
    inventory_pool_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    hosted_hotel_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    physical_room_key: Mapped[str]=mapped_column(String(128),nullable=False)
    physical_room_name: Mapped[str]=mapped_column(String(256),nullable=False)
    room_details_json: Mapped[dict]=mapped_column(JSON,nullable=False)
    capacity_total: Mapped[int]=mapped_column(Integer,nullable=False)
    capacity_available: Mapped[int]=mapped_column(Integer,nullable=False)
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
    __table_args__=(UniqueConstraint('hosted_hotel_id','physical_room_key',name='uq_hosted_physical_room_pool'),)
class HostedDirectRateVariantRow(Base):
    __tablename__='hosted_direct_rate_variant'
    rate_variant_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    inventory_pool_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    hosted_offer_id: Mapped[str]=mapped_column(String(64),nullable=False,unique=True,index=True)
    breakfast_count: Mapped[int]=mapped_column(Integer,nullable=False)
    benefits_json: Mapped[list]=mapped_column(JSON,nullable=False)
    payment_mode: Mapped[str]=mapped_column(String(32),nullable=False)
    state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)

class HostedContentSnapshotRow(Base):
    __tablename__='hosted_content_snapshot'
    content_snapshot_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    hosted_hotel_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    version: Mapped[int]=mapped_column(Integer,nullable=False)
    content_json: Mapped[dict]=mapped_column(JSON,nullable=False)
    content_hash: Mapped[str]=mapped_column(String(64),nullable=False)
    source_status: Mapped[str]=mapped_column(String(48),nullable=False,index=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
class HostedContentApprovalRow(Base):
    __tablename__='hosted_content_approval'
    content_approval_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    content_snapshot_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    approver_id: Mapped[str]=mapped_column(String(64),nullable=False)
    approver_role: Mapped[str]=mapped_column(String(32),nullable=False)
    decision: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    evidence_reference: Mapped[str]=mapped_column(String(512),nullable=False)
    decided_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
class HostedMediaAssetRow(Base):
    __tablename__='hosted_media_asset'
    media_asset_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    hosted_hotel_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    asset_role: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    physical_room_key: Mapped[str|None]=mapped_column(String(128),index=True)
    storage_reference: Mapped[str]=mapped_column(String(512),nullable=False)
    rights_owner: Mapped[str]=mapped_column(String(256),nullable=False)
    rights_evidence_reference: Mapped[str]=mapped_column(String(512),nullable=False)
    state: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)

# Production Build 10.4 — dated ARI and reservation operations hardening.
class HostedInventoryDayRow(Base):
    __tablename__='hosted_inventory_day'
    inventory_day_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    inventory_pool_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    stay_date: Mapped[str]=mapped_column(String(10),nullable=False,index=True)
    capacity_total: Mapped[int]=mapped_column(Integer,nullable=False)
    capacity_available: Mapped[int]=mapped_column(Integer,nullable=False)
    sale_state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
    __table_args__=(UniqueConstraint('inventory_pool_id','stay_date',name='uq_hosted_inventory_pool_day'),)
class HostedRateCalendarDayRow(Base):
    __tablename__='hosted_rate_calendar_day'
    rate_calendar_day_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    rate_variant_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    stay_date: Mapped[str]=mapped_column(String(10),nullable=False,index=True)
    price_minor: Mapped[int]=mapped_column(Integer,nullable=False)
    sale_state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    min_stay: Mapped[int]=mapped_column(Integer,nullable=False)
    max_stay: Mapped[int]=mapped_column(Integer,nullable=False)
    advance_min_days: Mapped[int]=mapped_column(Integer,nullable=False)
    advance_max_days: Mapped[int]=mapped_column(Integer,nullable=False)
    max_adults: Mapped[int]=mapped_column(Integer,nullable=False)
    max_children: Mapped[int]=mapped_column(Integer,nullable=False)
    extra_bed_allowed: Mapped[bool]=mapped_column(Boolean,nullable=False)
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
    __table_args__=(UniqueConstraint('rate_variant_id','stay_date',name='uq_hosted_rate_variant_day'),)
class HostedReservationStayRow(Base):
    __tablename__='hosted_reservation_stay'
    hosted_reservation_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    source: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    adults: Mapped[int]=mapped_column(Integer,nullable=False)
    children: Mapped[int]=mapped_column(Integer,nullable=False)
    extra_beds: Mapped[int]=mapped_column(Integer,nullable=False)
    operational_state: Mapped[str]=mapped_column(String(40),nullable=False,index=True)
    confirmation_expires_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    created_by: Mapped[str]=mapped_column(String(64),nullable=False)
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
class HostedReservationNightRow(Base):
    __tablename__='hosted_reservation_night'
    reservation_night_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    hosted_reservation_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    inventory_day_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    stay_date: Mapped[str]=mapped_column(String(10),nullable=False,index=True)
    price_minor: Mapped[int]=mapped_column(Integer,nullable=False)
    state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    __table_args__=(UniqueConstraint('hosted_reservation_id','stay_date',name='uq_hosted_reservation_night'),)
class HostedReservationNotificationRow(Base):
    __tablename__='hosted_reservation_notification'
    notification_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    hosted_reservation_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    recipient_type: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    channel: Mapped[str]=mapped_column(String(24),nullable=False)
    template_key: Mapped[str]=mapped_column(String(64),nullable=False)
    delivery_state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    payload_json: Mapped[dict]=mapped_column(JSON,nullable=False)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)

# Production Build 10.5 — front-desk UAT, governed operations and daily close.
class HostedStaffRoleRow(Base):
    __tablename__='hosted_staff_role'
    staff_role_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    hosted_hotel_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    staff_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    role: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    evidence_reference: Mapped[str]=mapped_column(String(512),nullable=False)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
    __table_args__=(UniqueConstraint('hosted_hotel_id','staff_id','role',name='uq_hosted_staff_role'),)
class HostedShiftHandoverRow(Base):
    __tablename__='hosted_shift_handover'
    handover_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    hosted_hotel_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    outgoing_staff_id: Mapped[str]=mapped_column(String(64),nullable=False)
    incoming_staff_id: Mapped[str]=mapped_column(String(64),nullable=False)
    unresolved_reservation_ids_json: Mapped[list]=mapped_column(JSON,nullable=False)
    notes: Mapped[str]=mapped_column(String(1024),nullable=False)
    state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    accepted_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
class HostedSlaEscalationRow(Base):
    __tablename__='hosted_sla_escalation'
    escalation_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    hosted_reservation_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    escalation_level: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    manager_staff_id: Mapped[str]=mapped_column(String(64),nullable=False)
    state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    reason: Mapped[str]=mapped_column(String(512),nullable=False)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
class HostedActionApprovalRow(Base):
    __tablename__='hosted_action_approval'
    action_approval_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    hosted_reservation_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    action_type: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    action_payload_json: Mapped[dict]=mapped_column(JSON,nullable=False)
    requester_id: Mapped[str]=mapped_column(String(64),nullable=False)
    checker_id: Mapped[str|None]=mapped_column(String(64))
    evidence_reference: Mapped[str|None]=mapped_column(String(512))
    state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
class HostedDailyCloseRow(Base):
    __tablename__='hosted_daily_close'
    daily_close_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    hosted_hotel_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    business_date: Mapped[str]=mapped_column(String(10),nullable=False,index=True)
    inventory_snapshot_json: Mapped[dict]=mapped_column(JSON,nullable=False)
    reservation_summary_json: Mapped[dict]=mapped_column(JSON,nullable=False)
    exception_summary_json: Mapped[dict]=mapped_column(JSON,nullable=False)
    closed_by: Mapped[str]=mapped_column(String(64),nullable=False)
    evidence_hash: Mapped[str]=mapped_column(String(64),nullable=False)
    closed_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
    __table_args__=(UniqueConstraint('hosted_hotel_id','business_date',name='uq_hosted_daily_close'),)
class HostedUatScenarioRow(Base):
    __tablename__='hosted_uat_scenario'
    uat_scenario_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    hosted_hotel_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    scenario_key: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    result: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    evidence_reference: Mapped[str]=mapped_column(String(512),nullable=False)
    signed_by: Mapped[str]=mapped_column(String(64),nullable=False)
    executed_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
class HostedGuestAccessAuditRow(Base):
    __tablename__='hosted_guest_access_audit'
    guest_access_audit_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    hosted_reservation_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    staff_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    access_mode: Mapped[str]=mapped_column(String(24),nullable=False)
    reason: Mapped[str]=mapped_column(String(512),nullable=False)
    occurred_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)

# Production Build 11 — Alipay authorization and safeguarded-settlement contract.
class AlipayMerchantBindingRow(Base):
    __tablename__='alipay_merchant_binding'
    merchant_binding_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    hosted_hotel_id: Mapped[str]=mapped_column(String(64),nullable=False,unique=True,index=True)
    merchant_account_name: Mapped[str]=mapped_column(String(256),nullable=False)
    account_attestation_state: Mapped[str]=mapped_column(String(40),nullable=False,index=True)
    app_id_reference: Mapped[str|None]=mapped_column(String(256))
    product_contract_reference: Mapped[str|None]=mapped_column(String(512))
    state: Mapped[str]=mapped_column(String(40),nullable=False,index=True)
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
class AlipayCredentialBindingRow(Base):
    __tablename__='alipay_credential_binding'
    credential_binding_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    merchant_binding_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    app_public_key_reference: Mapped[str]=mapped_column(String(512),nullable=False)
    alipay_public_key_reference: Mapped[str]=mapped_column(String(512),nullable=False)
    kms_private_key_reference: Mapped[str]=mapped_column(String(512),nullable=False)
    certificate_mode: Mapped[bool]=mapped_column(Boolean,nullable=False)
    state: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
class AlipayAuthorizationRow(Base):
    __tablename__='alipay_authorization'
    authorization_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    hosted_reservation_id: Mapped[str]=mapped_column(String(64),nullable=False,unique=True,index=True)
    amount_minor: Mapped[int]=mapped_column(Integer,nullable=False)
    currency: Mapped[str]=mapped_column(String(8),nullable=False)
    state: Mapped[str]=mapped_column(String(48),nullable=False,index=True)
    external_invoked: Mapped[bool]=mapped_column(Boolean,nullable=False)
    external_authorization_reference: Mapped[str|None]=mapped_column(String(256))
    settlement_eligible: Mapped[bool]=mapped_column(Boolean,nullable=False)
    idempotency_key: Mapped[str]=mapped_column(String(128),nullable=False,unique=True)
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
class AlipaySafeguardedEventRow(Base):
    __tablename__='alipay_safeguarded_event'
    safeguarded_event_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    authorization_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    event_type: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    source: Mapped[str]=mapped_column(String(32),nullable=False)
    external_event_id: Mapped[str|None]=mapped_column(String(256),unique=True)
    payload_hash: Mapped[str]=mapped_column(String(64),nullable=False)
    signature_verified: Mapped[bool]=mapped_column(Boolean,nullable=False)
    external_invoked: Mapped[bool]=mapped_column(Boolean,nullable=False)
    occurred_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
class AlipayAdjustmentApprovalRow(Base):
    __tablename__='alipay_adjustment_approval'
    adjustment_approval_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    authorization_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    adjustment_type: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    amount_minor: Mapped[int]=mapped_column(Integer,nullable=False)
    requester_id: Mapped[str]=mapped_column(String(64),nullable=False)
    checker_id: Mapped[str|None]=mapped_column(String(64))
    evidence_reference: Mapped[str|None]=mapped_column(String(512))
    state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
class AlipayReconciliationRow(Base):
    __tablename__='alipay_reconciliation'
    reconciliation_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    authorization_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    authorization_state: Mapped[str]=mapped_column(String(48),nullable=False)
    payment_amount_minor: Mapped[int]=mapped_column(Integer,nullable=False)
    refund_amount_minor: Mapped[int]=mapped_column(Integer,nullable=False)
    settlement_amount_minor: Mapped[int]=mapped_column(Integer,nullable=False)
    decision: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    evidence_hash: Mapped[str]=mapped_column(String(64),nullable=False)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)

# Production Build 12 — guest stay lifecycle and settlement eligibility evidence.
class GuestStayLifecycleRow(Base):
    __tablename__='guest_stay_lifecycle'
    stay_lifecycle_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    hosted_reservation_id: Mapped[str]=mapped_column(String(64),nullable=False,unique=True,index=True)
    state: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    assigned_room_reference: Mapped[str|None]=mapped_column(String(128))
    planned_check_out: Mapped[str]=mapped_column(String(10),nullable=False)
    actual_check_in_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
    actual_check_out_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
class GuestIdentityEvidenceRow(Base):
    __tablename__='guest_identity_evidence'
    identity_evidence_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    stay_lifecycle_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    evidence_hash: Mapped[str]=mapped_column(String(64),nullable=False)
    verification_method: Mapped[str]=mapped_column(String(32),nullable=False)
    verified_by: Mapped[str]=mapped_column(String(64),nullable=False)
    state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    verified_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
class GuestStayEventRow(Base):
    __tablename__='guest_stay_event'
    stay_event_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    stay_lifecycle_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    event_type: Mapped[str]=mapped_column(String(48),nullable=False,index=True)
    actor_id: Mapped[str]=mapped_column(String(64),nullable=False)
    payload_json: Mapped[dict]=mapped_column(JSON,nullable=False)
    evidence_hash: Mapped[str]=mapped_column(String(64),nullable=False)
    occurred_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
class StayFulfillmentEvidenceRow(Base):
    __tablename__='stay_fulfillment_evidence'
    fulfillment_evidence_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    stay_lifecycle_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    hotel_evidence_reference: Mapped[str]=mapped_column(String(512),nullable=False)
    guest_checkout_reference: Mapped[str]=mapped_column(String(512),nullable=False)
    fulfilled_amount_minor: Mapped[int]=mapped_column(Integer,nullable=False)
    state: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    confirmed_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
class StayDisputeRow(Base):
    __tablename__='stay_dispute'
    stay_dispute_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    stay_lifecycle_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    dispute_type: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    description: Mapped[str]=mapped_column(String(1024),nullable=False)
    evidence_reference: Mapped[str]=mapped_column(String(512),nullable=False)
    state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    opened_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
class SettlementEligibilityDecisionRow(Base):
    __tablename__='settlement_eligibility_decision'
    settlement_eligibility_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    stay_lifecycle_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    decision: Mapped[str]=mapped_column(String(40),nullable=False,index=True)
    eligible_amount_minor: Mapped[int]=mapped_column(Integer,nullable=False)
    blockers_json: Mapped[list]=mapped_column(JSON,nullable=False)
    evidence_hash: Mapped[str]=mapped_column(String(64),nullable=False)
    external_payment_invoked: Mapped[bool]=mapped_column(Boolean,nullable=False)
    decided_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)

# Production Build 13 — post-stay dispute, refund eligibility and reconciliation.
class PostStayDisputeCaseRow(Base):
    __tablename__='post_stay_dispute_case'
    dispute_case_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    stay_lifecycle_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    opened_by_party: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    dispute_type: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    assigned_to: Mapped[str]=mapped_column(String(64),nullable=False)
    state: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    response_due_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
    evidence_due_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
    closure_hash: Mapped[str|None]=mapped_column(String(64))
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
class PostStayDisputeEvidenceRow(Base):
    __tablename__='post_stay_dispute_evidence'
    dispute_evidence_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    dispute_case_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    submitted_by_party: Mapped[str]=mapped_column(String(24),nullable=False)
    evidence_type: Mapped[str]=mapped_column(String(24),nullable=False)
    storage_reference: Mapped[str]=mapped_column(String(512),nullable=False)
    content_hash: Mapped[str]=mapped_column(String(64),nullable=False)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
class PostStayDisputeCommunicationRow(Base):
    __tablename__='post_stay_dispute_communication'
    communication_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    dispute_case_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    party: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    message_reference: Mapped[str]=mapped_column(String(512),nullable=False)
    message_hash: Mapped[str]=mapped_column(String(64),nullable=False)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
class PostStayMediationRow(Base):
    __tablename__='post_stay_mediation'
    mediation_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    dispute_case_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    recommendation: Mapped[str]=mapped_column(String(32),nullable=False)
    recommended_refund_minor: Mapped[int]=mapped_column(Integer,nullable=False)
    rationale_reference: Mapped[str]=mapped_column(String(512),nullable=False)
    created_by: Mapped[str]=mapped_column(String(64),nullable=False)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
class PostStayDecisionRow(Base):
    __tablename__='post_stay_decision'
    post_stay_decision_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    dispute_case_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    outcome: Mapped[str]=mapped_column(String(32),nullable=False)
    refund_amount_minor: Mapped[int]=mapped_column(Integer,nullable=False)
    requester_id: Mapped[str]=mapped_column(String(64),nullable=False)
    checker_id: Mapped[str|None]=mapped_column(String(64))
    evidence_reference: Mapped[str|None]=mapped_column(String(512))
    state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
class RefundEligibilityRow(Base):
    __tablename__='refund_eligibility'
    refund_eligibility_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    post_stay_decision_id: Mapped[str]=mapped_column(String(64),nullable=False,unique=True,index=True)
    decision: Mapped[str]=mapped_column(String(48),nullable=False,index=True)
    eligible_amount_minor: Mapped[int]=mapped_column(Integer,nullable=False)
    original_payment_reference: Mapped[str|None]=mapped_column(String(256))
    external_refund_invoked: Mapped[bool]=mapped_column(Boolean,nullable=False)
    blockers_json: Mapped[list]=mapped_column(JSON,nullable=False)
    evidence_hash: Mapped[str]=mapped_column(String(64),nullable=False)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
class PostStayReconciliationRow(Base):
    __tablename__='post_stay_reconciliation'
    post_stay_reconciliation_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    dispute_case_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    settlement_eligible_minor: Mapped[int]=mapped_column(Integer,nullable=False)
    refund_eligible_minor: Mapped[int]=mapped_column(Integer,nullable=False)
    cancellation_fee_minor: Mapped[int]=mapped_column(Integer,nullable=False)
    no_show_fee_minor: Mapped[int]=mapped_column(Integer,nullable=False)
    decision: Mapped[str]=mapped_column(String(40),nullable=False,index=True)
    blockers_json: Mapped[list]=mapped_column(JSON,nullable=False)
    evidence_hash: Mapped[str]=mapped_column(String(64),nullable=False)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)

# Mother Plan P0 Product Compliance Patch — Flight Check-in, Flight-linked Ride Sync and GO Offer Builder.
class FlightCheckInStateRow(Base):
    __tablename__='flight_check_in_state'
    flight_check_in_state_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    flight_order_id: Mapped[str]=mapped_column(String(64),nullable=False,unique=True,index=True)
    state: Mapped[str]=mapped_column(String(40),nullable=False,index=True)
    check_in_opens_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
    official_check_in_url: Mapped[str|None]=mapped_column(String(1024))
    boarding_pass_reference: Mapped[str|None]=mapped_column(String(1024))
    source_type: Mapped[str]=mapped_column(String(32),nullable=False)
    source_authority_reference: Mapped[str|None]=mapped_column(String(512))
    source_fact_hash: Mapped[str|None]=mapped_column(String(64))
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
class FlightCheckInEventRow(Base):
    __tablename__='flight_check_in_event'
    flight_check_in_event_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    flight_order_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    previous_state: Mapped[str|None]=mapped_column(String(40))
    current_state: Mapped[str]=mapped_column(String(40),nullable=False,index=True)
    payload_hash: Mapped[str]=mapped_column(String(64),nullable=False)
    source_type: Mapped[str]=mapped_column(String(32),nullable=False)
    source_authority_reference: Mapped[str|None]=mapped_column(String(512))
    occurred_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
class RideFlightTrackingBindingRow(Base):
    __tablename__='ride_flight_tracking_binding'
    ride_flight_tracking_binding_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    ride_order_id: Mapped[str]=mapped_column(String(64),nullable=False,unique=True,index=True)
    flight_no: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    tracking_enabled: Mapped[bool]=mapped_column(Boolean,nullable=False)
    original_pickup_at: Mapped[str]=mapped_column(String(48),nullable=False)
    current_pickup_at: Mapped[str]=mapped_column(String(48),nullable=False)
    included_wait_minutes: Mapped[int]=mapped_column(Integer,nullable=False)
    delay_protection_enabled: Mapped[bool]=mapped_column(Boolean,nullable=False)
    delay_protection_free_wait_minutes: Mapped[int]=mapped_column(Integer,nullable=False)
    max_free_wait_minutes: Mapped[int]=mapped_column(Integer,nullable=False)
    supplier_rule_snapshot_json: Mapped[dict]=mapped_column(JSON,nullable=False)
    sync_state: Mapped[str]=mapped_column(String(40),nullable=False,index=True)
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
class RideFlightSyncEventRow(Base):
    __tablename__='ride_flight_sync_event'
    ride_flight_sync_event_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    ride_order_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    flight_event_type: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    verified_flight_time: Mapped[str]=mapped_column(String(48),nullable=False)
    previous_pickup_at: Mapped[str]=mapped_column(String(48),nullable=False)
    adjusted_pickup_at: Mapped[str]=mapped_column(String(48),nullable=False)
    free_wait_minutes: Mapped[int]=mapped_column(Integer,nullable=False)
    external_mutation_invoked: Mapped[bool]=mapped_column(Boolean,nullable=False)
    external_confirmation_state: Mapped[str]=mapped_column(String(40),nullable=False,index=True)
    source_authority_reference: Mapped[str]=mapped_column(String(512),nullable=False)
    idempotency_key: Mapped[str]=mapped_column(String(128),nullable=False,unique=True)
    evidence_hash: Mapped[str]=mapped_column(String(64),nullable=False)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
class GoOfferRequirementRow(Base):
    __tablename__='go_offer_requirement'
    go_offer_requirement_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    account_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    property_id: Mapped[str|None]=mapped_column(String(64),index=True)
    requirement_type: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    structured_requirement_json: Mapped[dict]=mapped_column(JSON,nullable=False)
    quote_mode: Mapped[str|None]=mapped_column(String(32),index=True)
    state: Mapped[str]=mapped_column(String(40),nullable=False,index=True)
    microphone_input_allowed: Mapped[bool]=mapped_column(Boolean,nullable=False)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
class GoOfferQuoteRow(Base):
    __tablename__='go_offer_quote'
    go_offer_quote_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    go_offer_requirement_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    property_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    quote_mode: Mapped[str]=mapped_column(String(32),nullable=False)
    amount_minor: Mapped[int|None]=mapped_column(Integer)
    currency: Mapped[str]=mapped_column(String(8),nullable=False)
    package_json: Mapped[dict]=mapped_column(JSON,nullable=False)
    conditions_json: Mapped[dict]=mapped_column(JSON,nullable=False)
    expires_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
    state: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    source_scope: Mapped[str]=mapped_column(String(40),nullable=False)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)

# Mother Plan Phase 1 — Member / Staff / Friends & Family / Owner identity entitlements.
class GoIdentityCredentialRow(Base):
    __tablename__='go_identity_credential'
    credential_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    account_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    credential_type: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    subject_supplier_id: Mapped[str|None]=mapped_column(String(64),index=True)
    state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    selected_privilege: Mapped[str|None]=mapped_column(String(32))
    review_due_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True),index=True)
    expires_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True),index=True)
    revocation_reason: Mapped[str|None]=mapped_column(String(128))
    rule_version: Mapped[str]=mapped_column(String(32),nullable=False)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)

class GoIdentityEvidenceRow(Base):
    __tablename__='go_identity_evidence'
    evidence_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    credential_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    evidence_type: Mapped[str]=mapped_column(String(40),nullable=False,index=True)
    source_type: Mapped[str]=mapped_column(String(40),nullable=False)
    source_reference: Mapped[str]=mapped_column(String(512),nullable=False)
    subject_match: Mapped[bool]=mapped_column(Boolean,nullable=False)
    confidence_bps: Mapped[int]=mapped_column(Integer,nullable=False)
    valid_until: Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
    evidence_hash: Mapped[str]=mapped_column(String(64),nullable=False,unique=True)
    received_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)

class GoIdentityEventRow(Base):
    __tablename__='go_identity_event'
    event_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    credential_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    event_type: Mapped[str]=mapped_column(String(48),nullable=False,index=True)
    previous_state: Mapped[str|None]=mapped_column(String(24))
    current_state: Mapped[str]=mapped_column(String(24),nullable=False)
    actor_id: Mapped[str]=mapped_column(String(64),nullable=False)
    evidence_hash: Mapped[str]=mapped_column(String(64),nullable=False)
    payload_json: Mapped[dict]=mapped_column(JSON,nullable=False)
    occurred_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)

class GoIdentitySupplierProgramRow(Base):
    __tablename__='go_identity_supplier_program'
    supplier_program_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    supplier_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    program_type: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    enabled: Mapped[bool]=mapped_column(Boolean,nullable=False)
    eligible_room_ids_json: Mapped[list]=mapped_column(JSON,nullable=False)
    open_date_ranges_json: Mapped[list]=mapped_column(JSON,nullable=False)
    inventory_limit: Mapped[int|None]=mapped_column(Integer)
    benefits_json: Mapped[list]=mapped_column(JSON,nullable=False)
    authorization_reference: Mapped[str]=mapped_column(String(512),nullable=False)
    rule_version: Mapped[str]=mapped_column(String(32),nullable=False)
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)

class GoFriendsFamilyInvitationRow(Base):
    __tablename__='go_friends_family_invitation'
    invitation_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    staff_credential_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    invitee_account_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    invitee_name_hash: Mapped[str]=mapped_column(String(64),nullable=False)
    state: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    annual_usage_limit: Mapped[int]=mapped_column(Integer,nullable=False)
    used_count: Mapped[int]=mapped_column(Integer,nullable=False)
    transferable: Mapped[bool]=mapped_column(Boolean,nullable=False)
    expires_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)

class GoOfferPrebookRow(Base):
    __tablename__='go_offer_prebook'
    go_offer_prebook_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    requirement_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    quote_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    account_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    state: Mapped[str]=mapped_column(String(48),nullable=False,index=True)
    quoted_amount_minor: Mapped[int]=mapped_column(Integer,nullable=False)
    revalidated_amount_minor: Mapped[int|None]=mapped_column(Integer)
    currency: Mapped[str]=mapped_column(String(8),nullable=False)
    quote_snapshot_hash: Mapped[str]=mapped_column(String(64),nullable=False)
    revalidation_evidence_hash: Mapped[str|None]=mapped_column(String(64))
    supplier_confirmation_reference: Mapped[str|None]=mapped_column(String(512))
    idempotency_key: Mapped[str]=mapped_column(String(128),nullable=False,unique=True)
    expires_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True),index=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)

class GoOfferOrderHandoffRow(Base):
    __tablename__='go_offer_order_handoff'
    go_offer_order_handoff_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    go_offer_prebook_id: Mapped[str]=mapped_column(String(64),nullable=False,unique=True,index=True)
    account_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    state: Mapped[str]=mapped_column(String(40),nullable=False,index=True)
    downstream_order_id: Mapped[str|None]=mapped_column(String(64),index=True)
    checkout_payload_json: Mapped[dict]=mapped_column(JSON,nullable=False)
    idempotency_key: Mapped[str]=mapped_column(String(128),nullable=False,unique=True)
    evidence_hash: Mapped[str]=mapped_column(String(64),nullable=False)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)

class GoOfferLifecycleEventRow(Base):
    __tablename__='go_offer_lifecycle_event'
    go_offer_lifecycle_event_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    requirement_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    event_type: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    actor_id: Mapped[str]=mapped_column(String(64),nullable=False)
    payload_json: Mapped[dict]=mapped_column(JSON,nullable=False)
    evidence_hash: Mapped[str]=mapped_column(String(64),nullable=False)
    occurred_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)


# P0 remediation 0097 — persisted Direct First source decisions.
class VerticalSourceDecisionRow(Base):
    __tablename__='vertical_source_decision'
    vertical_source_decision_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    vertical: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    business_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    selected_source_id: Mapped[str|None]=mapped_column(String(64),index=True)
    selected_source_type: Mapped[str|None]=mapped_column(String(48),index=True)
    route: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    authority_reference: Mapped[str|None]=mapped_column(String(512))
    evidence_reference: Mapped[str|None]=mapped_column(String(512))
    candidate_snapshot_json: Mapped[list]=mapped_column(JSON,nullable=False)
    reason_codes_json: Mapped[list]=mapped_column(JSON,nullable=False)
    decision_hash: Mapped[str]=mapped_column(String(64),nullable=False,unique=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)

# P0 remediation 0098 — server-resolved payment truth and scoped financial close.
class PaymentOrderFactBindingRow(Base):
    __tablename__='payment_order_fact_binding'
    payment_order_fact_binding_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    payment_intent_id: Mapped[str]=mapped_column(String(64),nullable=False,unique=True,index=True)
    business_type: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    business_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    payer_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    payee_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    amount_minor: Mapped[int]=mapped_column(BigInteger,nullable=False)
    currency: Mapped[str]=mapped_column(String(3),nullable=False)
    legal_entity_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True,default='GO_CN')
    source_decision_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    request_fingerprint: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    order_fact_hash: Mapped[str]=mapped_column(String(64),nullable=False)
    evidence_reference: Mapped[str]=mapped_column(String(512),nullable=False)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
    __table_args__=(UniqueConstraint('business_type','business_id','request_fingerprint',name='uq_payment_order_fact_request'),)

class FinanceScopedCloseBatchRow(Base):
    __tablename__='finance_scoped_close_batch'
    finance_scoped_close_batch_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    legal_entity_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    currency: Mapped[str]=mapped_column(String(3),nullable=False,index=True)
    period_start: Mapped[str]=mapped_column(String(10),nullable=False)
    period_end: Mapped[str]=mapped_column(String(10),nullable=False)
    cutoff_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    state: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    movement_count: Mapped[int]=mapped_column(Integer,nullable=False)
    debit_minor: Mapped[int]=mapped_column(BigInteger,nullable=False)
    credit_minor: Mapped[int]=mapped_column(BigInteger,nullable=False)
    difference_minor: Mapped[int]=mapped_column(BigInteger,nullable=False)
    blockers_json: Mapped[list]=mapped_column(JSON,nullable=False)
    scope_hash: Mapped[str]=mapped_column(String(64),nullable=False,unique=True)
    evidence_hash: Mapped[str]=mapped_column(String(64),nullable=False)
    requested_by: Mapped[str]=mapped_column(String(64),nullable=False)
    approved_by: Mapped[str|None]=mapped_column(String(64))
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
    closed_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
    __table_args__=(UniqueConstraint('legal_entity_id','currency','period_start','period_end','cutoff_at',name='uq_finance_scoped_close_scope'),)

class FinanceScopedCloseLineRow(Base):
    __tablename__='finance_scoped_close_line'
    finance_scoped_close_line_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    finance_scoped_close_batch_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    source_type: Mapped[str]=mapped_column(String(32),nullable=False)
    source_id: Mapped[str]=mapped_column(String(64),nullable=False)
    state: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    amount_minor: Mapped[int]=mapped_column(BigInteger,nullable=False)
    evidence_hash: Mapped[str]=mapped_column(String(64),nullable=False)
    __table_args__=(UniqueConstraint('finance_scoped_close_batch_id','source_type','source_id',name='uq_finance_scoped_close_source'),)

# P0 remediation 0099 — order-money-supplier atomic truth closure.
class PaymentOrderRootRow(Base):
    __tablename__='payment_order_root'
    payment_order_root_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    business_type: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    business_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    payment_intent_id: Mapped[str]=mapped_column(String(64),nullable=False,unique=True,index=True)
    legal_entity_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    state: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    root_hash: Mapped[str]=mapped_column(String(64),nullable=False,unique=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
    __table_args__=(UniqueConstraint('business_type','business_id',name='uq_payment_order_single_root'),)

class PspSettlementLineRow(Base):
    __tablename__='psp_settlement_line'
    psp_settlement_line_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    payment_intent_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    external_transaction_id: Mapped[str]=mapped_column(String(128),nullable=False,unique=True,index=True)
    channel: Mapped[str]=mapped_column(String(40),nullable=False,index=True)
    legal_entity_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    amount_minor: Mapped[int]=mapped_column(BigInteger,nullable=False)
    currency: Mapped[str]=mapped_column(String(3),nullable=False,index=True)
    evidence_reference: Mapped[str]=mapped_column(String(512),nullable=False)
    occurred_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)

class BankStatementLineRow(Base):
    __tablename__='bank_statement_line'
    bank_statement_line_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    bank_line_identity: Mapped[str]=mapped_column(String(128),nullable=False,unique=True,index=True)
    legal_entity_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    amount_minor: Mapped[int]=mapped_column(BigInteger,nullable=False)
    currency: Mapped[str]=mapped_column(String(3),nullable=False,index=True)
    payment_reference: Mapped[str]=mapped_column(String(128),nullable=False,index=True)
    evidence_reference: Mapped[str]=mapped_column(String(512),nullable=False)
    booked_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)

class OrderSupplierFulfillmentRow(Base):
    __tablename__='order_supplier_fulfillment'
    order_supplier_fulfillment_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    payment_intent_id: Mapped[str]=mapped_column(String(64),nullable=False,unique=True,index=True)
    business_type: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    business_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    supplier_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    supplier_idempotency_key: Mapped[str]=mapped_column(String(128),nullable=False,unique=True)
    state: Mapped[str]=mapped_column(String(40),nullable=False,index=True)
    external_operation_id: Mapped[str|None]=mapped_column(String(128),unique=True,index=True)
    supplier_confirmation_reference: Mapped[str|None]=mapped_column(String(256))
    evidence_reference: Mapped[str]=mapped_column(String(512),nullable=False)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
    __table_args__=(UniqueConstraint('business_type','business_id',name='uq_order_single_supplier_fulfillment'),)

class OrderSupplierFulfillmentEventRow(Base):
    __tablename__='order_supplier_fulfillment_event'
    order_supplier_fulfillment_event_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    order_supplier_fulfillment_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    event_type: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    state: Mapped[str]=mapped_column(String(40),nullable=False,index=True)
    evidence_reference: Mapped[str]=mapped_column(String(512),nullable=False)
    payload_hash: Mapped[str]=mapped_column(String(64),nullable=False)
    occurred_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)

# P0 0100 — real external execution + certified sandbox truth-chain evidence.
class ExternalTruthOperationRow(Base):
    __tablename__='external_truth_operation'
    external_truth_operation_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    execution_authorization_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    payment_intent_id: Mapped[str|None]=mapped_column(String(64),index=True)
    supplier_fulfillment_id: Mapped[str|None]=mapped_column(String(64),index=True)
    vertical: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    operation_type: Mapped[str]=mapped_column(String(48),nullable=False,index=True)
    idempotency_key: Mapped[str]=mapped_column(String(160),nullable=False,unique=True)
    endpoint_reference: Mapped[str]=mapped_column(String(512),nullable=False)
    external_operation_id: Mapped[str|None]=mapped_column(String(256),index=True)
    http_status: Mapped[int|None]=mapped_column(Integer)
    state: Mapped[str]=mapped_column(String(48),nullable=False,index=True)
    request_hash: Mapped[str]=mapped_column(String(64),nullable=False)
    response_hash: Mapped[str|None]=mapped_column(String(64))
    evidence_reference: Mapped[str|None]=mapped_column(String(512))
    started_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
    completed_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True))

class ExternalTruthWebhookReceiptRow(Base):
    __tablename__='external_truth_webhook_receipt'
    external_truth_webhook_receipt_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    external_truth_operation_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    source_vertical: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    delivery_id: Mapped[str]=mapped_column(String(160),nullable=False,unique=True)
    signature_scheme: Mapped[str]=mapped_column(String(64),nullable=False)
    signature_verified: Mapped[bool]=mapped_column(Boolean,nullable=False)
    supplier_state: Mapped[str]=mapped_column(String(64),nullable=False)
    payload_hash: Mapped[str]=mapped_column(String(64),nullable=False)
    received_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)

class ExternalTruthBankFeedReceiptRow(Base):
    __tablename__='external_truth_bank_feed_receipt'
    bank_feed_receipt_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    provider_key: Mapped[str]=mapped_column(String(128),nullable=False,index=True)
    delivery_id: Mapped[str]=mapped_column(String(160),nullable=False,unique=True)
    signature_verified: Mapped[bool]=mapped_column(Boolean,nullable=False)
    payload_hash: Mapped[str]=mapped_column(String(64),nullable=False)
    imported_line_count: Mapped[int]=mapped_column(Integer,nullable=False)
    evidence_reference: Mapped[str]=mapped_column(String(512),nullable=False)
    received_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)

# P0 0101 — named-provider certification and PostgreSQL race proof evidence.
class NamedProviderCertificationEvidenceRow(Base):
    __tablename__='named_provider_certification_evidence'
    named_provider_certification_evidence_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    provider_kind: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    provider_name: Mapped[str]=mapped_column(String(96),nullable=False,index=True)
    environment: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    operation_type: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    external_reference: Mapped[str|None]=mapped_column(String(256),index=True)
    state: Mapped[str]=mapped_column(String(48),nullable=False,index=True)
    request_hash: Mapped[str]=mapped_column(String(64),nullable=False)
    response_hash: Mapped[str]=mapped_column(String(64),nullable=False)
    evidence_reference: Mapped[str]=mapped_column(String(512),nullable=False)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)

class PostgresRaceProofEvidenceRow(Base):
    __tablename__='postgres_race_proof_evidence'
    postgres_race_proof_evidence_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    scenario_key: Mapped[str]=mapped_column(String(96),nullable=False,index=True)
    database_version: Mapped[str]=mapped_column(String(128),nullable=False)
    worker_count: Mapped[int]=mapped_column(Integer,nullable=False)
    commit_count: Mapped[int]=mapped_column(Integer,nullable=False)
    reject_count: Mapped[int]=mapped_column(Integer,nullable=False)
    assertion_state: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    evidence_hash: Mapped[str]=mapped_column(String(64),nullable=False,unique=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)

# P0 Final Closure Program — immutable requirement/evidence registry.
class P0FinalClosureRequirementEvidenceRow(Base):
    __tablename__='p0_final_closure_requirement_evidence'
    p0_final_closure_requirement_evidence_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    requirement_key: Mapped[str]=mapped_column(String(128),nullable=False,index=True)
    domain: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    requirement_text: Mapped[str]=mapped_column(String(512),nullable=False)
    code_reference: Mapped[str]=mapped_column(String(512),nullable=False)
    runtime_evidence_reference: Mapped[str|None]=mapped_column(String(512))
    status: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    blocker_code: Mapped[str|None]=mapped_column(String(160),index=True)
    evidence_hash: Mapped[str]=mapped_column(String(64),nullable=False,unique=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)

class P0FinalClosureBundleRow(Base):
    __tablename__='p0_final_closure_bundle'
    p0_final_closure_bundle_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    build_sha256: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    design_state: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    code_state: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    runtime_state: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    external_sandbox_gate: Mapped[str]=mapped_column(String(16),nullable=False,index=True)
    blockers_json: Mapped[list]=mapped_column(JSON,nullable=False)
    requirement_snapshot_json: Mapped[list]=mapped_column(JSON,nullable=False)
    evidence_hash: Mapped[str]=mapped_column(String(64),nullable=False,unique=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)


# GO AI multi-model aggregation: prompts are not persisted here; only hashes and routing evidence.
class GoAIRequestRow(Base):
    __tablename__ = "go_ai_request"
    go_ai_request_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    account_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    task: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    region: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    locale: Mapped[str] = mapped_column(String(24), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    selected_provider: Mapped[str | None] = mapped_column(String(32), index=True)
    selected_model: Mapped[str | None] = mapped_column(String(128))
    response_hash: Mapped[str | None] = mapped_column(String(64))
    failure_code: Mapped[str | None] = mapped_column(String(96))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class GoAIExecutionRow(Base):
    """GO AI-specific execution ownership; not shared with other worker domains."""
    __tablename__ = "go_ai_execution"
    go_ai_request_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    fencing_token: Mapped[int] = mapped_column(BigInteger, nullable=False)
    lease_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    state: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    checkpoint_json: Mapped[dict | None] = mapped_column(JSON)
    checkpoint_hash: Mapped[str | None] = mapped_column(String(64))
    checkpoint_complete: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    provider_outcome: Mapped[str] = mapped_column(String(32), nullable=False, default="NOT_STARTED")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class GoAIInvocationRow(Base):
    __tablename__ = "go_ai_invocation"
    go_ai_invocation_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    go_ai_request_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    provider_key: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    provider_request_id: Mapped[str | None] = mapped_column(String(192))
    response_hash: Mapped[str | None] = mapped_column(String(64))
    error_code: Mapped[str | None] = mapped_column(String(96))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


# GO Hotel AutoPage Factory — multi-source hotel content graph, prebuilt page, contacts, registration and GO Direct.
class HotelContentSourceSnapshotRow(Base):
    __tablename__='hotel_content_source_snapshot'
    content_source_snapshot_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    source_key: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    source_type: Mapped[str]=mapped_column(String(48),nullable=False,index=True)
    external_hotel_id: Mapped[str]=mapped_column(String(192),nullable=False,index=True)
    source_url: Mapped[str|None]=mapped_column(String(1024))
    rights_status: Mapped[str]=mapped_column(String(48),nullable=False,index=True)
    confidence_bps: Mapped[int]=mapped_column(Integer,nullable=False,default=5000)
    payload_json: Mapped[dict]=mapped_column(JSON,nullable=False)
    payload_hash: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    canonical_hotel_id: Mapped[str|None]=mapped_column(String(64),index=True)
    observed_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
    __table_args__=(UniqueConstraint('source_key','external_hotel_id','payload_hash',name='uq_hotel_content_source_payload'),)

class HotelCanonicalProfileRow(Base):
    __tablename__='hotel_canonical_profile'
    hotel_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    slug: Mapped[str]=mapped_column(String(192),nullable=False,unique=True,index=True)
    canonical_json: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)
    field_provenance_json: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)
    source_snapshot_ids_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    completeness_bps: Mapped[int]=mapped_column(Integer,nullable=False,default=0,index=True)
    go_direct_state: Mapped[str]=mapped_column(String(32),nullable=False,default='NOT_REGISTERED',index=True)
    page_state: Mapped[str]=mapped_column(String(32),nullable=False,default='DRAFT',index=True)
    version: Mapped[int]=mapped_column(Integer,nullable=False,default=1)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)

class HotelContactPointRow(Base):
    __tablename__='hotel_contact_point'
    hotel_contact_point_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    hotel_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    contact_type: Mapped[str]=mapped_column(String(48),nullable=False,index=True)
    channel: Mapped[str]=mapped_column(String(24),nullable=False,index=True)
    value: Mapped[str]=mapped_column(String(512),nullable=False)
    normalized_value: Mapped[str]=mapped_column(String(512),nullable=False,index=True)
    source_url: Mapped[str|None]=mapped_column(String(1024))
    source_type: Mapped[str]=mapped_column(String(48),nullable=False)
    is_public_business_contact: Mapped[bool]=mapped_column(Boolean,nullable=False,default=False)
    jurisdiction: Mapped[str|None]=mapped_column(String(16),index=True)
    confidence_bps: Mapped[int]=mapped_column(Integer,nullable=False,default=5000)
    marketing_eligibility: Mapped[str]=mapped_column(String(40),nullable=False,default='REVIEW_REQUIRED',index=True)
    do_not_contact: Mapped[bool]=mapped_column(Boolean,nullable=False,default=False,index=True)
    verified_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
    __table_args__=(UniqueConstraint('hotel_id','channel','normalized_value',name='uq_hotel_contact_point_value'),)

class HotelAutoPageVersionRow(Base):
    __tablename__='hotel_auto_page_version'
    hotel_auto_page_version_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    hotel_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    slug: Mapped[str]=mapped_column(String(192),nullable=False,index=True)
    version: Mapped[int]=mapped_column(Integer,nullable=False)
    page_json: Mapped[dict]=mapped_column(JSON,nullable=False)
    page_hash: Mapped[str]=mapped_column(String(64),nullable=False,unique=True)
    source_snapshot_ids_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    go_direct_state: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    publication_state: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
    __table_args__=(UniqueConstraint('hotel_id','version',name='uq_hotel_auto_page_version'),)

class HotelRegistrationDirectRow(Base):
    __tablename__='hotel_registration_go_direct'
    hotel_registration_direct_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    hotel_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    supplier_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    state: Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    evidence_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    official_supplement_json: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)
    requested_by: Mapped[str]=mapped_column(String(64),nullable=False)
    reviewed_by: Mapped[str|None]=mapped_column(String(64))
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
    reviewed_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True))

class HotelAutoPageEventRow(Base):
    __tablename__='hotel_auto_page_event'
    hotel_auto_page_event_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    hotel_id: Mapped[str|None]=mapped_column(String(64),index=True)
    event_type: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    evidence_json: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)
    actor: Mapped[str]=mapped_column(String(64),nullable=False)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)


# GO Personal Travel Vault / Universal Import (P0 master baseline, 2026-08-20).
class ProfileImportJobRow(Base):
    __tablename__ = "profile_import_job"
    import_job_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    source_provider: Mapped[str | None] = mapped_column(String(96), index=True)
    source_reference: Mapped[str | None] = mapped_column(Text)
    source_fingerprint: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="RECEIVED", index=True)
    consent_id: Mapped[str | None] = mapped_column(String(64), index=True)
    item_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    accepted_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rejected_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    conflict_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

class ProfileImportItemRow(Base):
    __tablename__ = "profile_import_item"
    import_item_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    import_job_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    traveler_ref: Mapped[str | None] = mapped_column(String(128), index=True)
    field_type: Mapped[str | None] = mapped_column(String(64), index=True)
    candidate_value_ciphertext: Mapped[str | None] = mapped_column(Text)
    normalized_value_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    preview_masked: Mapped[str | None] = mapped_column(Text)
    sensitive: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    confidence_bps: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_payload_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="EXTRACTED", index=True)
    resolution_traveler_id: Mapped[str | None] = mapped_column(String(64), index=True)
    conflict_fact_id: Mapped[str | None] = mapped_column(String(64), index=True)
    review_action: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class ProfileFactRow(Base):
    __tablename__ = "profile_fact"
    fact_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    traveler_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    field_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    value_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_value_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    sensitive: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source_type: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    source_provider: Mapped[str | None] = mapped_column(String(96), index=True)
    source_reference: Mapped[str | None] = mapped_column(Text)
    source_fingerprint: Mapped[str | None] = mapped_column(String(128), index=True)
    confidence_bps: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    user_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    trust_level: Mapped[str] = mapped_column(String(32), nullable=False, default="L0_EXTRACTED", index=True)
    verification_status: Mapped[str] = mapped_column(String(32), nullable=False, default="CANDIDATE", index=True)
    verification_method: Mapped[str | None] = mapped_column(String(64))
    valid_from: Mapped[str | None] = mapped_column(String(32))
    valid_until: Mapped[str | None] = mapped_column(String(32), index=True)
    superseded_by: Mapped[str | None] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="ACTIVE", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class ProfileConsentRow(Base):
    __tablename__ = "profile_consent"
    consent_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    traveler_id: Mapped[str | None] = mapped_column(String(64), index=True)
    consent_type: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    purpose: Mapped[str] = mapped_column(String(128), nullable=False)
    scope_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="ACTIVE", index=True)
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

class ProfileTravelerPermissionRow(Base):
    __tablename__ = "profile_traveler_permission"
    permission_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    traveler_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    permission_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source: Mapped[str] = mapped_column(String(48), nullable=False, default="USER")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class ProfileDataReleaseAuditRow(Base):
    __tablename__ = "profile_data_release_audit"
    release_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    traveler_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    requester_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    requester_id: Mapped[str | None] = mapped_column(String(96), index=True)
    vertical: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    purpose: Mapped[str] = mapped_column(String(128), nullable=False)
    destination: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    booking_id: Mapped[str | None] = mapped_column(String(64), index=True)
    requested_fields_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    released_fields_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    consent_id: Mapped[str | None] = mapped_column(String(64), index=True)
    decision: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

class ProfileAccessAuditRow(Base):
    __tablename__ = "profile_access_audit"
    access_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    traveler_id: Mapped[str | None] = mapped_column(String(64), index=True)
    actor_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    actor_type: Mapped[str] = mapped_column(String(32), nullable=False)
    action: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    purpose: Mapped[str | None] = mapped_column(String(128))
    fields_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

Index("ix_profile_import_user_source", ProfileImportJobRow.user_id, ProfileImportJobRow.source_fingerprint)
Index("ix_profile_fact_traveler_field_status", ProfileFactRow.traveler_id, ProfileFactRow.field_type, ProfileFactRow.status)
Index("ix_profile_release_user_created", ProfileDataReleaseAuditRow.user_id, ProfileDataReleaseAuditRow.created_at)


# GO Consumer Growth + Official Direct Value Constitution (V5.3, 2026-08-20).
class DirectValueOfferRow(Base):
    __tablename__='direct_value_offer'
    direct_value_offer_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    supplier_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    hotel_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    status: Mapped[str]=mapped_column(String(24),nullable=False,default='ACTIVE',index=True)
    cash_discount_bps: Mapped[int]=mapped_column(Integer,nullable=False,default=0)
    upgrade_priority: Mapped[bool]=mapped_column(Boolean,nullable=False,default=False)
    late_checkout_priority: Mapped[bool]=mapped_column(Boolean,nullable=False,default=False)
    late_checkout_time: Mapped[str|None]=mapped_column(String(8))
    breakfast_option: Mapped[str]=mapped_column(String(24),nullable=False,default='NONE')
    benefits_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    supplier_incremental_cost_minor: Mapped[int]=mapped_column(Integer,nullable=False,default=0)
    consumer_perceived_value_minor: Mapped[int]=mapped_column(Integer,nullable=False,default=0)
    currency: Mapped[str]=mapped_column(String(3),nullable=False,default='CNY')
    starts_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True),index=True)
    ends_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True),index=True)
    authorization_reference: Mapped[str]=mapped_column(String(160),nullable=False)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)

class MarketBenchmarkQuoteRow(Base):
    __tablename__='market_benchmark_quote'
    benchmark_quote_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    hotel_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    source_provider: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    source_type: Mapped[str]=mapped_column(String(32),nullable=False,default='AUTHORIZED_THIRD_PARTY',index=True)
    check_in: Mapped[str]=mapped_column(String(10),nullable=False,index=True)
    check_out: Mapped[str]=mapped_column(String(10),nullable=False)
    room_type_key: Mapped[str]=mapped_column(String(128),nullable=False)
    occupancy_key: Mapped[str]=mapped_column(String(64),nullable=False)
    meal_plan_key: Mapped[str]=mapped_column(String(64),nullable=False)
    cancellation_key: Mapped[str]=mapped_column(String(128),nullable=False)
    tax_fee_key: Mapped[str]=mapped_column(String(64),nullable=False)
    eligibility_key: Mapped[str]=mapped_column(String(128),nullable=False,default='PUBLIC')
    total_amount_minor: Mapped[int]=mapped_column(Integer,nullable=False)
    currency: Mapped[str]=mapped_column(String(3),nullable=False)
    comparable_fingerprint: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    authorized_for_consumer: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)
    captured_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    expires_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True),index=True)
    evidence_json: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)

class SupplierChannelEconomicsRow(Base):
    __tablename__='supplier_channel_economics'
    channel_economics_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    supplier_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    hotel_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    direct_value_offer_id: Mapped[str|None]=mapped_column(String(64),index=True)
    direct_rate_minor: Mapped[int]=mapped_column(Integer,nullable=False)
    market_rate_minor: Mapped[int|None]=mapped_column(Integer)
    ota_channel_cost_bps: Mapped[int]=mapped_column(Integer,nullable=False)
    go_direct_cost_bps: Mapped[int]=mapped_column(Integer,nullable=False)
    cash_discount_bps: Mapped[int]=mapped_column(Integer,nullable=False,default=0)
    consumer_value_shared_minor: Mapped[int]=mapped_column(Integer,nullable=False,default=0)
    supplier_incremental_cost_minor: Mapped[int]=mapped_column(Integer,nullable=False,default=0)
    ota_net_revenue_minor: Mapped[int|None]=mapped_column(Integer)
    go_net_revenue_minor: Mapped[int]=mapped_column(Integer,nullable=False)
    net_revenue_uplift_minor: Mapped[int|None]=mapped_column(Integer)
    currency: Mapped[str]=mapped_column(String(3),nullable=False)
    assumptions_json: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)

class DirectValueRecommendationRow(Base):
    __tablename__='direct_value_recommendation'
    direct_value_recommendation_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    supplier_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    hotel_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    direct_value_offer_id: Mapped[str|None]=mapped_column(String(64),index=True)
    recommendation_type: Mapped[str]=mapped_column(String(40),nullable=False,index=True)
    proposed_cash_discount_bps: Mapped[int]=mapped_column(Integer,nullable=False,default=0)
    proposed_benefits_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    consumer_perceived_value_minor: Mapped[int]=mapped_column(Integer,nullable=False,default=0)
    supplier_incremental_cost_minor: Mapped[int]=mapped_column(Integer,nullable=False,default=0)
    value_efficiency_bps: Mapped[int]=mapped_column(Integer,nullable=False,default=0)
    reason_codes_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    recommendation_pool_unchanged: Mapped[bool]=mapped_column(Boolean,nullable=False,default=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)

class ConsumerGrowthEventRow(Base):
    __tablename__='consumer_growth_event'
    growth_event_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    user_id: Mapped[str|None]=mapped_column(String(64),index=True)
    event_type: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    source_surface: Mapped[str|None]=mapped_column(String(64),index=True)
    object_type: Mapped[str|None]=mapped_column(String(48),index=True)
    object_id: Mapped[str|None]=mapped_column(String(96),index=True)
    referrer_user_id: Mapped[str|None]=mapped_column(String(64),index=True)
    journey_id: Mapped[str|None]=mapped_column(String(64),index=True)
    supplier_id: Mapped[str|None]=mapped_column(String(64),index=True)
    metadata_json: Mapped[dict]=mapped_column(JSON,nullable=False,default=dict)
    occurred_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)

class ConsumerGrowthAttributionRow(Base):
    __tablename__='consumer_growth_attribution'
    growth_attribution_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    user_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    acquisition_source: Mapped[str|None]=mapped_column(String(64),index=True)
    registration_trigger: Mapped[str|None]=mapped_column(String(64),index=True)
    activation_trigger: Mapped[str|None]=mapped_column(String(64),index=True)
    referrer_user_id: Mapped[str|None]=mapped_column(String(64),index=True)
    supplier_id: Mapped[str|None]=mapped_column(String(64),index=True)
    first_seen_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
    registered_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
    activated_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True),index=True)
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)

class ConsumerTripMemberRow(Base):
    __tablename__='consumer_trip_member'
    trip_member_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    journey_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    user_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    role: Mapped[str]=mapped_column(String(24),nullable=False,default='MEMBER')
    status: Mapped[str]=mapped_column(String(24),nullable=False,default='ACTIVE',index=True)
    source_invitation_id: Mapped[str|None]=mapped_column(String(64),index=True)
    joined_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)

Index('uq_consumer_trip_member_journey_user', ConsumerTripMemberRow.journey_id, ConsumerTripMemberRow.user_id, unique=True)

class ConsumerTripInvitationRow(Base):
    __tablename__='consumer_trip_invitation'
    invitation_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    journey_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    inviter_user_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    invite_token_hash: Mapped[str]=mapped_column(String(64),nullable=False,unique=True,index=True)
    invitee_hint_hash: Mapped[str|None]=mapped_column(String(64),index=True)
    status: Mapped[str]=mapped_column(String(24),nullable=False,default='ACTIVE',index=True)
    joined_user_id: Mapped[str|None]=mapped_column(String(64),index=True)
    expires_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
    joined_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True))

class TravelerClaimRow(Base):
    __tablename__='traveler_claim'
    traveler_claim_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    traveler_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    owner_user_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    target_email_hash: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    claim_token_hash: Mapped[str]=mapped_column(String(64),nullable=False,unique=True,index=True)
    status: Mapped[str]=mapped_column(String(24),nullable=False,default='PENDING',index=True)
    claimed_user_id: Mapped[str|None]=mapped_column(String(64),index=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
    expires_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    claimed_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True))

class TripImportIntentRow(Base):
    __tablename__='trip_import_intent'
    trip_import_intent_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    user_id: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    source_type: Mapped[str]=mapped_column(String(48),nullable=False,index=True)
    source_provider: Mapped[str|None]=mapped_column(String(96),index=True)
    source_reference: Mapped[str|None]=mapped_column(Text)
    content_hash: Mapped[str]=mapped_column(String(64),nullable=False,index=True)
    status: Mapped[str]=mapped_column(String(32),nullable=False,default='RECEIVED',index=True)
    detected_verticals_json: Mapped[list]=mapped_column(JSON,nullable=False,default=list)
    created_journey_id: Mapped[str|None]=mapped_column(String(64),index=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)

Index('ix_direct_value_offer_hotel_status',DirectValueOfferRow.hotel_id,DirectValueOfferRow.status)
Index('ix_market_benchmark_hotel_capture',MarketBenchmarkQuoteRow.hotel_id,MarketBenchmarkQuoteRow.captured_at)
Index('ix_growth_event_user_time',ConsumerGrowthEventRow.user_id,ConsumerGrowthEventRow.occurred_at)
Index('ix_growth_attribution_user_activation',ConsumerGrowthAttributionRow.user_id,ConsumerGrowthAttributionRow.activated_at)


# Travel Intelligence Layer 1.0 / Parent Implementation Build P0.
# These rows are additive projections and governance records. They do not replace
# authoritative Order, Payment/Ledger, Supplier Fulfillment or Personal Travel Vault truth.
class TravelEntityRow(Base):
    __tablename__ = "travel_entity"
    go_entity_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    canonical_name: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="ACTIVE", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (CheckConstraint("length(canonical_name) > 0", name="ck_ti_entity_name"),)

class TravelEntityAliasRow(Base):
    __tablename__ = "travel_entity_alias"
    alias_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    go_entity_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), ForeignKey("travel_entity.go_entity_id"), nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(String(40), nullable=False)
    source_entity_id: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_name: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (UniqueConstraint("source_type", "source_entity_id", name="uq_ti_alias_source"),)

class TravelEntityRelationRow(Base):
    __tablename__ = "travel_entity_relation"
    relation_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    from_entity_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), ForeignKey("travel_entity.go_entity_id"), nullable=False, index=True)
    relation_type: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    to_entity_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), ForeignKey("travel_entity.go_entity_id"), nullable=False)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (CheckConstraint("from_entity_id <> to_entity_id", name="ck_ti_relation_not_self"),)

class TravelEntityFactRow(Base):
    __tablename__ = "travel_entity_fact"
    fact_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    go_entity_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), ForeignKey("travel_entity.go_entity_id"), nullable=False, index=True)
    fact_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    fact_value: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    provenance: Mapped[str] = mapped_column(String(40), nullable=False)
    source_id: Mapped[str | None] = mapped_column(Text)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    verification_state: Mapped[str] = mapped_column(String(32), nullable=False)
    evidence_ref: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_ti_fact_confidence"),)

class TravelIntentRow(Base):
    __tablename__ = "travel_intent"
    intent_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    traveler_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    session_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    raw_input: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_intent: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    consent_scope: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="ACTIVE", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class TravelIntentConstraintRow(Base):
    __tablename__ = "travel_intent_constraint"
    constraint_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    intent_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), ForeignKey("travel_intent.intent_id"), nullable=False, index=True)
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    value_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="USER_INPUT")
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_ti_constraint_confidence"),)

class TravelBehaviorEventRow(Base):
    __tablename__ = "travel_behavior_event"
    event_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    actor_type: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(64))
    tenant_id: Mapped[str | None] = mapped_column(String(64))
    organization_id: Mapped[str | None] = mapped_column(String(64))
    traveler_id: Mapped[str | None] = mapped_column(String(64), index=True)
    session_id: Mapped[str | None] = mapped_column(String(64), index=True)
    intent_id: Mapped[object | None] = mapped_column(Uuid(as_uuid=True), index=True)
    entity_id: Mapped[object | None] = mapped_column(Uuid(as_uuid=True), index=True)
    decision_id: Mapped[object | None] = mapped_column(Uuid(as_uuid=True), index=True)
    trip_id: Mapped[str | None] = mapped_column(String(64), index=True)
    order_id: Mapped[str | None] = mapped_column(String(64), index=True)
    transaction_root_id: Mapped[str | None] = mapped_column(String(64), index=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(16), nullable=False, default="1.0")
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    causation_id: Mapped[str | None] = mapped_column(String(64))
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False, unique=True)
    privacy_class: Mapped[str] = mapped_column(String(16), nullable=False)
    retention_class: Mapped[str] = mapped_column(String(24), nullable=False)
    payload_schema: Mapped[str | None] = mapped_column(String(96))
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class AIDecisionRow(Base):
    __tablename__ = "ai_decision"
    decision_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    previous_hash: Mapped[str | None] = mapped_column(String(64))
    decision_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    input_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    rule_version: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    model_version: Mapped[str] = mapped_column(String(128), nullable=False)
    input_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    evidence_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    output_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

class AIDecisionModelCallRow(Base):
    __tablename__ = "ai_decision_model_call"
    model_call_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    decision_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), ForeignKey("ai_decision.decision_id"), nullable=False, index=True)
    routing_decision_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    session_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    capability: Mapped[str] = mapped_column(String(48), nullable=False)
    cost_scope: Mapped[str] = mapped_column(String(24), nullable=False, default="JUDGMENT", index=True)
    business_reference_id: Mapped[str | None] = mapped_column(String(96), index=True)
    tier: Mapped[int] = mapped_column(Integer, nullable=False)
    provider_id: Mapped[str | None] = mapped_column(String(64))
    model_version: Mapped[str] = mapped_column(String(128), nullable=False)
    price_snapshot_id: Mapped[str] = mapped_column(String(96), nullable=False)
    estimated_quality: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    estimated_cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    attributed_revenue_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class TransactionRelationRow(Base):
    __tablename__ = "transaction_relation"
    relation_id: Mapped[object] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    source_truth_domain: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    source_truth_id: Mapped[str] = mapped_column(Text, nullable=False)
    relation_type: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    subject_id: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    object_id: Mapped[str] = mapped_column(Text, nullable=False)
    source_event_id: Mapped[str] = mapped_column(Text, nullable=False)
    projected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (UniqueConstraint("source_truth_domain", "source_truth_id", "relation_type", "subject_id", "object_id", name="uq_ti_transaction_projection"),)

class HostedFareRuleVersionRow(Base):
    __tablename__ = 'hosted_fare_rule_version'
    rule_version_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    hosted_offer_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    rules_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    rule_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    authority_reference: Mapped[str] = mapped_column(String(512), nullable=False)
    published_by: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (UniqueConstraint('hosted_offer_id', 'version', name='uq_hosted_fare_version'),)

class HostedOrderFareSnapshotRow(Base):
    __tablename__ = 'hosted_order_fare_snapshot'
    hosted_reservation_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    rule_version_id: Mapped[str] = mapped_column(String(64), nullable=False)
    rules_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    rule_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class HostedFareQuoteRow(Base):
    __tablename__ = 'hosted_fare_quote'
    quote_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    hosted_reservation_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    order_revision: Mapped[str] = mapped_column(String(64), nullable=False)
    quote_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    quote_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False)
    result_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class HostedFareFundingRow(Base):
    __tablename__ = 'hosted_fare_funding'
    quote_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    hosted_reservation_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    generation: Mapped[int] = mapped_column(Integer, nullable=False)
    payment_intent_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (UniqueConstraint('hosted_reservation_id','generation',name='uq_hosted_fare_funding_generation'),)

class HostedStayCreditRow(Base):
    __tablename__ = 'hosted_stay_credit'
    credit_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    original_reservation_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    account_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    hosted_hotel_id: Mapped[str] = mapped_column(String(64), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False)
    source_capture_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    issued_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    available_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    ledger_head_hash: Mapped[str | None] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class HostedCreditAllocationRow(Base):
    __tablename__ = 'hosted_credit_allocation'
    hosted_reservation_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    credit_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    quote_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    applied_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    forfeited_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    fulfilled_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    fee_consumed_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    restored_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    state: Mapped[str] = mapped_column(String(24), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class HostedCreditValueEventRow(Base):
    __tablename__ = 'hosted_credit_value_event'
    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    credit_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    generation: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    delta_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    balance_after_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reservation_id: Mapped[str | None] = mapped_column(String(64))
    evidence_json: Mapped[list] = mapped_column(JSON, nullable=False)
    previous_hash: Mapped[str | None] = mapped_column(String(64))
    event_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    actor_id: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (UniqueConstraint('credit_id','generation',name='uq_hosted_credit_event_generation'),)

class HostedCreditRefundPlanRow(Base):
    __tablename__ = 'hosted_credit_refund_plan'
    refund_eligibility_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    hosted_reservation_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    plan_json: Mapped[list] = mapped_column(JSON, nullable=False)
    plan_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class HostedSupplierDisruptionRow(Base):
    __tablename__ = 'hosted_supplier_disruption'
    case_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    hosted_reservation_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    hosted_hotel_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    account_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    requester_id: Mapped[str] = mapped_column(String(64), nullable=False)
    request_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_json: Mapped[list] = mapped_column(JSON, nullable=False)
    evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    checker_id: Mapped[str | None] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(40), nullable=False)
    decision_json: Mapped[dict | None] = mapped_column(JSON)
    decision_hash: Mapped[str | None] = mapped_column(String(64))
    post_stay_case_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    refund_eligibility_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    compensation_intent_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class HostedFaultDebitMandateRow(Base):
    __tablename__ = 'hosted_fault_debit_mandate'
    mandate_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    hosted_hotel_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    scope: Mapped[str] = mapped_column(String(64), nullable=False)
    maximum_per_case_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    authority_reference: Mapped[str] = mapped_column(String(512), nullable=False)
    authority_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    registered_by: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    deactivated_by: Mapped[str | None] = mapped_column(String(64))
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class HostedFaultRecoveryRow(Base):
    __tablename__ = 'hosted_fault_recovery'
    recovery_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    hosted_hotel_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_reference_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    result_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    actor_id: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CatalogSupplierRemedyRow(Base):
    __tablename__ = 'catalog_supplier_remedy'
    case_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    order_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    supplier_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    account_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    requester_id: Mapped[str] = mapped_column(String(64), nullable=False)
    request_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_json: Mapped[list] = mapped_column(JSON, nullable=False)
    evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    checker_id: Mapped[str | None] = mapped_column(String(64))
    decision_json: Mapped[dict | None] = mapped_column(JSON)
    decision_hash: Mapped[str | None] = mapped_column(String(64))
    refund_lines_json: Mapped[list | None] = mapped_column(JSON)
    refund_lines_hash: Mapped[str | None] = mapped_column(String(64))
    supplier_cancel_reference: Mapped[str | None] = mapped_column(String(512))
    compensation_intent_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CatalogFaultDebitMandateRow(Base):
    __tablename__ = 'catalog_fault_debit_mandate'
    mandate_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    supplier_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    scope: Mapped[str] = mapped_column(String(64), nullable=False)
    maximum_per_case_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    authority_reference: Mapped[str] = mapped_column(String(512), nullable=False)
    authority_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    registered_by: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    deactivated_by: Mapped[str | None] = mapped_column(String(64))
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CatalogFaultRecoveryRow(Base):
    __tablename__ = 'catalog_fault_recovery'
    recovery_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    supplier_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_reference_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    result_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    actor_id: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CatalogCreditContractRow(Base):
    __tablename__ = 'catalog_credit_contract'
    credit_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    original_order_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    quote_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    contract_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    contract_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    available_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    expired_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    ledger_head_hash: Mapped[str | None] = mapped_column(String(64))
    accepted_by: Mapped[str] = mapped_column(String(64), nullable=False)
    accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CatalogCreditSourceRow(Base):
    __tablename__ = 'catalog_credit_source'
    capture_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    credit_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    payment_intent_id: Mapped[str] = mapped_column(String(64), nullable=False)
    funded_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    prior_refund_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    excluded_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)


class CatalogCreditQuoteRow(Base):
    __tablename__ = 'catalog_credit_quote'
    quote_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    order_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    credit_id: Mapped[str | None] = mapped_column(String(64), index=True)
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CatalogCreditAllocationRow(Base):
    __tablename__ = 'catalog_credit_allocation'
    order_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    credit_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    quote_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    state: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    request_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    applied_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    forfeited_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    restored_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    refunded_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    cash_due_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    supplier_confirmation_no: Mapped[str | None] = mapped_column(String(128))
    payment_json: Mapped[dict | None] = mapped_column(JSON)
    after_sales_json: Mapped[dict | None] = mapped_column(JSON)
    after_sales_hash: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CatalogCreditValueEventRow(Base):
    __tablename__ = 'catalog_credit_value_event'
    __table_args__ = (UniqueConstraint('credit_id', 'generation', name='uq_catalog_credit_generation'),)
    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    credit_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    generation: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(48), nullable=False)
    delta_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    balance_after_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    order_id: Mapped[str | None] = mapped_column(String(64))
    evidence_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    previous_hash: Mapped[str | None] = mapped_column(String(64))
    event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CatalogFareFamilyRow(Base):
    __tablename__ = 'catalog_fare_family'
    family_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    property_id: Mapped[str] = mapped_column(String(64), nullable=False)
    supplier_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    connector_id: Mapped[str] = mapped_column(String(64), nullable=False)
    fare_rule_id: Mapped[str] = mapped_column(String(64), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False)
    current_version_id: Mapped[str | None] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class CatalogFareRuleVersionRow(Base):
    __tablename__ = 'catalog_fare_rule_version'
    __table_args__ = (UniqueConstraint('family_id', 'version', name='uq_catalog_fare_version'),)
    version_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    family_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    contract_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    contract_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    published_by: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CatalogOfferFareSnapshotRow(Base):
    __tablename__ = 'catalog_offer_fare_snapshot'
    offer_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    version_id: Mapped[str] = mapped_column(String(64), nullable=False)
    snapshot_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CatalogOrderFareSnapshotRow(Base):
    __tablename__ = 'catalog_order_fare_snapshot'
    order_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    version_id: Mapped[str] = mapped_column(String(64), nullable=False)
    snapshot_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    accepted_by: Mapped[str] = mapped_column(String(64), nullable=False)
    acceptance_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class HostedMoneyUnknownEpisodeRow(Base):
    __tablename__ = 'hosted_money_unknown_episode'
    __table_args__ = (
        UniqueConstraint('money_movement_id', 'episode_generation', name='uq_hosted_money_unknown_generation'),
    )
    episode_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    authorization_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    hosted_reservation_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    money_movement_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    funding_leg: Mapped[str] = mapped_column(String(40), nullable=False)
    episode_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    open_evidence_reference: Mapped[str] = mapped_column(String(512), nullable=False)
    open_evidence_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    resolution_decision: Mapped[str | None] = mapped_column(String(32))
    resolution_evidence_reference: Mapped[str | None] = mapped_column(String(512))
    resolution_evidence_digest: Mapped[str | None] = mapped_column(String(64))
    opened_by: Mapped[str] = mapped_column(String(64), nullable=False)
    resolved_by: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class HostedMoneyUnknownEpisodeAuditRow(Base):
    __tablename__ = 'hosted_money_unknown_episode_audit'
    __table_args__ = (
        UniqueConstraint('episode_id', 'sequence', name='uq_hosted_money_unknown_audit_sequence'),
    )
    audit_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    episode_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    previous_hash: Mapped[str | None] = mapped_column(String(64))
    event_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

