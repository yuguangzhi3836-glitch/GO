# Per-call money SQL follow-up — 2026-10-03

Class: TEST_ONLY + DOCUMENTATION. Extends existing Draft #366, no business
query changes, no schema changes, no deployment. No new performance verdict.

The #373 attribution at f9f12b53328084bbd4822f1ded0dfecede7b001d correctly
leaves the historical root/key 4.905732 seconds mixed across new writes and
replays. Source guard 0.917241 seconds is client time, not proven scan cost.
Neither provides a safe removable-round-trip budget. Source and history guards,
root/key locks, and independent AUTH/CAPTURE commits must remain intact.

`call_sql.py` fills a missing data shape: every cursor event has a call identity
and an explicit scenario. It retains full checkout-to-checkin hold intervals,
including commit/rollback outside create_in_session. It records no SQL text,
parameters, result values, exception text, business keys or money amounts.
SHA256 fingerprints are exact statement-byte hashes; map them to reviewed
parameterized SQL templates offline for the fixed application, not by guessed
call count. Different bind names can change fingerprints.

This is a standalone opt-in synchronous collector, not wired into the old
concurrent launcher. Do not run alongside another dialect wrapper. Instantiate
one per worker after connection initialization, use bounded isolated fixtures,
and snapshot only after all workers join. No async/shared-thread use. Calls
must start before checkout and end after checkin; inherited or escaped leases
invalidate the report. Call IDs are worker-local; archive a worker identity.

Explicit caller-owned integration, with existing correctness assertions kept:

```python
probe = CallSQL(engine)
try:
    # Fixture must prove fresh intent/key and unchanged AUTH/CAPTURE behavior.
    with probe.call('fresh_AUTH'):
        auth = money.create(intent_id, auth_body, auth_key, actor)
    with probe.call('fresh_CAPTURE'):
        capture = money.create(intent_id, cap_body, cap_key, actor)
    with probe.call('replay_CAPTURE'):
        replay = money.create(intent_id, cap_body, cap_key, actor)
    assert replay['money_movement_id'] == capture['money_movement_id']
    report = probe.snapshot()
    assert report['valid'], report['errors']
finally:
    probe.close()
```

For caller-owned sessions, place the entire session/commit/close lifetime inside
the call scope. Do not put a label just around create_in_session and then omit
commit. `fresh_AUTH`, `fresh_CAPTURE`, `replay_AUTH`, `replay_CAPTURE`, `conflict`
are fixture assertions, not automatically detected database outcomes. A returned
call is not proof of committed success. Preserve original outcome/ledger checks.

Optional `acquisition()` brackets an existing session.connection() invocation;
do not insert extra acquisitions solely for measurement. It measures total
acquisition, not pure queue; queue is explicitly null. Existing queue metrics
must be separately retained and correlated before claiming path-level queue
attribution. SQL cursor timing excludes fetch/materialization and includes
scheduling/transport/driver overhead. No server CPU or lock wait inference.

Local validation: Python 3.12.14, SQLAlchemy 2.0.43, SQLite QueuePool; eight
behavior tests pass (classification isolation, concurrent calls, error/rollback
and reuse, lease escape/inheritance detection, restoration, acquisition naming,
and no raw statement/value/error export). This is not PostgreSQL validation,
not the original SQLAlchemy 2.1.1 environment, and not money correctness testing.

```sh
python -m unittest discover -s ci/hold_cpu -p 'test_call_sql.py' -v
```

Live retest NOT RUN. Desktop Commander returned no connected devices this turn.
The original Codespace name is recorded in #366 README:
`literate-winner-vpqqjgwvpjprcp7gw`. Before sampling, verify actual source/tree,
working tree, schema, PostgreSQL and dependency versions there. Collect bounded
source cardinality/index/plan evidence. Run labelled serial cases first; collect
raw per-call data and rank new AUTH/CAPTURE SQL separately from replays. Any
later concurrent diagnostic retains existing correctess and 20/100 stop rules;
instrumented timing cannot qualify a performance candidate. No original
Codespace database was accessed and no business optimization was selected here.


## Execution connection recovered — 2026-10-03

Browser terminal successfully reconnected to original Codespace
`literate-winner-vpqqjgwvpjprcp7gw`. Desktop Commander availability is not a
prerequisite for that browser-terminal route. Existing authorized workspace
trust was restored. No new account, credentials or access grant was created.

Observed base workspace: /workspaces/GO, branch
integration/capacity-foundation-20260928, HEAD
40d59f85bc667754707c2d40ca1eedbf95e239d4; historical diagnostic worktrees and
local modifications remain intact. The original isolated virtual environment
/workspaces/.go-capacity-venv/bin/python remains Python 3.12.3, SQLAlchemy 2.1.1,
psycopg 3.3.6. Default shell Python is different; do not use it for comparison.

Fetched fixed observer 70022e643febbef3692a7f713d7aa1850a391b71 into a new detached
/workspaces/GO-call-sql-20261003 worktree. Eight test_call_sql behavior tests
passed there in 0.181s (SQLite tests under original dependencies).

No Docker containers were present at reconnection. Cached postgres:18.4 was
available. Started a NEW isolated fixture container go-call-sql-pg-20261003 on
127.0.0.1:55436, database go_c11_isolated. It is not the old diagnostic database
or its original row population. Read-back server version: PostgreSQL 18.4
(Debian 18.4-1.pgdg13+1). A Python SQLAlchemy SELECT 1 / commit / checkin smoke
with CallSQL returned valid=true, one cursor event and one balanced lease.
The fixture label fresh_AUTH in this smoke is only a collector label; this
was NOT a money AUTH transaction or money correctness/performance test.

Connection blocker resolved. Still pending: integrate fixture-asserted call
labels into the bounded money workload, bind application/source/scale, collect
SQL-by-path timings and source/index/plan evidence, then select a defensible
optimization. No historical database cardinality restored or inferred, no
business query edit, external load test, merge, deployment or performance PASS.
