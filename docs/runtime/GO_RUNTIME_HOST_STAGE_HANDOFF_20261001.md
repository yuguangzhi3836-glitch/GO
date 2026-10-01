# GO Runtime Host · 2026-10-01 Stage Validation Handoff

This document is a factual handoff of the dedicated Runtime Host validation
performed on 2026-10-01.

It records observed implementation and test state only.

It does not decide whether the Runtime project should proceed to the next phase.

Scope of this repository change: preserve the two implementations that were
actually executed on the target host during the validation, add minimal contract
tests for them, and record the observed state. It adds no Runtime capability,
changes no upstream branch, and performs no deployment.

---

## 1. Upstream sources observed

| Item | Value |
|---|---|
| PR287 tested candidate SHA | `7b9d53adb99b0523c1563ad388ac593ad800c864` |
| PR287 runtime tree | `bd102d9b3dcc6eb7cba4720e4baa20ff1bf3c742` |
| PR290 tested source SHA | `2fb15e50cac1d381c5f94acbb6a6a8d59e177138` |
| PR290 head branch | `feat/runtime-host-channel-v1-20261001` |

GitHub state observed when this handoff was generated:

```
PR287 = OPEN / DRAFT
PR289 = OPEN / DRAFT
PR290 = OPEN / DRAFT
```

This branch (`eason/runtime-host-validated-handoff-20261001`) is stacked on the
PR290 head commit above. PR #287, #289 and #290 were not modified by this change.

---

## 2. Target host facts

| Field | Value |
|---|---|
| name | `go-runtime-test-01` |
| instance_id | `i-j6cg7euc4ggol8gkijog` |
| region | `cn-hongkong` |
| OS | Ubuntu 24.04 (Ubuntu 24.04.5 LTS, kernel 6.8.0-139-generic) |
| architecture | x86_64 |

Host preparation observed in this round:

- dedicated `go-runtime` non-root service account (uid 999, gid 987, login shell `nologin`)
- frozen Runtime working directory `/opt/go/c1-c14-runtime` owned `go-runtime:go-runtime` mode `0750`
- SSH public-key access retained
- `PasswordAuthentication` disabled for `sshd`; public-key authentication left enabled
- 2 GiB swapfile enabled and recorded in `/etc/fstab`
- Docker installed (docker-ce / containerd.io / buildx / compose plugin); the
  service account is not a member of the `docker` group
- dedicated Runtime and Agent paths created

Status:

```
HOST_PREP = READY
```

This records host preparation for the bounded test only. It is not a production
hardening, certification, or security assessment.

---

## 3. GitHub transport

No new repository was created.

| Purpose | Repository | Namespace |
|---|---|---|
| Task | `chenzhenxi1-sudo/go-control-tasks` | `runtime-host-v1/tasks/` |
| Evidence | `chenzhenxi1-sudo/go-control-evidence` | `runtime-host-v1/evidence/` |

Evidence branch used during the test: `permission-test`.

The branch was selected because the live HK evidence writer at that time resolved
its target through the repository **default branch** rather than a branch constant:
the running unit is `go-hk-agent.service`, whose transport helper performs
`git clone --depth=1 <repo>` with no `-b` and then `git push origin HEAD`.
The repository default branch was `permission-test` at that time. The older
`/opt/go-hk-agent/` tree contains a hardcoded `'hk-agent-evidence'`
constant but is not the running implementation.

Observed transport property: a GitHub deploy key is repository-scoped and carries
no path-level permission, so the `runtime-host-v1/` namespace separation is
enforced by `git_transport.py` (`PREFIX = 'runtime-host-v1/'`, key regex, refusal
of symlinks/directories, no overwrite, no force push).

The pre-existing HK namespace `go-control-tasks/tasks/` was not written to by this
validation.

---

## 4. Host Channel E2E (observed)

Exactly one probe task was published.

| Field | Value |
|---|---|
| task_id | `rh-probe-612d7ad713f2be1b` |
| action | `RUNTIME_HOST_PROBE_V1` |
| parameters | `{}` (empty) |
| task lifetime | 300 s |
| tasks blob | `5279aa5010a8e4c7849b446c4b64a60f2b4dd6d2` |
| evidence blob | `8399687a8cc8272e24a854ad31a6fadce18e2ca5` (615 bytes) |

Observed path:

```
CC test publisher
  -> go-control-tasks / runtime-host-v1/tasks/
  -> rt01 Management Agent
  -> go-control-evidence / runtime-host-v1/evidence/
  -> CC collect / verify_evidence
```

Observed verification results:

```
signature            = PASS
task binding         = PASS
registration binding = PASS
host binding         = PASS
agent binding        = PASS
generation binding   = PASS
executor digest      = PASS
evidence readback    = PASS
status               = PROBE_ONLY
runtime_acceptance   = NOT_RUN
```

Registration used for the probe: 723 bytes, mode `0600`, `generation = 1`,
`actions = ["RUNTIME_HOST_PROBE_V1"]`, validity window 14400 s, self-verified with
the corresponding public key immediately after signing. The same bytes were copied
to the target host and the `sha256` was confirmed identical on both sides
(`281794c2dc032efdff3b0a3218ae86ade49b26402d46d1c34e9ae67e6eb934ca`).

```
HOST_CHANNEL_E2E = PASS
```

Range proven by this result: the third host can receive one restricted, signed and
verified Runtime Host probe through this channel and return verifiable Evidence.

Range not proven by this result: that an external task entered the C1-C14 Runtime
queue (see section 7).

---

## 5. PR287 Runtime installed on the host (observed)

| Item | Value |
|---|---|
| candidate SHA | `7b9d53adb99b0523c1563ad388ac593ad800c864` |
| runtime tree | `bd102d9b3dcc6eb7cba4720e4baa20ff1bf3c742` |
| topology sha256 (re-checked on install) | `ede10d06e41d7eec42dc7996d8001bea61d034e7010632a7485c7485f2c1f394` |
| systemd unit sha256 (re-checked on install) | `94955124d1f63a9f4cb5da5a6dab4bcaf93869973066b889e7116ad65c6cdee5` |
| install path | `/opt/go/c1-c14-runtime` |

Observed effective Runtime properties:

```
User=go-runtime
PrivateNetwork=true            (service net namespace differs from the host net namespace)
MemoryMax=256M                 (268435456)
CPUQuota=50%                   (CPUQuotaPerSecUSec=500ms)
TasksMax=32
CapabilityBoundingSet=         (empty)
UMask=0077
StateDirectoryMode=0700
Restart=on-failure / RestartSec=3s
StartLimitInterval=60s / StartLimitBurst=5
```

Observed credential and network boundary for the Runtime process:

- no GitHub credential
- no Evidence private key (the service account could not read either key file)
- no Docker socket access
- no network listener
- the only TCP listener on the host remained `sshd` on port 22

---

## 6. Runtime local probe (observed)

One task was inserted through the Runtime's own `Runtime.enqueue()` and claimed by
the running frozen `runner_service`.

| Field | Value |
|---|---|
| task_id | `rt_f2d1fe6ffcb04d238fe7a8ef1b9aff6f` |
| owner_c | `C1` |
| kind | `RUNTIME_PROBE` |
| idempotency_key | `go-runtime-local-probe-20261001-01` |

Observed results:

```
status                    = SUCCEEDED
attempts                  = 1
lease_owner               = null
lease_until               = null
evidence sequence         = TASK_ENQUEUED -> TASK_CLAIMED -> TASK_COMPLETED
verify_evidence_chain()   = true
NoopWorker result         = {"adapter": "noop", "accepted": true}
last_error                = null
```

```
RUNTIME_LOCAL_PROBE = PASS
```

---

## 7. Boundary between the two PASS results

The two results are separate and are not combined into a single statement.

| | Host Channel E2E | Runtime Local Probe |
|---|---|---|
| Task source | CC → GitHub | local `Runtime.enqueue()` |
| Entered PR287 Runtime queue | **NO** | **YES** |
| What it proves | the dedicated host task/evidence channel works for one restricted probe | the frozen PR287 Runtime kernel can claim and complete a `RUNTIME_PROBE` |

Combining them into `FULL_EXTERNAL_C1_C14_E2E = PASS` is not supported by the
observed evidence.

---

## 8. Current implementation boundary

```
EXTERNAL_TASK_TO_C1_C14_RUNTIME = NOT_IMPLEMENTED
```

Observed fact: an external `RUNTIME_HOST_PROBE_V1` is handled by the Management
Agent, which calls `Registry.probe()` and produces Host Evidence. It does not call
`Runtime.enqueue()`, so it does not enter the PR287 C1-C14 Runtime queue.

The only task that entered the Runtime queue in this validation was inserted
locally through `Runtime.enqueue()`.

```
REAL_AI_WORKER = NOT_IMPLEMENTED
```

Observed fact: the tested PR287 Runtime uses `NoopWorker`.

These are statements of the current implementation boundary, not evaluations of it.

---

## 9. PR289 reliability matrix — observed completion

Observed / measured in this round:

- exact target host identity
- exact candidate and package digests
- Runtime service user
- filesystem and credential boundary
- `PrivateNetwork` namespace separation
- configured cgroup limits
- Runtime probe completion
- normal service stop
- Host Channel task/evidence round trip
- Runtime Evidence chain validity

Not executed in this round:

- bounded memory pressure fixture
- bounded CPU throttling workload fixture
- `TasksMax` pressure fixture
- controlled process kill / restart recovery matrix
- stale lease / fencing fixture matrix on the target host
- actual `StartLimit` burst triggering
- VM reboot / boot recovery
- hard power reset / power-loss recovery
- SQLite backup / restore acceptance

```
FULL_HOST_RELIABILITY_MATRIX = PARTIAL
```

`FULL_HOST_ACCEPTANCE = PASS` was not established and is not claimed.

---

## 10. Source added by this change

### `control-plane/runtime-host-channel-v1/agent_service.py`

Origin: 2026-10-01 target-host test implementation.

Role: Management Agent entry point — protected config loading, registration
loading, local identity and executor-digest validation, Git transport polling,
Evidence signing and publication. Accepts only the optional `--once` flag and takes
no path or URL arguments.

Observed use: USED IN FIRST HOST CHANNEL E2E (installed at
`/opt/go/runtime-host-agent/agent_service.py` on the target host).

### `control-plane/runtime-host-channel-v1/cc_test_publisher.py`

Origin: 2026-10-01 CC test implementation.

Role: test-only entry point with exactly three verbs — `sign-registration`,
`publish-one-probe`, `collect-evidence`.

Observed use: USED IN FIRST HOST CHANNEL E2E (installed under
`/usr/local/libexec/go-runtime-host/` on the Command Center host, invoked through
the wrapper `/usr/local/libexec/go-runtime-host-test-publisher`).

Neither file was part of PR290 head `2fb15e50…`. This change preserves them in
repository source history for the first time.

### TESTED_SOURCE_DIGESTS

The digests below were confirmed byte-identical between the local source of record
and the copies actually installed on the hosts at test time, and between the local
source of record and the git blob stored by this change.

```
agent_service.py       size 8878    sha256 629c6bddba2849a5ff2f8c8672561ecf60b5f44e99d9dc6b54dea8d15f280dbf
cc_test_publisher.py   size 12554   sha256 89391c059df945c07fac36389ecb6f9641c13bb93f5a880570d793a5539e18ef
```

No private key, token, credential, database, outbox, registration secret material
or journal is included in this change.

---

## 11. Minimal contract tests added

Two test modules were added to the component, following its existing flat
`test_*.py` convention (the component has no `tests/` subdirectory).

- `test_agent_service.py` — fixed configuration path constant, IMDS constant,
  argument surface, clean refusal without a config, absence of shell execution
  paths, path/remote shape validation, deterministic executor manifest and digest
  behaviour, fail-closed registration/host/executor binding checks, transport
  namespace, single action constant.
- `test_cc_test_publisher.py` — fixed three-verb surface, rejection of unknown verbs
  and extra arguments, configuration bounds, plan / executor / evidence-key /
  approval-ref / approval-status comparison, the fixed registration field set,
  single-shot outbox ordering, bounded task lifetime, mandatory Evidence
  verification with `status = PROBE_ONLY` and `runtime_acceptance = NOT_RUN`,
  protected environment names.

All tests are local-only: temporary filesystem, temporary SQLite, in-memory keys
and in-memory transport fakes. No network call, no GitHub write, no SSH, no Runtime
or Agent start, no task or Evidence publication. `agent_service.protected_read` is
substituted in tests because the production implementation requires root-owned
paths; root-ownership and symlink enforcement itself is already covered by
`test_adapter.py`.

Observed test counts on this change:

```
OLD_TESTS   = PASS   (33 tests, PR290 baseline modules, unchanged)
NEW_TESTS   = PASS   (38 tests)
TOTAL       = PASS   (71 tests, component discovery)
```

The baseline suite requires POSIX (`os.geteuid`); it was executed on Linux. On a
Windows host the root-owned-path fixture reports an environment error, which is a
platform limitation rather than a result of this change.

---

## 12. Known issues observed during validation

Recorded, not changed in this change. Editing either file would mean the bytes
stored here were no longer the bytes executed on the target host.

1. `cc_test_publisher.check_binding()` reads the plan file with
   `open(PLAN_JSON, "rb").read()` without closing the handle. Under CPython this is
   observable as a `ResourceWarning` during tests. The behaviour of the executed
   validation is unaffected.

The following were encountered during the validation and are recorded because they
affected how the tested bytes were produced:

2. `git archive` against a repository with `core.autocrlf=true` rewrites line
   endings, which changes the digest of the extracted frozen candidate. The
   validation used `-c core.autocrlf=false -c core.eol=lf` so the extraction
   digests matched the frozen `topology sha256` and `unit sha256`.

3. A here-string copy (`<<< "$(cat …)"`) appends a trailing newline and is not
   byte-preserving. Exact-byte copying of the signed registration was done with
   `cat > <path>`; the resulting `sha256` was confirmed identical on both sides.

4. An OpenSSH Ed25519 `SHA256:` fingerprint is computed over the SSH wire blob,
   while `evidence_key_sha256` is computed over the raw 32-byte Ed25519 public key.
   The two values are different digests.

---

## 13. Final observed host state

```
Management Agent                = STOPPED
C1-C14 Runtime                  = STOPPED + DISABLED / HOLD
```

Retained on the hosts:

- Runtime SQLite database and WAL state
- Runtime health file
- Runtime runner lock file
- the signed registration
- the CC publisher outbox database
- GitHub task and Evidence references
- journal and test evidence
- recorded digests

Not executed in this round:

- reboot
- power reset
- Production
- HK business deployment
- new repository
- modification of the existing Boss Request action enum

---

## 14. Final status block

```
HOST_PREP = READY

GITHUB_TRANSPORT = READY

HOST_CHANNEL_E2E = PASS

PR287_RUNTIME_INSTALL = TESTED

RUNTIME_LOCAL_PROBE = PASS

FIRST_TEST = PASS


FULL_HOST_RELIABILITY_MATRIX = PARTIAL

EXTERNAL_TASK_TO_C1_C14_RUNTIME = NOT_IMPLEMENTED

REAL_AI_WORKER = NOT_IMPLEMENTED


RUNTIME_CURRENT_STATE = STOPPED_HOLD

MANAGEMENT_AGENT_CURRENT_STATE = STOPPED


PR287 = OPEN_DRAFT

PR289 = OPEN_DRAFT

PR290 = OPEN_DRAFT
```

---

## Items left for Owner / upstream decision

1. Whether to continue with:

   GitHub external Task
   → Management Agent
   → `Runtime.enqueue()`
   → C1-C14 Runtime queue

2. Whether to implement a real `WorkerAdapter` / AI Worker instead of the current
   `NoopWorker`.

3. Whether to execute the remaining PR289 reliability matrix:
   resource pressure / restart / reboot / power loss / backup restore.

4. Whether these tested Agent / Publisher additions should be incorporated into the
   long-term Runtime Host source.

5. Whether the dedicated Runtime Host should later run persistently or remain
   `STOPPED/HOLD`.
