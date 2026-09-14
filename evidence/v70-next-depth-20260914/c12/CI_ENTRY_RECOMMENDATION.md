# C12 additional receipt admission and frozen CI evidence

The existing `validate_ledger.py` contract remains unchanged. Its RUNNING
check verifies referenced bytes and source/task bindings, and explicitly does
not authenticate their meaning. The new `verify_execution_receipt.py` adds
the next layer: expected cell, task and agent; full source/parent identity;
explicit RUNNING; nonempty ACK/start/observation timestamps in order; and
SHA256-bound nonempty process/tool output inside the evidence root.

ASSIGNED with no ACK/start is rejected. This check never changes a ledger
status, sends a task, synthesizes a worker ACK, verifies remote liveness or
authenticates an agent signature. Reviewers still compare the receipt to the
original collaboration/tool record. Its own result states those limits.

Proposed frozen CI entry, for root integration (no workflow modified here):

1. Pin checkout to the reviewed full candidate SHA and record the workflow,
   run, job and artifact IDs. Keep the artifact's reported digest distinct from
   a locally downloaded-and-verified archive digest.
2. Inherit previously passed tests only at their original source/scope. The
   retained PR73 scheduler test result is **16 tests, OK**, job 103850208313,
   run 34803331596, fixed head
   `a274f77e4c1479fb143cdc7ef45d63b9c4f8cc1b`. The supplied original log and
   artifact metadata are in `../PR73_SCOPED_CI_ORIGINAL.json`.
3. Execute the five added receipt cases with
   `python -m pytest ci/round2/test_validate_ledger.py -k receipt -p no:cacheprovider --junitxml <new-path>`.
4. Run `verify_execution_receipt.py` for each newly claimed RUNNING receipt:
   `python ci/round2/verify_execution_receipt.py <receipt.json> --evidence-root . --expected-cell C12 --expected-task V70-R2-C12-02 --expected-agent /root/c12_scheduler`.
5. Validate the development ledger separately. Preserve observed
   SCHEDULER_FAIL, assignments, ACK receipts, execution output and C14→C13
   review records as separate events. A passing assignment/schema check is
   not evidence that all 14 Cells executed or completed their domain.

The next integration decision is to wire both checks into the frozen candidate
CI while keeping reviewer provenance and historical source bindings. The
current helper is locally exercised and reviewable; automatic remote-worker
ACK authentication and heartbeat expiry remain outside its scope.
