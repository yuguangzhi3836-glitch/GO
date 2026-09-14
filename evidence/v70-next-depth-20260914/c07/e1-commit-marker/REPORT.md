# V70-R2-C07-02-E1 — explicit commit acknowledgment evidence

Status: **EVIDENCE_READY, 4/6**. This is a test-evidence correction; product code is unchanged. C14/C13 remain independent. PostgreSQL still requires the central isolated CI run.

The original interleaving tests inferred completed withdrawal from process exit. The service could already have committed while that process was still disposing its engine or exiting, so process exit was an incomplete measurement of the relevant event.

The subprocess actor now creates a `CONSENT_WITHDRAWAL_COMMIT_ACK` record immediately after `revoke_consent` returns from its committed transaction. It records PID, UTC time and `monotonic_ns`, writes and fsyncs a temporary file, and publishes the complete marker by atomic rename. The paused reader/writer separately records its actual resumed event. The assertions compare those two events on the same host's monotonic clock; they no longer use `poll()` to infer database commit or a controller-side release check to infer when the worker actually resumed.

This observes **the service's committed acknowledgment and the protected process's actual resume order**. It does not claim to measure the storage engine's internal commit timestamp or to withdraw data already transmitted to a client.

Only the two affected update/withdrawal and read/withdrawal interleaving tests were re-run: **2 PASS, 0 FAIL, 0 SKIP in 24.55 seconds**. Both observed the protected process resume before the withdrawal commit acknowledgment. Fresh subsequent reads were empty, and the update case also rejected a later write using the withdrawn consent. Raw commit-marker files, worker events, controller ledgers, stdout/stderr and ordering observations are under `processes/`; `pytest.log` and `junit.xml` preserve the run result.

The previous 40-PASS logs, old freeze manifest and earlier red evidence remain unchanged one directory above. Their two affected cases overlap this new run; the total must not be described as 42 distinct tests. The exact pre-E1 actor/test files are preserved under `pre-e1-source/tests/`.

The updated four-file freeze includes the unchanged product module and unchanged PostgreSQL runner plus the two updated test files. Its canonical file-list SHA256 is:

`81f08781e68f89c60eb5e854f607b8b74d84775cd7aa92f5890a512a692fb539`.

This supersedes the previous test freeze `8837284c7d2374a2734712c991a9635a6897eab4a5ad87a0329f5a2da2a737f5` while preserving its original manifest. The product module remains SHA256 `b9cb30b204be2993e77f8a09d76a5244858d82007e53c44058b13815a4053dd1`.

Next action: run `application/ci/next_depth/c07_postgres.py` from the combined candidate using these final tests, then pass the resulting PostgreSQL evidence to C14/C13. No product logic, dependencies, migration, Git remote, Hong Kong or Production was changed by E1.
