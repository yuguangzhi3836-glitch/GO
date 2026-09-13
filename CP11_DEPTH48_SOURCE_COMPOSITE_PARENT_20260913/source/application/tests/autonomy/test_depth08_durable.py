"""Real file-database, thread and killed-process evidence for DEPTH08.

The same matrix can run on an explicitly supplied local PostgreSQL test DB via
GO_DEPTH08_TEST_DATABASE_URL. Each test owns a fresh schema. No public schema or
existing application database is reset by this suite.
"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import multiprocessing
import os
import threading
import uuid

import pytest
from sqlalchemy import create_engine, func, select, text, update
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from go_hotel.autonomy import ALL_CELL_REGISTRY, Environment, RiskFactors
from go_hotel.autonomy.action_control import AILegalPolicyRegistry, LegalPolicyRule
from go_hotel.autonomy.durable import (
    Claim, DurableExecutor, DurableQualifications, ExecutionError, Handler,
    LostLease, ReconciledResult, RetryableStepError, db_now_ms, transaction,
)
from go_hotel.autonomy.types import (
    LegalDecision, LegalExposureProfile, ProductionReality, QualificationEvidence,
    QualificationKey, QualificationRecord, RiskClass,
)
from go_hotel.db.models import Base, AutonomyTaskRow as Task, AutonomyStepRow as Step

pytestmark = pytest.mark.no_db
TABLES = [Base.metadata.tables[n] for n in ('autonomy_cell_control', 'autonomy_qualification',
          'autonomy_task', 'autonomy_step', 'autonomy_event')]


def actor_check(s, actor):
    return actor == 'operator' and s.scalar(text('SELECT active FROM test_operator')) == 1


def make_runtime(url, *, cell='C01', steps=None, max_lease=30000, retry=0, **overrides):
    engine = create_engine(url, connect_args={'timeout': 15} if make_url(url).get_backend_name() == 'sqlite' else {})
    sessions = sessionmaker(engine, expire_on_commit=False)
    definition = ALL_CELL_REGISTRY.cell(cell)
    def effect(ctx):
        ctx.execute(text('INSERT INTO test_effect(task_id, step_no, value) VALUES (:id,:step,1)'),
                    {'id': ctx.task_id, 'step': len(ctx.previous)})
        return {'effect': len(ctx.previous), 'cell_id': ctx.cell_id}
    handler = Handler('test.' + cell, 'test-v1', cell, sorted(definition.capabilities)[0], steps=(effect, effect) if steps is None else steps)
    handler = replace(handler, **overrides)
    runtime = DurableExecutor(sessions, (handler,), environment=Environment.TEST,
                   authorize_actor=actor_check, lease_ms=max_lease, retry_ms=retry)
    return runtime


@pytest.fixture
def db_url(tmp_path):
    supplied = os.getenv('GO_DEPTH08_TEST_DATABASE_URL')
    admin = None
    if supplied:
        url = make_url(supplied)
        if url.get_backend_name() != 'postgresql' or url.host not in {'localhost', '127.0.0.1', '::1'} or not (url.database or '').endswith('_test'):
            pytest.fail('Only an explicitly isolated local PostgreSQL *_test database is accepted')
        schema = 'depth08_' + uuid.uuid4().hex
        admin = create_engine(url)
        with admin.begin() as conn:
            conn.execute(text('CREATE SCHEMA ' + schema))
        target = url.update_query_dict({'options': '-csearch_path=' + schema}).render_as_string(hide_password=False)
    else:
        target = 'sqlite+pysqlite:///' + str(tmp_path / 'execution.db')
    engine = create_engine(target)
    Base.metadata.create_all(engine, tables=TABLES)
    with engine.begin() as conn:
        conn.execute(text('CREATE TABLE test_effect(task_id varchar(64), step_no integer, value integer, PRIMARY KEY(task_id,step_no))'))
        conn.execute(text('CREATE TABLE test_operator(active integer)'))
        conn.execute(text('INSERT INTO test_operator VALUES(1)'))
    engine.dispose()
    yield target
    if admin:
        with admin.begin() as conn:
            conn.execute(text('DROP SCHEMA ' + schema + ' CASCADE'))
        admin.dispose()


def submit(rt, key='one', **kwargs):
    return rt.submit(next(iter(rt.handlers)), idempotency_key=key, submitted_by='operator', **kwargs)


def expire(rt, task_id):
    with transaction(rt.sessions) as s:
        s.execute(update(Task).where(Task.task_id == task_id).values(lease_until_ms=0))


def effects(rt):
    with rt.sessions() as s:
        return s.execute(text('SELECT task_id,step_no,value FROM test_effect ORDER BY task_id,step_no')).all()


@pytest.mark.parametrize('cell', ['C%02d' % n for n in range(1, 15)])
def test_every_cell_persists_and_resumes_committed_step_without_duplicate(db_url, cell):
    rt = make_runtime(db_url, cell=cell)
    task = submit(rt)
    claim = rt.claim('worker-a')
    assert rt.run_step(claim)['next_step'] == 1
    assert len(effects(rt)) == 1
    expire(rt, task['task_id'])
    # New executor and new engine, with no in-memory execution state.
    restored = make_runtime(db_url, cell=cell)
    assert restored.run_once('worker-b')['status'] == 'SUCCEEDED'
    with pytest.raises(LostLease):
        rt.run_step(claim)
    final = restored.inspect(task['task_id'])
    assert final['attempt'] == 2 and final['next_step'] == 2
    assert len(final['checkpoints']) == len(effects(rt)) == 2
    assert [e['sequence'] for e in final['events']] == list(range(1, len(final['events']) + 1))
    # Submission plus pre/post review of each of the two committed steps.
    assert sum(e['event_type'] == 'C14_REVIEW' for e in final['events']) == 5
    assert submit(restored)['task_id'] == task['task_id']
    assert restored.run_once('worker-c') is None


@pytest.mark.parametrize('field,value', [('payload', {'changed': True}), ('max_attempts', 3)])
def test_same_key_cannot_change_request(db_url, field, value):
    rt = make_runtime(db_url)
    submit(rt)
    with pytest.raises(ExecutionError, match='IDEMPOTENCY_CONFLICT'):
        submit(rt, **{field: value})
    assert len(rt.list_tasks()) == 1


def test_parallel_submit_and_claim_have_one_effect(db_url):
    rt = make_runtime(db_url)
    barrier = threading.Barrier(6)
    def producer(_):
        barrier.wait(10)
        return submit(make_runtime(db_url))['task_id']
    with ThreadPoolExecutor(6) as pool:
        ids = list(pool.map(producer, range(6)))
    assert len(set(ids)) == 1
    with ThreadPoolExecutor(6) as pool:
        results = list(pool.map(lambda n: make_runtime(db_url).run_once('w' + str(n)), range(6)))
    assert sum(r is not None for r in results) == 1
    assert len(effects(rt)) == 2
    assert rt.inspect(ids[0])['attempt'] == 1


def test_retry_rolls_back_effect_and_stops_at_budget(db_url):
    def fail(ctx):
        ctx.execute(text('INSERT INTO test_effect VALUES (:id,0,1)'), {'id': ctx.task_id})
        raise RetryableStepError('INJECTED_TRANSACTION_FAILURE')
    rt = make_runtime(db_url, steps=(fail,))
    task = submit(rt, max_attempts=2)
    assert rt.run_once('a')['status'] == 'RETRY_WAIT'
    assert effects(rt) == []
    assert rt.run_once('b')['status'] == 'DEAD'
    assert submit(rt, max_attempts=2)['status'] == 'DEAD'
    with pytest.raises(ExecutionError, match='TASK_NOT_RESUMABLE'):
        rt.resume(task['task_id'], actor='operator')
    assert rt.run_once('c') is None


def test_retry_has_persisted_backoff(db_url):
    def fail(_):
        raise RetryableStepError('TRY_LATER')
    rt = make_runtime(db_url, steps=(fail,), retry=5000)
    submit(rt)
    result = rt.run_once('a')
    assert result['available_ms'] >= result['updated_ms'] + 5000
    assert make_runtime(db_url, steps=(fail,)).claim('b') is None


def test_unknown_handler_and_new_version_hold_existing_task(db_url):
    rt = make_runtime(db_url)
    task = submit(rt)
    changed = make_runtime(db_url, version='test-v2')
    assert changed.run_once('b')['status'] == 'HOLD'
    assert changed.inspect(task['task_id'])['last_code'] == 'HANDLER_VERSION_UNAVAILABLE'
    assert effects(rt) == []
    with pytest.raises(ExecutionError, match='OPERATION_NOT_ALLOWLISTED'):
        rt.submit('shell', idempotency_key='x', submitted_by='operator', payload={'cmd': 'echo unsafe'})


def test_pause_resume_and_cancel_fence_old_worker(db_url):
    rt = make_runtime(db_url)
    task = submit(rt)
    claim = rt.claim('a')
    rt.set_paused('C01', paused=True, actor='operator', expected_version=1)
    assert rt.run_step(claim)['last_code'] == 'CELL_PAUSED'
    rt.set_paused('C01', paused=False, actor='operator', expected_version=2)
    with pytest.raises(ExecutionError, match='CELL_CONTROL_VERSION_CONFLICT'):
        rt.set_paused('C01', paused=True, actor='operator', expected_version=1)
    assert rt.resume(task['task_id'], actor='operator')['status'] == 'QUEUED'
    second = rt.claim('b')
    assert rt.cancel(task['task_id'], actor='operator')['status'] == 'CANCELLED'
    with pytest.raises(LostLease):
        rt.run_step(second)
    assert submit(rt)['status'] == 'CANCELLED'
    assert effects(rt) == []


def test_role_revoked_after_first_checkpoint_prevents_next_step(db_url):
    rt = make_runtime(db_url)
    submit(rt)
    claim = rt.claim('a')
    rt.run_step(claim)
    with transaction(rt.sessions) as s:
        s.execute(text('UPDATE test_operator SET active=0'))
    assert rt.run_step(claim)['last_code'] == 'SUBMITTER_AUTHORITY_REVOKED'
    assert len(effects(rt)) == 1


def qualification(handler):
    key = QualificationKey(handler.cell_id, handler.capability, RiskClass.R0, Environment.TEST)
    evidence = QualificationEvidence(True, True, True, True, True, True, True, True, False, ('test://independent-depth08',))
    return QualificationRecord(key, ProductionReality.AUTONOMOUS_QUALIFIED, evidence, 'C13', 'C12')


@pytest.mark.parametrize('loss', ['revoke', 'expire'])
def test_standing_qualification_survives_restart_and_loss_stops_retry(db_url, loss):
    rt = make_runtime(db_url, autonomous=True)
    record = qualification(next(iter(rt.handlers.values())))
    task = submit(rt)
    assert task['status'] == 'HOLD'
    with transaction(rt.sessions) as s:
        DurableQualifications(s).qualify(record, expires_ms=db_now_ms(s) + 60000)
    rt = make_runtime(db_url, autonomous=True)
    assert rt.resume(task['task_id'], actor='operator')['status'] == 'QUEUED'
    claim = rt.claim('a')
    rt.run_step(claim)
    with transaction(rt.sessions) as s:
        if loss == 'revoke':
            DurableQualifications(s).revoke(record.key, reason='independent regression', expected_revision=1)
        else:
            from go_hotel.db.models import AutonomyQualificationRow
            s.execute(update(AutonomyQualificationRow).values(expires_ms=0))
    assert rt.run_step(claim)['status'] == 'HOLD'
    assert len(effects(rt)) == 1


def test_c13_cannot_self_qualify(db_url):
    rt = make_runtime(db_url, cell='C13', autonomous=True)
    with transaction(rt.sessions) as s:
        with pytest.raises(RuntimeError, match='SELF_CERTIFICATION_PROHIBITED'):
            DurableQualifications(s).qualify(qualification(next(iter(rt.handlers.values()))), expires_ms=db_now_ms(s) + 60000)
    assert submit(rt)['status'] == 'HOLD'


@pytest.mark.parametrize('change,code', [
    ({'target_domain': 'FLIGHT', 'truth_mutation': True}, 'CROSS_DOMAIN_TRUTH_MUTATION_DENIED'),
    ({'capability': 'GRANT_SELF_PERMISSION'}, 'SELF_EMPOWERMENT_PROHIBITED'),
    ({'autonomous': True}, 'AUTONOMY_QUALIFICATION_MISSING'),
    ({'exposure': LegalExposureProfile(money_or_refund=True)}, 'LEGAL_HOLD'),
])
def test_c14_cannot_be_bypassed_in_durable_execution(db_url, change, code):
    rt = make_runtime(db_url, **change)
    assert submit(rt)['last_code'] == code
    assert rt.run_once('a') is None
    assert effects(rt) == []


def test_conditional_legal_allow_is_not_executable_without_satisfier(db_url):
    rt = make_runtime(db_url, exposure=LegalExposureProfile(money_or_refund=True), jurisdiction='TEST')
    rt.legal = AILegalPolicyRegistry((LegalPolicyRule('test-only', LegalDecision.LEGAL_ALLOW_WITH_CONDITIONS,
                                        conditions=('independent_case_approval',),
                                        covered_exposure_tags=frozenset({'money_or_refund'})),))
    assert submit(rt)['last_code'] == 'LEGAL_CONDITIONS_UNSATISFIED'


def test_expired_and_wrong_token_heartbeats_do_not_resurrect_lease(db_url):
    rt = make_runtime(db_url)
    task = submit(rt)
    claim = rt.claim('a')
    assert rt.heartbeat(claim) > 0
    with pytest.raises(LostLease):
        rt.heartbeat(Claim(claim.task_id, 'wrong-token', claim.attempt))
    expire(rt, task['task_id'])
    with pytest.raises(LostLease):
        rt.heartbeat(claim)
    assert rt.run_once('b')['status'] == 'SUCCEEDED'


def test_checkpoints_detect_corruption(db_url):
    rt = make_runtime(db_url)
    task = submit(rt)
    claim = rt.claim('a')
    rt.run_step(claim)
    with transaction(rt.sessions) as s:
        s.execute(update(Step).where(Step.task_id == task['task_id']).values(result_hash='tampered'))
    assert rt.run_step(claim)['last_code'] == 'CHECKPOINT_INTEGRITY_FAILURE'
    assert len(effects(rt)) == 1


def test_request_tampering_is_rejected_before_effect(db_url):
    rt = make_runtime(db_url)
    task = submit(rt)
    with transaction(rt.sessions) as s:
        s.execute(update(Task).where(Task.task_id == task['task_id']).values(payload_json={'changed': True}))
    assert rt.run_once('a')['last_code'] == 'TASK_REQUEST_INTEGRITY_FAILURE'
    assert effects(rt) == []


def test_local_step_expiring_before_commit_rolls_back(db_url):
    def slow(ctx):
        ctx.execute(text('INSERT INTO test_effect VALUES (:id,0,1)'), {'id': ctx.task_id})
        threading.Event().wait(0.15)
        return {'done': True}
    rt = make_runtime(db_url, steps=(slow,), max_lease=100)
    task = submit(rt)
    rt.run_once('a')
    assert effects(rt) == []
    assert rt.inspect(task['task_id'])['checkpoints'] == []
    rt.recover_expired()
    assert rt.inspect(task['task_id'])['status'] == 'RETRY_WAIT'


def test_environment_scope_isolation_and_production_gate(db_url):
    rt = make_runtime(db_url)
    task = submit(rt)
    other = DurableExecutor(rt.sessions, rt.handlers.values(), environment=Environment.STAGING, authorize_actor=actor_check)
    assert other.run_once('a') is None
    with pytest.raises(ExecutionError, match='TASK_NOT_FOUND'):
        other.inspect(task['task_id'])
    prod = DurableExecutor(rt.sessions, rt.handlers.values(), environment=Environment.PRODUCTION, authorize_actor=actor_check)
    assert submit(prod)['last_code'] == 'PRODUCTION_EXECUTION_NOT_CERTIFIED'


@pytest.mark.parametrize('outcome', ['SUCCEEDED', 'UNKNOWN', 'FAILED'])
def test_external_ambiguous_outcome_is_reconciled_without_resend(db_url, outcome):
    calls = []
    def dispatch(ctx):
        calls.append(ctx.operation_key)
        raise TimeoutError('provider may already have applied')
    def reconcile(ctx):
        return ReconciledResult(outcome, ctx.operation_key, 'test://provider-receipt', {'provider_state': outcome})
    rt = make_runtime(db_url, mode='EXTERNAL', steps=(), dispatch=dispatch, reconcile=reconcile)
    task = submit(rt)
    assert rt.run_once('a')['status'] == 'UNCERTAIN'
    assert rt.run_once('b') is None
    with pytest.raises(ExecutionError, match='TASK_NOT_RESUMABLE'):
        rt.resume(task['task_id'], actor='operator')
    with pytest.raises(ExecutionError, match='TASK_NOT_CANCELLABLE'):
        rt.cancel(task['task_id'], actor='operator')
    state = rt.reconcile_external(task['task_id'], actor='operator')
    assert state['status'] == ('UNCERTAIN' if outcome == 'UNKNOWN' else outcome)
    assert len(calls) == 1


def test_external_reconciliation_rejects_unbound_receipt(db_url):
    rt = make_runtime(db_url, mode='EXTERNAL', steps=(),
        dispatch=lambda _: (_ for _ in ()).throw(TimeoutError()),
        reconcile=lambda _: ReconciledResult('SUCCEEDED', 'wrong-key', 'receipt', {}))
    task = submit(rt)
    rt.run_once('a')
    with pytest.raises(ExecutionError, match='RECONCILIATION_SCOPE_MISMATCH'):
        rt.reconcile_external(task['task_id'], actor='operator')
    assert rt.inspect(task['task_id'])['status'] == 'UNCERTAIN'


def _killed_worker(url, ready, stage):
    def pending_effect(ctx):
        ctx.execute(text('INSERT INTO test_effect VALUES (:id,0,1)'), {'id': ctx.task_id})
        ready.set()
        threading.Event().wait(30)
        return {'effect': 0}
    rt = make_runtime(url, steps=(pending_effect,) if stage == 'inside_transaction' else None)
    claim = rt.claim('doomed-process')
    if stage == 'inside_transaction':
        rt.run_step(claim)
    elif stage == 'after_claim':
        ready.set()
        threading.Event().wait(30)
    else:
        rt.run_step(claim)
        ready.set()
        threading.Event().wait(30)


@pytest.mark.parametrize('stage', ['after_claim', 'inside_transaction', 'after_checkpoint'])
def test_sigkill_recovery_uses_database_not_process_memory(db_url, stage):
    rt = make_runtime(db_url)
    # For the transaction fault point keep the same one-step handler contract.
    if stage == 'inside_transaction':
        h = next(iter(rt.handlers.values()))
        rt = make_runtime(db_url, steps=(h.steps[0],))
    task = submit(rt)
    ctx = multiprocessing.get_context('spawn')
    ready = ctx.Event()
    proc = ctx.Process(target=_killed_worker, args=(db_url, ready, stage))
    proc.start()
    try:
        assert ready.wait(15), 'child did not reach fault point'
        proc.kill()
        proc.join(10)
        assert proc.exitcode is not None and proc.exitcode != 0
    finally:
        if proc.is_alive():
            proc.kill()
            proc.join(5)
    before = effects(rt)
    assert len(before) == (1 if stage == 'after_checkpoint' else 0)
    expire(rt, task['task_id'])
    assert rt.run_once('replacement-process')['status'] == 'SUCCEEDED'
    assert len(effects(rt)) == (1 if stage == 'inside_transaction' else 2)


def _external_crash(url, ready):
    def dispatch(ctx):
        # A separate transaction models the provider's own durable effect.
        engine = create_engine(url)
        with engine.begin() as conn:
            conn.execute(text('INSERT INTO test_effect VALUES (:id,0,1)'), {'id': ctx.operation_key})
        ready.set()
        threading.Event().wait(30)
        return {'provider': 'applied'}
    rt = make_runtime(url, mode='EXTERNAL', steps=(), dispatch=dispatch,
                      reconcile=lambda _: None)
    rt.run_once('external-doomed')


def test_process_dies_after_provider_effect_never_redispatches(db_url):
    calls = []
    def dispatch(ctx):
        calls.append(ctx.operation_key)
        return {}
    def reconcile(ctx):
        return ReconciledResult('SUCCEEDED', ctx.operation_key, 'test://persisted-provider', {'provider': 'applied'})
    rt = make_runtime(db_url, mode='EXTERNAL', steps=(), dispatch=dispatch, reconcile=reconcile)
    task = submit(rt)
    ctx = multiprocessing.get_context('spawn')
    ready = ctx.Event()
    proc = ctx.Process(target=_external_crash, args=(db_url, ready))
    proc.start()
    try:
        assert ready.wait(15)
        proc.kill()
        proc.join(10)
    finally:
        if proc.is_alive():
            proc.kill()
            proc.join(5)
    expire(rt, task['task_id'])
    assert rt.run_once('replacement') is None
    assert rt.inspect(task['task_id'])['status'] == 'UNCERTAIN'
    assert len(effects(rt)) == 1 and calls == []
    assert rt.reconcile_external(task['task_id'], actor='operator')['status'] == 'SUCCEEDED'
    assert calls == []
