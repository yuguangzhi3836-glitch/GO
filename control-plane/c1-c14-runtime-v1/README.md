# C1-C14 Runtime V1

Status: **candidate only / not installed / not deployed**

This directory is the first executable kernel for turning GO's C1-C14 model
from conversational roles into fourteen durable, 24x7 responsibility domains.

## What this first slice implements

- **Heartbeat / liveness** for C1-C14 with TTL and stale detection.
- **Durable task queue** with priority, delayed availability, idempotency keys,
  leases, retry budgets and crash recovery.
- **Long-term state** as per-C key/value JSON persisted independently from chat.
- **Automatic wake signal**: `wake_candidates()` tells an external supervisor
  which C domains have runnable work.
- **Permission matrix** with fail-closed unknown actions.
- **Cross-C collaboration** through durable inbox messages and correlation IDs.
- **Evidence** as an append-only SHA-256 hash chain.
- **Exception escalation** with severity and explicit human-required flag.
- **Unattended recovery**: expired task leases requeue; exhausted retry budgets
  escalate instead of silently dropping work.

## Safety boundary

V1 intentionally cannot deploy, sign authority, touch real payment, touch a real
supplier, read private keys, or enter Production. The kernel only returns
permission decisions. Existing GO Command Center / Control Plane remains the
authority boundary.

Default policy:

- isolated reads/tests/candidate branches/Draft PR/evidence/messages: `ALLOW`
- merge/HK deploy/final release/Production/real money/real supplier/signing:
  `REQUIRE_HUMAN`
- private keys/secret export/gate bypass: `DENY`
- unknown action: `DENY`

## Why SQLite first

This slice proves the state machine and recovery semantics with no new service
topology and no external dependency. It is **not** the target HA store.
Production-grade 24x7 operation should move the same contracts to the existing
approved PostgreSQL/control-plane persistence after acceptance.

## Run isolated tests

```bash
python -m unittest discover -s control-plane/c1-c14-runtime-v1/tests -v
```

No network, credentials, payment endpoint, supplier endpoint, HK deployment or
Production access is required.

## Next slice after this candidate passes

1. supervisor loop: periodic heartbeat/recovery/wake dispatch;
2. executor adapter contract for model/Dot/Codex workers;
3. per-C role registry binding the already-approved C1-C14 responsibility map;
4. PostgreSQL implementation with `FOR UPDATE SKIP LOCKED` claiming;
5. maker-checker handoff in formal order: C14 rule review, then C13 quality acceptance;
6. Command Center dashboard: liveness, queue age, escalations, evidence chain;
7. signed runtime receipts without giving workers signing-key access;
8. chaos tests for process death, DB restart, duplicate dispatch and clock drift.

## Non-goals of V1

- redefining C1-C14 responsibilities;
- creating C15;
- changing HK-STAGING topology;
- merging or deploying this candidate;
- replacing existing C13/C14 gates or Command Center authority.


## Independent review order

The candidate follows the existing formal channel: **C14 -> C13**.
`ReviewChain.start_c14()` queues C14 from a builder domain (C1-C12).
`advance_to_c13()` reads the completed C14 task and its completion Evidence;
there is no caller-supplied PASS parameter. The existing
`control-plane/c13-c14-lite/lite_prerequisite.py` validator recomputes the sealed
C14 root and applies the formal PASS_SCOPED / documented NOT_APPLICABLE and
remediation-closure rules. FAIL, BLOCKED, missing/incomplete/tampered results,
and candidate SHA or application-tree mismatches refuse the handoff.
The originating evidence reference is also fixed; the C13 task hashes the C14
root and completion-evidence identity into its idempotent request binding.

The former `start_c13` / `advance_to_c14` reverse-order methods are removed.
Calling `request_independent_review` directly cannot skip the C14 prerequisite.
Review routing code must use this entry point; generic task queue operations are
not a formal review dispatch or review authority.

This Runtime is still a candidate coordinator. A stored bundle/root alone does
not establish independent AI execution or authenticated GitHub provenance. The
formal backend remains responsible for real run/artifact readback, original
ledger/task binding, reviewer independence, and acceptance formation. Unit
fixtures are synthetic and grant no review verdict. Keep Draft; installation
still requires both independent reviews and human Command Center authorization.

Change classes for this alignment: CONTROL_PLANE, PRODUCT_FIX, TEST_ONLY,
DOCUMENTATION. No migration, formal-workflow edit or live topology change.
