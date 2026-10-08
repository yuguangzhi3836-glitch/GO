# #366 cost attribution follow-up — live retest blocked

2026-10-03. No business query changes, index application, external load test,
merge or deployment performed in this follow-up. Main was rechecked as
`05b108cc63b008aad4da732ac97c7e453cf59220`.

The archived evidence at commit `13a08ec261cc1618b7cada5a2b64bd438b848621`
was downloaded and its raw ZIP SHA256 matched
`a720dd9adfbddeb90c19a16ef862a56f156237d4616405e4dbfa893f67cc8c88`.
`recompute_366.py` reconstructs exact SQL fingerprints using retained SQL text
and the explicit bind names in historical application `a6361b9`, then matches
the archived SHA256 prefixes. It does not rerun SQL. The historical application
already used immutable prepared query shapes; current main has different bind
names. SQL identity was matched by hashing, not guessed from call counts.

## Verified historical aggregate costs, 100-concurrency tier

| Query fingerprint | Calls | Summed client SQL wall seconds |
| --- | ---: | ---: |
| Root intent lock | 500 | 2.893789 |
| Global idempotency key lock | 500 | 2.011943 |
| Credit source guard | 200 | 0.917241 |
| Movement history lock | 200 | 0.844530 |
| Movement insert | 200 | 0.875944 |
| Fulfillment lock | 100 | 0.454829 |
| Ledger batch insert | 100 | 0.588621 |
| Fulfillment update | 100 | 0.369111 |

Money service totals independently reproduce 2,000 SQL / 9.309649s SQL wall,
500 leases / 14.063154s hold, and 228.726702s cumulative pool queue.
The guard's 200 calls match two fresh writes per transaction. Its SQL wall is
9.85% of money SQL wall and 6.52% of money hold time. Root+key SQL wall is 52.69%
of money SQL wall, but includes fresh writes and replays. Neither number is a
database-server execution time or an estimate of removable scan cost.

The fingerprint table is global, not a SQL-by-service cross-tab. In particular,
fulfillment-event INSERT is shared with other services (300 calls / 1.074202s),
so it is deliberately excluded above rather than assigned wholesale to money.
The source read fingerprint occurs 200 times and matches the fresh-write guard;
this is strong workload-specific attribution, not a general identity rule.

## What cannot be recovered

The archive contains no catalog_credit_source row count, observed index list,
or EXPLAIN plan. Profiling records SQL fingerprint totals and service totals
separately, without per-call AUTH/CAPTURE/replay labels or a joinable event
timeline. Parent service context has CPU summaries only. Consequently it cannot
split SQL wall, connection hold or pool queue into the requested three paths.
Do not divide totals evenly or assign all root/key time to fresh writes.

0.917241s is only a ceiling on the entire guard's client-time contribution in
this old run. An index retains both round trips and cannot remove transport,
scheduling, or all execution time. Its scan-only saving remains unknown.
No matching-scale index or source-write-maintenance experiment was triggered:
the prerequisite observed source scale and plan are missing.

## Access and decision

No Remote Desktop Commander device is connected. The available GitHub
connector supports repository evidence retrieval but rejects the Codespaces
inventory endpoint as unsupported. There is currently no established execution
channel to the original diagnostic Codespace/database. This is an access gap,
not a missing authorization to carry out the user's requested diagnostics.

Decision: HOLD #373 as the current performance next step, pending measured scan
cost. No performance PASS or completed live retest is claimed. If the observed
table is small or scan cost negligible, mark it NO-GO for this bottleneck and
rank fresh-write SQL by newly collected cost instead. Root/key aggregates are
not justification to weaken their locks or replay path.

To finish, connect the original diagnostic Codespace (or provide its retained
read-only outputs). Verify database/schema and source identity; collect source
count, actual indexes and the guard plan with bounded read-only queries. Add
test-only per-call labels for fresh AUTH, fresh CAPTURE, replay and conflict;
retain them from acquisition through checkin, including commit/rollback. SQL
events must carry the same call identifier. Preserve the original queue metric
and distinguish it from total connection acquisition. A serial diagnostic can
measure query work but cannot reproduce the old 100-concurrency queue profile.
Any concurrent diagnostic must remain within separately confirmed scope; do
not silently restart the old external workload runner.

Recompute without a database:

```sh
python ci/money_new_write/recompute_366.py /path/to/raw.zip
```
