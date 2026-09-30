# Runtime V1 failure-injection acceptance

Candidate only. Execute in an isolated environment.

## Required gates

1. Restart persistence: state and queued tasks survive supervisor process restart.
2. Lease fencing: a dead/expired worker cannot complete a task after takeover.
3. Duplicate dispatch: one idempotency key produces one task and one active claim.
4. Evidence tamper: mutation of a historical evidence body makes chain verification fail.
5. Permission fail-closed: an unknown action returns DENY.
6. Review bypass: C13 is rejected without a completed C14 task and an admissible, untampered sealed C14 bundle for the same candidate and application tree.
7. Retry exhaustion: expired work exceeding max attempts becomes ESCALATED.
8. Watchdog: stale heartbeat is surfaced and recoverable work is requeued.

## Acceptance command

```bash
python -m unittest discover -s control-plane/c1-c14-runtime-v1/tests -v
```

## Installation gate

Passing these tests does not authorize installation. Before a persistent Runner is
installed, the candidate must additionally pass:
- PostgreSQL multi-process contention test;
- database restart during an active lease;
- evidence projection consistency;
- C14 independent rule/compliance review;
- C13 independent quality acceptance after C14 closes;
- explicit human Command Center authorization.

No Production, real payment, real supplier, signing private key or gate bypass is
part of this acceptance.

