# Topology/residency and SQLite fencing validation

Local implementation evidence, 2026-10-01 Asia/Shanghai. Not independent C14/C13 acceptance.
Base candidate: dfea65841f93b51b47d33254727f0c8df98f4c21 (PR #285, preserved).

- Exact remote snapshot: all 34 Runtime blobs verified against Runtime tree df8cb8602eef03a017c4c5cd7345de95432403d4 before modification.
- Baseline reproductions on disposable SQLite: old same-name worker completed a re-claimed task (epoch 2); expired lease was renewable before recovery. Both are now rejected.
- `python -m unittest discover -s control-plane/c1-c14-runtime-v1/tests -v`: 54 tests PASS, including previous 41 tests and 13 new tests.
- Real database cases: epoch reuse across restart, expired-before-recovery and exact expiry boundary, absent/malformed epoch, completion waiting for write lock until expiry, evidence write rollback, equal/backward evidence timestamps, Supervisor stale-failure isolation, probe filtering, invalid lease duration.
- Real child-process cases: default activation refusal, concurrent singleton refusal, SIGKILL and restart with preserved state, probe-only completion, SIGTERM clean stop. All use disposable local paths, not installed services.
- Topology cases: valid isolated proposal; reject changed environment, services, credentials, network, topology version/type, protected mutation and extra fields; old all-PASS preflight with human flag remains topology-blocked.
- `systemd-analyze verify systemd/go-c1-c14-runtime.service`: exit 0. Static syntax only; no systemd installation/start, namespace enforcement or boot persistence test.
- `git diff --check`: clean.

CI will bind the actual follow-up SHA, Runtime/application trees, topology and unit bytes, and original unittest log in the contract artifact. The PostgreSQL workflow is unchanged and must use the new exact candidate; prior PASS is not transferred.

Pending: fresh independent C14 -> C13, approved isolated host and first formal topology E2E, target-host resource/network/permission checks, authenticated operational admission and real worker integration. Installation BLOCKED; TOPOLOGY_CHANGE_REQUIRED / HOLD.
