"""Durable execution for trusted, versioned adapters; never executes user supplied code.

DB_ATOMIC steps commit their effect, checkpoint and evidence together. External
dispatch is recorded *before* invoking the adapter; ambiguous outcomes are only
reconciled, never automatically resent. A database lease is not an external fence.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass, fields, is_dataclass, replace
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import uuid
from typing import Callable, Mapping

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from go_hotel.db.models import (
    AutonomyCellControlRow as Control, AutonomyEventRow as Event,
    AutonomyQualificationRow as Qualification, AutonomyStepRow as Step,
    AutonomyTaskRow as Task,
)
from .action_control import AILegalPolicyRegistry, AuthorityConstitutionGate, evaluate_ai_action
from .definitions import ALL_CELL_REGISTRY
from .policy import RiskFactors
from .registry import AutonomyQualificationRegistry, GovernanceViolation
from .types import (
    AIActionEnvelope, Environment, LegalDecision, LegalExposureProfile,
    ProductionReality, QualificationEvidence, QualificationKey,
    QualificationRecord, RiskClass,
)


class ExecutionError(RuntimeError):
    pass


class RetryableStepError(ExecutionError):
    """A local transactional step rolled back and may be retried."""


class LostLease(ExecutionError):
    pass


class AuthorityLost(ExecutionError):
    """Local effects must roll back when execution authority lapses mid-step."""


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def digest(value) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


_PG_CLOCK = select(func.extract('epoch', func.clock_timestamp()))
_SQLITE_CLOCK = select((func.julianday('now') - 2440587.5) * 86400000)

def db_now_ms(s: Session) -> int:
    # Cache the expression, not database time. Each call executes the clock
    # again; leases and reservation deadlines must never reuse an earlier value.
    if s.bind.dialect.name == 'postgresql':
        return int(s.scalar(_PG_CLOCK) * 1000)
    return int(s.scalar(_SQLITE_CLOCK))


def utc_ms(value):
    return datetime.fromtimestamp(value / 1000, timezone.utc)


def record_primitive(value):
    # dataclasses.asdict deep-copies MappingProxyType; immutable authority records
    # deliberately cannot be deep-copied. Serialize their public fields explicitly.
    if is_dataclass(value):
        return {f.name: record_primitive(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {k: record_primitive(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [record_primitive(v) for v in value]
    return value


def insert_once(s, model, values, keys):
    factory = pg_insert if s.bind.dialect.name == 'postgresql' else sqlite_insert
    s.execute(factory(model).values(**values).on_conflict_do_nothing(index_elements=keys))


@contextmanager
def transaction(factory):
    with factory() as s:
        if s.bind.dialect.name not in {'sqlite', 'postgresql'}:
            raise ExecutionError('UNSUPPORTED_EXECUTION_DATABASE')
        # SQLite's deferred read-to-write upgrade is not a row lock. Reserve the
        # writer before reading. PostgreSQL locks selected rows instead.
        if s.bind.dialect.name == 'sqlite':
            s.execute(text('BEGIN IMMEDIATE'))
        try:
            yield s
            s.commit()
        except BaseException:
            s.rollback()
            raise


class DurableQualifications:
    """Use inside the caller's transaction so revocation serializes with steps.

    qualify/revoke are trusted governance integration methods, not task handlers
    or public HTTP endpoints. Existing C13 independent validation rules apply.
    """
    def __init__(self, session, cells=ALL_CELL_REGISTRY):
        self.s, self.cells = session, cells

    @staticmethod
    def key_id(key):
        return digest(asdict(key))

    def get(self, key):
        row = self.s.scalar(select(Qualification).where(
            Qualification.qualification_id == self.key_id(key)).with_for_update())
        if row is None:
            return None
        return self._decode(row, key)

    def _decode(self, row, key):
        data = dict(row.record_json)
        k = data.pop('key')
        evidence = data.pop('evidence')
        for name in ('valid_from', 'valid_until'):
            if data.get(name) is not None:
                data[name] = datetime.fromisoformat(data[name])
        record = QualificationRecord(
            key=QualificationKey(k['cell_id'], k['capability'], RiskClass(k['risk_class']), Environment(k['environment'])),
            evidence=QualificationEvidence(**evidence),
            **{**data, 'reality': ProductionReality(data['reality'])},
        )
        if record.key != key:
            raise GovernanceViolation('QUALIFICATION_SCOPE_INTEGRITY_FAILURE')
        # Revalidate against the currently installed ownership/policy registry.
        AutonomyQualificationRegistry(cells=self.cells).qualify(record)
        return record

    def current_denial(self, key, *, at, policy_version):
        row = self.s.scalar(select(Qualification).where(
            Qualification.qualification_id == self.key_id(key)).with_for_update())
        if row is None:
            return 'AUTONOMY_QUALIFICATION_MISSING'
        registry = AutonomyQualificationRegistry(cells=self.cells)
        registry.qualify(self._decode(row, key))
        # Both the persisted TTL and the approved window constrain execution.
        # Legacy JSON with no approved window remains HOLD, never backdated.
        now = db_now_ms(self.s)
        denial = registry.current_denial(key, at=max(at, utc_ms(now)), policy_version=policy_version)
        return denial or ('AUTONOMY_QUALIFICATION_EXPIRED' if row.expires_ms <= now else None)

    def qualify(self, record, *, expires_ms, expected_revision=0):
        now = db_now_ms(self.s)
        if type(expires_ms) is not int or not record.evidence.evidence_refs or expires_ms <= now:
            raise GovernanceViolation('DATED_QUALIFICATION_EVIDENCE_REQUIRED')
        # This trusted registration call is a new observed event. It may start a
        # new window now, but reading an old record must never invent one.
        if record.valid_from is None and record.valid_until is None:
            record = replace(record, valid_from=utc_ms(now), valid_until=utc_ms(expires_ms))
        registry = AutonomyQualificationRegistry(cells=self.cells)
        registry.qualify(record)
        if int(record.valid_until.timestamp() * 1000) != expires_ms:
            raise GovernanceViolation('QUALIFICATION_EXPIRY_SCOPE_MISMATCH')
        key_id = self.key_id(record.key)
        insert_once(self.s, Qualification, dict(qualification_id=key_id, record_json={},
                    expires_ms=0, revision=0, updated_ms=db_now_ms(self.s)), ['qualification_id'])
        row = self.s.scalar(select(Qualification).where(Qualification.qualification_id == key_id).with_for_update())
        if row.revision != expected_revision:
            raise GovernanceViolation('QUALIFICATION_REVISION_CONFLICT')
        if row.revision:
            previous = self._decode(row, record.key)
            registry = AutonomyQualificationRegistry(cells=self.cells)
            registry.qualify(previous)
            registry.qualify(record)
        row.record_json, row.expires_ms = json.loads(canonical(record_primitive(record))), expires_ms
        row.revision += 1
        row.updated_ms = db_now_ms(self.s)
        self.s.flush()
        return row.revision

    def revoke(self, key, *, reason, expected_revision):
        row = self.s.scalar(select(Qualification).where(
            Qualification.qualification_id == self.key_id(key)).with_for_update())
        if row is None or row.revision != expected_revision:
            raise GovernanceViolation('QUALIFICATION_REVISION_CONFLICT')
        row.record_json = {**row.record_json, 'reality': ProductionReality.RESTRICTED.value,
                           'metadata': {**row.record_json.get('metadata', {}), 'revocation_reason': reason}}
        row.revision += 1
        row.updated_ms = db_now_ms(self.s)
        self.s.flush()


@dataclass(frozen=True)
class StepContext:
    task_id: str
    cell_id: str
    environment: str
    payload: dict
    previous: tuple[dict, ...]
    execute: Callable


@dataclass(frozen=True)
class ExternalContext:
    operation_key: str
    cell_id: str
    environment: str
    payload: dict


@dataclass(frozen=True)
class ReconciledResult:
    # No NOT_APPLIED retry: an old worker may still dispatch after a timeout.
    state: str  # SUCCEEDED, FAILED (authoritative terminal result), or UNKNOWN
    operation_key: str
    evidence_reference: str
    result: dict


@dataclass(frozen=True)
class Handler:
    operation: str
    version: str
    cell_id: str
    capability: str
    steps: tuple[Callable[[StepContext], dict], ...] = ()
    mode: str = 'DB_ATOMIC'
    risk: RiskFactors = RiskFactors(0, 0, 0, 0, 0, 0, 0, 0, 0)
    exposure: LegalExposureProfile = LegalExposureProfile()
    truth_mutation: bool = False
    autonomous: bool = False
    target_domain: str | None = None
    jurisdiction: str | None = None
    dispatch: Callable[[ExternalContext], dict] | None = None
    reconcile: Callable[[ExternalContext], ReconciledResult] | None = None

    def contract(self):
        return {'operation': self.operation, 'version': self.version, 'cell_id': self.cell_id,
                'capability': self.capability, 'mode': self.mode, 'steps': len(self.steps),
                'risk': asdict(self.risk), 'exposure': asdict(self.exposure),
                'truth_mutation': self.truth_mutation, 'autonomous': self.autonomous,
                'target_domain': self.target_domain, 'jurisdiction': self.jurisdiction}


@dataclass(frozen=True)
class Claim:
    task_id: str
    token: str
    attempt: int


class DurableExecutor:
    def __init__(self, sessions, handlers, *, environment: Environment,
                 authorize_actor: Callable[[Session, str], bool],
                 lease_ms=30000, retry_ms=1000, legal_registry=None, condition_resolver=None):
        if not isinstance(environment, Environment) or not 100 <= lease_ms <= 300000 or not 0 <= retry_ms <= 3600000:
            raise ValueError('INVALID_EXECUTOR_CONFIGURATION')
        self.sessions, self.environment = sessions, environment
        self.authorize_actor = authorize_actor
        self.lease_ms, self.retry_ms = lease_ms, retry_ms
        self.legal = legal_registry or AILegalPolicyRegistry()
        self.condition_resolver = condition_resolver
        self.handlers = {}
        for h in handlers:
            ALL_CELL_REGISTRY.cell(h.cell_id)
            if h.operation in self.handlers or not h.version:
                raise ValueError('DUPLICATE_OR_UNVERSIONED_HANDLER')
            if h.mode == 'DB_ATOMIC' and not h.steps:
                raise ValueError('TRANSACTIONAL_STEPS_REQUIRED')
            if h.mode == 'EXTERNAL' and (h.dispatch is None or h.reconcile is None or h.steps):
                raise ValueError('EXTERNAL_DISPATCH_AND_RECONCILIATION_REQUIRED')
            if h.mode not in {'DB_ATOMIC', 'EXTERNAL'}:
                raise ValueError('UNSUPPORTED_HANDLER_MODE')
            self.handlers[h.operation] = h

    def _handler(self, row):
        h = self.handlers.get(row.operation)
        if h is None or digest(h.contract()) != row.handler_version:
            raise ExecutionError('HANDLER_VERSION_UNAVAILABLE')
        if digest([row.payload_json, row.submitted_by, h.contract(), row.max_attempts]) != row.request_hash:
            raise ExecutionError('TASK_REQUEST_INTEGRITY_FAILURE')
        return h

    def _event(self, s, row, kind, actor, **details):
        row.event_seq += 1
        s.add(Event(event_id=uuid.uuid4().hex, task_id=row.task_id, environment=row.environment,
                    cell_id=row.cell_id, event_type=kind, actor_id=actor,
                    details_json=details, sequence=row.event_seq, created_ms=db_now_ms(s)))

    def _control(self, s, cell_id, actor):
        insert_once(s, Control, dict(environment=self.environment.value, cell_id=cell_id,
                    paused=False, version=1, updated_by=actor, updated_ms=db_now_ms(s)), ['environment', 'cell_id'])
        return s.scalar(select(Control).where(Control.environment == self.environment.value,
                        Control.cell_id == cell_id).with_for_update())

    def _authorize(self, s, row, h):
        if row.environment != self.environment.value or h.cell_id != row.cell_id:
            return 'EXECUTION_SCOPE_MISMATCH'
        if not self.authorize_actor(s, row.submitted_by):
            return 'SUBMITTER_AUTHORITY_REVOKED'
        if self._control(s, row.cell_id, row.submitted_by).paused:
            return 'CELL_PAUSED'
        # Production accountability remains unbound in the frozen baseline.
        if self.environment in {Environment.PRODUCTION, Environment.CANARY}:
            return 'PRODUCTION_EXECUTION_NOT_CERTIFIED'
        action = AIActionEnvelope(row.task_id, h.cell_id, h.capability,
                   h.target_domain or ALL_CELL_REGISTRY.cell(h.cell_id).domain,
                   self.environment, h.risk, h.exposure, jurisdiction=h.jurisdiction,
                   truth_mutation=h.truth_mutation, require_autonomous_execution=h.autonomous,
                   metadata={'request_hash': row.request_hash, 'handler_hash': row.handler_version,
                             'step_no': str(row.next_step)})
        try:
            result = evaluate_ai_action(action,
                authority_gate=AuthorityConstitutionGate(ALL_CELL_REGISTRY, DurableQualifications(s)),
                legal_registry=self.legal, condition_resolver=self.condition_resolver,
                clock=lambda: utc_ms(db_now_ms(s)))
        except (GovernanceViolation, ValueError, TypeError, KeyError):
            return 'QUALIFICATION_INVALID'
        self._event(s, row, 'C14_REVIEW', row.submitted_by, authority=result.authority.code,
                    legal=result.legal.decision.value if result.legal else None,
                    policy_rules=list(result.legal.policy_rule_ids) if result.legal else [],
                    evidence_refs=list(result.condition_evidence_refs),
                    blocked_conditions=list(result.blocked_conditions),
                    request_hash=row.request_hash, handler_hash=row.handler_version, step_no=row.next_step)
        if not result.executable:
            if result.blocked_conditions:
                return 'LEGAL_CONDITIONS_UNSATISFIED'
            return result.authority.code if not result.authority.allowed else result.legal.decision.value
        return None

    @staticmethod
    def snapshot(row):
        return {k: getattr(row, k) for k in ('task_id', 'environment', 'cell_id', 'operation',
                'handler_version', 'status', 'attempt', 'max_attempts', 'next_step',
                'available_ms', 'lease_until_ms', 'worker_id', 'last_code',
                'result_json', 'created_ms', 'updated_ms')}

    def submit(self, operation, *, idempotency_key, submitted_by, payload=None, max_attempts=5):
        h = self.handlers.get(operation)
        if h is None:
            raise ExecutionError('OPERATION_NOT_ALLOWLISTED')
        if not isinstance(idempotency_key, str) or not 1 <= len(idempotency_key) <= 160 or not submitted_by or len(submitted_by) > 64:
            raise ExecutionError('INVALID_TASK_IDENTITY')
        if type(max_attempts) is not int or not 1 <= max_attempts <= 20 or (payload is not None and type(payload) is not dict):
            raise ExecutionError('INVALID_TASK_INPUT')
        body = json.loads(canonical(payload or {}))
        if len(canonical(body).encode()) > 32768:
            raise ExecutionError('TASK_PAYLOAD_TOO_LARGE')
        task_id = digest([self.environment.value, h.cell_id, operation, idempotency_key])
        request_hash = digest([body, submitted_by, h.contract(), max_attempts])
        with transaction(self.sessions) as s:
            now = db_now_ms(s)
            insert_once(s, Task, dict(task_id=task_id, environment=self.environment.value,
                cell_id=h.cell_id, operation=operation, handler_version=digest(h.contract()),
                request_hash=request_hash, submitted_by=submitted_by, payload_json=body,
                status='QUEUED', attempt=0, max_attempts=max_attempts, next_step=0, event_seq=0,
                available_ms=now, external_started=False, created_ms=now, updated_ms=now), ['task_id'])
            row = s.scalar(select(Task).where(Task.task_id == task_id).with_for_update())
            # Match execution's lock order: task -> actor -> cell -> qualification.
            # Rejected submissions roll back the insert; no unauthorized task persists.
            if not self.authorize_actor(s, submitted_by):
                raise ExecutionError('SUBMITTER_NOT_AUTHORIZED')
            if row.request_hash != request_hash:
                raise ExecutionError('IDEMPOTENCY_CONFLICT')
            # Replays return the original result/state, including cancelled/dead
            # tasks. They cannot create a new execution or reset retry budgets.
            if not s.scalar(select(Event.event_id).where(Event.task_id == task_id).limit(1)):
                blocked = self._authorize(s, row, h)
                if blocked:
                    row.status, row.last_code = 'HOLD', blocked
                self._event(s, row, 'SUBMITTED', submitted_by, request_hash=request_hash)
            s.flush()
            return self.snapshot(row)

    def _get(self, s, task_id, lock=False):
        stmt = select(Task).where(Task.task_id == task_id, Task.environment == self.environment.value)
        row = s.scalar(stmt.with_for_update() if lock else stmt)
        if row is None:
            raise ExecutionError('TASK_NOT_FOUND')
        return row

    def _leased(self, s, claim):
        row = self._get(s, claim.task_id, lock=True)
        if row.status != 'RUNNING' or row.lease_token != claim.token or row.attempt != claim.attempt or (row.lease_until_ms or 0) <= db_now_ms(s):
            raise LostLease('LEASE_EXPIRED_OR_REPLACED')
        return row

    def _finish(self, s, row, status, code, actor):
        row.status, row.last_code, row.updated_ms = status, code, db_now_ms(s)
        row.lease_token, row.lease_until_ms, row.worker_id = None, None, None
        self._event(s, row, status, actor, code=code, attempt=row.attempt, next_step=row.next_step)

    def recover_expired(self, limit=100):
        with transaction(self.sessions) as s:
            rows = s.scalars(select(Task).where(Task.environment == self.environment.value,
                    Task.status == 'RUNNING', Task.lease_until_ms <= db_now_ms(s))
                    .order_by(Task.lease_until_ms, Task.task_id).limit(min(max(limit, 1), 1000))
                    .with_for_update(skip_locked=True)).all()
            for row in rows:
                status = 'UNCERTAIN' if row.external_started else ('DEAD' if row.attempt >= row.max_attempts else 'RETRY_WAIT')
                self._finish(s, row, status, 'WORKER_LEASE_EXPIRED', 'recovery')
                row.available_ms = db_now_ms(s) + self.retry_ms
            return len(rows)

    def claim(self, worker_id, *, cell_id=None):
        if not worker_id or len(worker_id) > 128:
            raise ExecutionError('INVALID_WORKER_ID')
        if cell_id is not None:
            ALL_CELL_REGISTRY.cell(cell_id)
        self.recover_expired()
        with transaction(self.sessions) as s:
            stmt = select(Task).where(Task.environment == self.environment.value,
                Task.status.in_(['QUEUED', 'RETRY_WAIT']), Task.available_ms <= db_now_ms(s))
            if cell_id is not None:
                stmt = stmt.where(Task.cell_id == cell_id)
            row = s.scalar(stmt.order_by(Task.available_ms, Task.created_ms, Task.task_id).limit(1).with_for_update(skip_locked=True))
            if row is None:
                return None
            if row.attempt >= row.max_attempts:
                self._finish(s, row, 'DEAD', 'ATTEMPTS_EXHAUSTED', worker_id)
                return None
            row.status, row.lease_token, row.worker_id = 'RUNNING', uuid.uuid4().hex, worker_id
            row.attempt += 1
            row.updated_ms = db_now_ms(s)
            row.lease_until_ms = row.updated_ms + self.lease_ms
            self._event(s, row, 'CLAIMED', worker_id, attempt=row.attempt)
            return Claim(row.task_id, row.lease_token, row.attempt)

    def heartbeat(self, claim):
        with transaction(self.sessions) as s:
            row = self._leased(s, claim)
            row.lease_until_ms = db_now_ms(s) + self.lease_ms
            return row.lease_until_ms

    def run_step(self, claim):
        """One bounded DB step. Process death rolls back effects before checkpoint."""
        try:
            with transaction(self.sessions) as s:
                row = self._leased(s, claim)
                h = self._handler(row)
                if h.mode != 'DB_ATOMIC':
                    raise ExecutionError('USE_EXTERNAL_DISPATCH')
                blocked = self._authorize(s, row, h)
                if blocked:
                    self._finish(s, row, 'HOLD', blocked, row.worker_id)
                    return self.snapshot(row)
                prior = s.scalars(select(Step).where(Step.task_id == row.task_id).order_by(Step.step_no)).all()
                if len(prior) != row.next_step or [p.step_no for p in prior] != list(range(row.next_step)) or any(digest(p.result_json) != p.result_hash for p in prior):
                    raise ExecutionError('CHECKPOINT_INTEGRITY_FAILURE')
                context = StepContext(row.task_id, row.cell_id, row.environment,
                                      json.loads(canonical(row.payload_json)), tuple(p.result_json for p in prior), s.execute)
                result = h.steps[row.next_step](context)
                if type(result) is not dict or len(canonical(result).encode()) > 65536:
                    raise ExecutionError('INVALID_STEP_RESULT')
                # A long-running local step cannot commit after its lease expires.
                if row.lease_until_ms <= db_now_ms(s):
                    raise LostLease('LEASE_EXPIRED_DURING_STEP')
                blocked = self._authorize(s, row, h)
                if blocked:
                    raise AuthorityLost(blocked)
                s.add(Step(task_id=row.task_id, step_no=row.next_step, result_json=result,
                           result_hash=digest(result), completed_ms=db_now_ms(s)))
                row.next_step += 1
                row.result_json = result
                row.updated_ms = db_now_ms(s)
                self._event(s, row, 'CHECKPOINT', row.worker_id, next_step=row.next_step, result_hash=digest(result))
                if row.next_step == len(h.steps):
                    self._finish(s, row, 'SUCCEEDED', 'TRANSACTION_COMMITTED', row.worker_id)
                else:
                    row.lease_until_ms = db_now_ms(s) + self.lease_ms
                s.flush()
                return self.snapshot(row)
        except LostLease:
            raise
        except Exception as exc:
            return self._failed_step(claim, exc)

    def _failed_step(self, claim, exc):
        with transaction(self.sessions) as s:
            row = self._leased(s, claim)
            retry = isinstance(exc, RetryableStepError)
            code = str(exc) if isinstance(exc, ExecutionError) else type(exc).__name__
            code = code[:128]
            status = ('RETRY_WAIT' if row.attempt < row.max_attempts else 'DEAD') if retry else 'FAILED'
            if code == 'HANDLER_VERSION_UNAVAILABLE' or isinstance(exc, AuthorityLost):
                status = 'HOLD'
            self._finish(s, row, status, code, row.worker_id)
            row.available_ms = db_now_ms(s) + min(self.retry_ms * (2 ** (row.attempt - 1)), 3600000)
            return self.snapshot(row)

    def dispatch_external(self, claim):
        with transaction(self.sessions) as s:
            row = self._leased(s, claim)
            h = self._handler(row)
            if h.mode != 'EXTERNAL' or row.external_started:
                raise ExecutionError('EXTERNAL_DISPATCH_NOT_ALLOWED')
            blocked = self._authorize(s, row, h)
            if blocked:
                self._finish(s, row, 'HOLD', blocked, row.worker_id)
                return self.snapshot(row)
            row.external_started = True
            ctx = ExternalContext(row.task_id, row.cell_id, row.environment, row.payload_json)
            self._event(s, row, 'EXTERNAL_DISPATCH_INTENT', row.worker_id, operation_key=row.task_id)
        try:
            result = h.dispatch(ctx)
            if type(result) is not dict or len(canonical(result).encode()) > 65536:
                raise ExecutionError('INVALID_EXTERNAL_RESULT')
        except Exception:
            # Includes network timeout and adapter bugs. No speculative resend.
            with transaction(self.sessions) as s:
                row = self._leased(s, claim)
                self._finish(s, row, 'UNCERTAIN', 'EXTERNAL_RESULT_UNKNOWN', row.worker_id)
                return self.snapshot(row)
        with transaction(self.sessions) as s:
            row = self._leased(s, claim)
            row.result_json = result
            self._finish(s, row, 'SUCCEEDED', 'EXTERNAL_RESULT_RECORDED', row.worker_id)
            return self.snapshot(row)

    def reconcile_external(self, task_id, *, actor):
        # Adapter contract is read-only, operation-key-bound provider lookup.
        # It cannot claim NOT_APPLIED and thereby race a delayed old dispatch.
        with transaction(self.sessions) as s:
            row = self._get(s, task_id, lock=True)
            if not self.authorize_actor(s, actor):
                raise ExecutionError('OPERATOR_NOT_AUTHORIZED')
            if row.status != 'UNCERTAIN' or not row.external_started:
                raise ExecutionError('TASK_NOT_UNCERTAIN')
            h = self._handler(row)
            if h.mode != 'EXTERNAL':
                raise ExecutionError('NOT_EXTERNAL')
            blocked = self._authorize(s, row, h)
            if blocked:
                self._event(s, row, 'RECONCILIATION_HOLD', actor, code=blocked)
                return self.snapshot(row)
            result = h.reconcile(ExternalContext(row.task_id, row.cell_id, row.environment, row.payload_json))
            if not isinstance(result, ReconciledResult) or result.operation_key != row.task_id:
                raise ExecutionError('RECONCILIATION_SCOPE_MISMATCH')
            if result.state not in {'SUCCEEDED', 'FAILED', 'UNKNOWN'}:
                raise ExecutionError('INVALID_RECONCILIATION_STATE')
            if result.state != 'UNKNOWN':
                if not result.evidence_reference or type(result.result) is not dict or len(canonical(result.result).encode()) > 65536:
                    raise ExecutionError('RECONCILIATION_EVIDENCE_REQUIRED')
                row.result_json = result.result
                self._finish(s, row, result.state, 'AUTHORITATIVE_RECONCILIATION', actor)
            self._event(s, row, 'RECONCILED', actor, state=result.state, evidence_reference=result.evidence_reference)
            return self.snapshot(row)

    def run_once(self, worker_id, *, cell_id=None):
        claim = self.claim(worker_id, cell_id=cell_id)
        if claim is None:
            return None
        try:
            with self.sessions() as s:
                h = self._handler(self._get(s, claim.task_id))
            if h.mode == 'EXTERNAL':
                return self.dispatch_external(claim)
            while True:
                state = self.run_step(claim)
                if state['status'] != 'RUNNING':
                    return state
        except LostLease:
            return self.inspect(claim.task_id)
        except ExecutionError as exc:
            return self._failed_step(claim, exc)

    def set_paused(self, cell_id, *, paused, actor, expected_version):
        ALL_CELL_REGISTRY.cell(cell_id)
        with transaction(self.sessions) as s:
            if not self.authorize_actor(s, actor):
                raise ExecutionError('OPERATOR_NOT_AUTHORIZED')
            row = self._control(s, cell_id, actor)
            if row.version != expected_version:
                raise ExecutionError('CELL_CONTROL_VERSION_CONFLICT')
            row.paused, row.updated_by, row.updated_ms = bool(paused), actor, db_now_ms(s)
            row.version += 1
            s.add(Event(event_id=uuid.uuid4().hex, environment=self.environment.value, cell_id=cell_id,
                        task_id=None, event_type='CELL_PAUSED' if paused else 'CELL_RESUMED',
                        actor_id=actor, details_json={'version': row.version}, sequence=row.version, created_ms=row.updated_ms))
            return {'cell_id': cell_id, 'paused': row.paused, 'version': row.version}

    def resume(self, task_id, *, actor):
        with transaction(self.sessions) as s:
            row = self._get(s, task_id, lock=True)
            if not self.authorize_actor(s, actor):
                raise ExecutionError('OPERATOR_NOT_AUTHORIZED')
            if row.status != 'HOLD' or row.external_started or row.attempt >= row.max_attempts:
                raise ExecutionError('TASK_NOT_RESUMABLE')
            h = self._handler(row)
            blocked = self._authorize(s, row, h)
            if blocked:
                row.last_code = blocked
            else:
                row.status, row.last_code, row.available_ms = 'QUEUED', None, db_now_ms(s)
                self._event(s, row, 'RESUMED', actor, attempt=row.attempt)
            row.updated_ms = db_now_ms(s)
            return self.snapshot(row)

    def cancel(self, task_id, *, actor):
        with transaction(self.sessions) as s:
            row = self._get(s, task_id, lock=True)
            if not self.authorize_actor(s, actor):
                raise ExecutionError('OPERATOR_NOT_AUTHORIZED')
            if row.external_started or row.status not in {'QUEUED', 'RETRY_WAIT', 'HOLD', 'RUNNING'}:
                raise ExecutionError('TASK_NOT_CANCELLABLE')
            self._finish(s, row, 'CANCELLED', 'OPERATOR_CANCELLED', actor)
            return self.snapshot(row)

    def inspect(self, task_id):
        with self.sessions() as s:
            row = self._get(s, task_id)
            out = self.snapshot(row)
            out['events'] = [{'sequence': e.sequence, 'event_type': e.event_type, 'actor_id': e.actor_id, 'details': e.details_json,
                              'created_ms': e.created_ms} for e in s.scalars(select(Event).where(
                              Event.task_id == task_id).order_by(Event.sequence))]
            out['checkpoints'] = [{'step_no': p.step_no, 'result_hash': p.result_hash, 'result': p.result_json}
                                 for p in s.scalars(select(Step).where(Step.task_id == task_id).order_by(Step.step_no))]
            return out

    def list_tasks(self, *, cell_id=None, limit=100):
        with self.sessions() as s:
            stmt = select(Task).where(Task.environment == self.environment.value)
            if cell_id:
                stmt = stmt.where(Task.cell_id == cell_id)
            return [self.snapshot(r) for r in s.scalars(stmt.order_by(Task.created_ms.desc(), Task.task_id).limit(min(max(limit, 1), 200)))]

    def cells(self):
        with self.sessions() as s:
            rows = {r.cell_id: r for r in s.scalars(select(Control).where(Control.environment == self.environment.value))}
            counts = {(c, state): n for c, state, n in s.execute(select(Task.cell_id, Task.status, func.count())
                      .where(Task.environment == self.environment.value).group_by(Task.cell_id, Task.status))}
            return [{'cell_id': c.cell_id, 'name': c.name, 'domain': c.domain,
                'paused': rows[c.cell_id].paused if c.cell_id in rows else False,
                'control_version': rows[c.cell_id].version if c.cell_id in rows else 1,
                'operations': [h.operation for h in self.handlers.values() if h.cell_id == c.cell_id],
                'tasks': {state: n for (cell, state), n in counts.items() if cell == c.cell_id}}
                for c in ALL_CELL_REGISTRY.cells.values()]
