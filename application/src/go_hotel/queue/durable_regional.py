"""Database-backed, at-least-once regional delivery with fenced ACK and bounded retry.

Queue receipts are not proof of hotel completeness. Discovery adapters can replay
local facts after a crash; this queue does not claim atomicity with every adapter
write or authorize external mutations. Historical Redis work needs explicit import.
"""
from go_hotel.services import catalog_scope
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
import uuid

from sqlalchemy import and_, or_, select, func

from go_hotel.autonomy.durable import canonical, db_now_ms, digest, insert_once, transaction
from go_hotel.db.models import RegionalQueueRow as Row, HotelAutoPageEventRow as Event
from go_hotel.db.session import SessionLocal

_current_claim = ContextVar('regional_current_claim', default=None)


class RegionalLeaseLost(ValueError):
    pass


@dataclass(frozen=True)
class Claim:
    message_id: str
    topic: str
    payload: dict
    lease_token: str
    attempt: int


def current_reference():
    current = _current_claim.get()
    if not current:
        return {}
    claim = current[1]
    return {'delivery_message_id': claim.message_id, 'delivery_attempt': claim.attempt}


def guard_current(session):
    current = _current_claim.get()
    if current:
        queue, claim = current
        queue.owned(session, claim)


@contextmanager
def processing(queue, claim):
    token = _current_claim.set((queue, claim))
    try:
        yield
    finally:
        _current_claim.reset(token)


class DurableRegionalQueue:
    def __init__(self, factory=SessionLocal, *, lease_ms=300_000, max_attempts=5):
        if type(lease_ms) is not int or lease_ms < 100:
            raise ValueError('REGIONAL_LEASE_INVALID')
        if type(max_attempts) is not int or not 1 <= max_attempts <= 20:
            raise ValueError('REGIONAL_MAX_ATTEMPTS_INVALID')
        self.factory, self.lease_ms, self.max_attempts = factory, lease_ms, max_attempts

    def enqueue(self, topic, message_id, payload, *, on_create=None, supersedes=None):
        body = canonical(payload)
        if not isinstance(payload, dict) or not payload.get('run_id') or len(body.encode()) > 2_000_000:
            raise ValueError('REGIONAL_QUEUE_PAYLOAD_INVALID')
        with transaction(self.factory) as s:
            catalog_scope.scope_lock(s)
            catalog_scope.require_run(s,payload)
            guard_current(s)
            now = db_now_ms(s)
            # The primary key serializes repeated submissions across processes.
            insert_once(s, Row, dict(message_id=message_id, topic=topic, run_id=payload['run_id'],
                payload_hash=digest(payload), payload_json=payload, status='QUEUED', attempt=0,
                max_attempts=self.max_attempts, available_ms=now, created_ms=now, updated_ms=now), ['message_id'])
            row = s.scalar(select(Row).where(Row.message_id == message_id).with_for_update())
            if row.topic != topic or row.payload_hash != digest(payload):
                raise ValueError('REGIONAL_QUEUE_PAYLOAD_CONFLICT')
            if supersedes:
                previous = s.scalar(select(Row).where(Row.message_id == supersedes).with_for_update())
                if previous is None or previous.run_id != row.run_id or previous.message_id == row.message_id:
                    raise ValueError('REGIONAL_RETRY_ORIGIN_INVALID')
                if previous.status == 'DEAD':
                    previous.status = 'SUPERSEDED'
                    previous.result_json = {'retry_message_id': message_id}
                    previous.updated_ms = now
                elif previous.status != 'SUPERSEDED' or (previous.result_json or {}).get('retry_message_id') != message_id:
                    raise ValueError('REGIONAL_RETRY_ORIGIN_NOT_DEAD')
            # Evidence callback uses deterministic event IDs. Both records commit together.
            if on_create:
                on_create(s, message_id)
        return message_id

    def claim(self, topic):
        with transaction(self.factory) as s:
            catalog_scope.scope_lock(s)
            active=catalog_scope.state(s)
            visible=Row.run_id.not_in(active['retired_run_ids']) if active else True
            now = db_now_ms(s)
            ready = or_(and_(Row.status == 'QUEUED', Row.available_ms <= now),
                        and_(Row.status == 'RUNNING', Row.lease_until_ms <= now))
            while True:
                row = s.scalar(select(Row).where(Row.topic == topic, ready, visible)
                    .order_by(Row.available_ms, Row.created_ms, Row.message_id)
                    .with_for_update(skip_locked=True).limit(1))
                if row is None:
                    return None
                if row.attempt >= row.max_attempts:
                    row.status, row.last_code = 'DEAD', 'ATTEMPTS_EXHAUSTED'
                    row.lease_token, row.lease_until_ms, row.updated_ms = None, None, now
                    self._dead_event(s, row)
                    s.flush()
                    continue
                catalog_scope.require_run(s,row.payload_json)
                row.status = 'RUNNING'
                row.attempt += 1
                row.lease_token = uuid.uuid4().hex
                row.lease_until_ms = now + self.lease_ms
                row.updated_ms = now
                return Claim(row.message_id, row.topic, row.payload_json, row.lease_token, row.attempt)

    def owned(self, session, claim):
        row = session.scalar(select(Row).where(Row.message_id == claim.message_id).with_for_update())
        if row is None or row.topic != claim.topic or row.status != 'RUNNING' or row.lease_token != claim.lease_token or row.lease_until_ms <= db_now_ms(session):
            raise RegionalLeaseLost('REGIONAL_QUEUE_LEASE_LOST')
        return row

    def heartbeat(self, claim):
        with transaction(self.factory) as s:
            row = self.owned(s, claim)
            now = db_now_ms(s)
            row.lease_until_ms, row.updated_ms = now + self.lease_ms, now

    def ack(self, claim, result=None):
        with transaction(self.factory) as s:
            row = self.owned(s, claim)
            row.status, row.result_json, row.updated_ms = 'SUCCEEDED', result, db_now_ms(s)
            row.lease_token, row.lease_until_ms = None, None

    @staticmethod
    def _dead_event(session, row):
        payload = row.payload_json
        details = {k: payload.get(k) for k in ('run_id','province','city','tier','candidate_key','task')}
        details.update(scope='DELIVERY', error_code='REGIONAL_QUEUE_DEAD', error=row.last_code,
            delivery_message_id=row.message_id, delivery_attempt=row.attempt,
            operator_action_required=True, retryable=True)
        insert_once(session, Event, dict(
            hotel_auto_page_event_id='hape_' + digest([row.message_id, row.attempt, 'DEAD'])[:56],
            hotel_id=None, event_type='REGIONAL_BUILD_FAILURE', evidence_json=details,
            actor='REGIONAL_QUEUE', created_at=datetime.now(timezone.utc)), ['hotel_auto_page_event_id'])

    def fail(self, claim, code, *, retryable=True):
        with transaction(self.factory) as s:
            row = self.owned(s, claim)
            now = db_now_ms(s)
            row.status = 'QUEUED' if retryable and row.attempt < row.max_attempts else 'DEAD'
            row.last_code = str(code)[:96]
            row.available_ms = now + min(60_000, 1000 * 2 ** (row.attempt - 1))
            row.updated_ms = now
            row.lease_token, row.lease_until_ms = None, None
            if row.status == 'DEAD':
                self._dead_event(s, row)

    def retry_payload(self, message_id):
        with self.factory() as s:
            row = s.get(Row, message_id)
            if row is None or row.status != 'DEAD':
                raise ValueError('REGIONAL_RETRY_ORIGIN_NOT_DEAD')
            return row.payload_json

    def retry_needed(self, message_id):
        with self.factory() as s:
            row = s.get(Row, message_id)
            return row is None or row.status == 'DEAD'

    def tier_ready(self, run_id, tier):
        current = _current_claim.get()
        current_id = current[1].message_id if current else None
        with self.factory() as s:
            pending = select(Row.message_id).where(Row.run_id == run_id,
                Row.payload_json['tier'].as_integer() == tier, Row.status.not_in(['SUCCEEDED','SUPERSEDED']))
            if current_id:
                pending = pending.where(Row.message_id != current_id)
            return s.scalar(pending.limit(1)) is None

    def status(self, run_id):
        with self.factory() as s:
            counts = dict(s.execute(select(Row.status, func.count()).where(Row.run_id == run_id).group_by(Row.status)).all())
            return {name.lower(): counts.get(name, 0) for name in ('QUEUED', 'RUNNING', 'SUCCEEDED', 'DEAD', 'SUPERSEDED')}

