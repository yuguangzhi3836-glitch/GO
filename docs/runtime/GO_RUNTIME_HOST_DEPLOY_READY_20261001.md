# GO Runtime Host · 2026-10-01 Deployment Preparation

This document is a factual record of the deployment-preparation round performed on
2026-10-01 for the dedicated Runtime Host `go-runtime-test-01`.

It records what the round added and what was tested offline.

It does not enable anything on the Runtime Host, does not publish a registration to
any repository, and does not decide whether the Runtime should run persistently.

Owner has approved deployment. This round only prepares the persistent registration
and service lifecycle required before enabling the already validated Runtime Host.

---

## 1. Scope of this round

Added, tested locally, and not deployed:

| Artifact | Path | Kind |
|---|---|---|
| CC registration rotator | `control-plane/runtime-host-channel-v1/registration_publisher.py` | new source |
| rt01 registration sync | `control-plane/runtime-host-channel-v1/registration_sync.py` | new source |
| registrations namespace | `control-plane/runtime-host-channel-v1/git_transport.py` | 3-line change |
| rt01 units | `control-plane/runtime-host-channel-v1/systemd/go-runtime-host-registration-sync.{service,timer}` | new |
| rt01 unit | `control-plane/runtime-host-channel-v1/systemd/go-runtime-host-agent.service` | new |
| CC units | `control-plane/runtime-host-channel-v1/systemd/go-runtime-host-registration-publish.{service,timer}` | new |
| contract tests | `test_registration_publisher.py`, `test_registration_sync.py` | new |

Not changed in this round: `agent_service.py` and `cc_test_publisher.py` keep the
exact bytes that were exercised on the real host on 2026-10-01 (verified against
their 2026-10-01 digests), and the frozen PR #287 Runtime unit is untouched.

---

## 2. Why rotation is required before persistent operation

The registration that completed the first host-channel E2E was issued for a bounded
test window (14400 s). The registration contract in `channel.py` allows at most
86400 s, and `Registry.enroll` refuses a generation that does not strictly increase.

The existing bounded test registration therefore cannot serve as a long-lived
credential, and the 86400 s ceiling was not changed.

The rotation design stays inside those existing constraints:

- the signer private key remains on the Control Center and is never copied;
- `channel.py` is not modified, and the 86400 s maximum is not removed;
- a generation is never re-signed and never reused;
- the Management Agent keeps reading a single local signed registration file.

---

## 3. Registration transport

No new repository was created. The existing target is reused:

```
git@github.com:chenzhenxi1-sudo/go-control-tasks.git   branch: main
```

New append-only namespace:

```
runtime-host-v1/tasks/            (existing, unchanged)
runtime-host-v1/evidence/         (existing, unchanged)
runtime-host-v1/registrations/    (new)
```

Object naming is immutable and one file per generation:

```
runtime-host-v1/registrations/<agent_id>-g<generation:06d>.json
```

Old generations are never overwritten or deleted.

`git_transport.py` accepts a third kind. The change is three lines: a `KINDS`
tuple, the namespace alternation in the key regex, and the kind check. The fixed
remote/branch, explicit argv, no-force, no-rebase, path validation, 16384-byte
object ceiling and symlink rejection are unchanged, and the `tasks` / `evidence`
behaviour is unchanged.

A registration is never written into `runtime-host-v1/tasks/`, so the Management
Agent cannot scan it as a task.

---

## 4. CC registration rotator

`registration_publisher.py` accepts no command-line arguments. Every path, remote
and binding value comes from root-owned configuration.

One invocation publishes at most one new generation:

1. load the fixed root-owned configuration (`publisher.json`);
2. load `approval.json` and `install-plan.json`, recompute the plan digest locally,
   and compare the approval binding, plan identity, candidate, executor digest and
   Evidence key digest;
3. observe the durable generation state;
4. choose `max(last_generation + 1, deployment_first_generation)`;
5. build the `runtime-host-registration` body;
6. sign it with the existing CC signer (`task-manifest-signing.pem`);
7. self-verify it with the matching public key;
8. persist the exact signed bytes durably, then mark `PREPARED` and `ATTEMPTED`,
   strictly before any network I/O;
9. publish the immutable object;
10. read the object back and compare byte for byte;
11. advance `last_generation` only after a confirmed readback.

Lifetime is the protocol maximum, 86400 s, as a module constant. The rotator never
issues a longer window.

Refused by construction: task publication, arbitrary action, shell, deploy, reboot,
host-selector input, URL input, Production and HK actions. The only action value is
`channel.ACTION == 'RUNTIME_HOST_PROBE_V1'`.

### Generation state

```
/var/lib/go-command-center/runtime-host-v1/registration-generation.json
```

Shape (per the round specification):

```json
{"version": 1, "environment": "...", "host_id": "...", "agent_id": "...",
 "last_generation": 1, "pending": null}
```

`root:root`, mode `0600`, written through a temporary file and `os.replace`, then
`chmod` to `0600`. A generation is never allowed to decrease, and never allowed to
fall below `deployment_first_generation - 1`. An identity change in the state file
is refused.

### Unfinished publication

A pending entry always holds one generation, one signature, one immutable key and
one exact byte string. Recovery works from those stored bytes and nothing else:

| remote state at the pending key | action | outcome |
|---|---|---|
| object present, bytes identical | none | the pending generation is marked published, `pending` is cleared, PASS |
| object absent | retry with the identical key and the identical byte string, then read back | exact readback marks the same generation published, PASS; if still absent the pending entry is left untouched and the run fails |
| object present, bytes differ | none | `publication_conflict`, nothing overwritten, the pending entry is left untouched |

Recovery never re-signs, never builds another body, never increments the generation,
never changes `issued_at` / `expires_at` and never uses a different key. Only the
network step is retried; the signed artifact is immutable. The first attempt of a
cycle reports `publication_unresolved` when the object cannot be read back, and the
next timer tick performs the recovery above. This removes the earlier failure mode
where a push that never reached the remote left rotation stuck until a human edited
the state file.

### Rotation interval and lifetime

Lifetime stays at the protocol maximum of 86400 s (24 h), as a module constant.

The publisher timer runs every 6 h (`OnBootSec=5min`, `OnUnitActiveSec=6h`). A 24 h
registration refreshed every 6 h tolerates several missed publisher cycles before
the installed registration expires.

### First deployment generation

`publisher.json` must carry `deployment_first_generation`. Instruction for this
round is that the first deployment registration must be strictly greater than the
generation already enrolled on the Runtime Host (1), so the deployment value is 2.

---

## 5. rt01 registration sync

`registration_sync.py` accepts no command-line arguments and does not share the
Management Agent's main loop. It is a separate unit of responsibility: a failed
refresh changes nothing about the task protocol, and the Agent keeps running on the
last valid signed registration.

Per invocation:

1. use the existing tasks READ deploy key;
2. list `runtime-host-v1/registrations/`;
3. consider only bodies whose `agent_id` is this host's agent;
4. for each candidate verify the CC signer signature, `environment`, `host_id`,
   `agent_id`, the action list, `candidate_sha`, the plan digest,
   `executor_sha256` (recomputed locally from the installed Management Agent
   bundle) and `evidence_key_sha256` (recomputed locally from the installed
   Evidence public key);
5. pick the highest valid generation;
6. accept only `remote_generation >= local_generation`; a lower generation is
   refused, and the same generation with different bytes is refused;
7. when it is higher, atomically replace `/etc/go-runtime-host/registration.json`
   through a temporary file and `os.replace`;
8. install it `root:root` `0600`;
9. read it back and verify the signature again;
10. print a short JSON status.

Invalid candidates are skipped, not fatal. Candidates that fail signature,
identity, plan, executor, Evidence-key or expiry checks are simply not applied, and
the installed registration is left untouched.

Scan bound: at most the 4 newest registration names are considered. The rotator
publishes every 6 h and a registration is valid for at most 24 h, so any still
usable generation is always inside that window; the bound keeps one timer tick from
turning a year of history into hundreds of repository clones.

Refused by construction: any private key input, arbitrary URL, arbitrary
repository, arbitrary path, task execution and `Runtime.enqueue()`. No shell is
invoked from remote data.

---

## 6. systemd units

All five units were checked with `systemd-analyze verify` (systemd 255, the same
major version as the Runtime Host) inside a staged root that provides the base OS
units and stub executables at the configured `ExecStart` paths. All five return
exit code 0 with no warnings.

### Runtime Host

`go-runtime-host-registration-sync.service` — `Type=oneshot`, `User=root`,
`WorkingDirectory=/opt/go/runtime-host-agent`,
`ExecStart=/opt/go/runtime-host-agent/.venv/bin/python -B /opt/go/runtime-host-agent/registration_sync.py`.

`go-runtime-host-registration-sync.timer` — `OnBootSec=1min`,
`OnUnitActiveSec=5min`, `Persistent=true`.

`go-runtime-host-agent.service` — `Type=simple`, `User=root`,
`ExecStart=/opt/go/runtime-host-agent/.venv/bin/python -B /opt/go/runtime-host-agent/agent_service.py`,
`Restart=on-failure`, `RestartSec=10`, `StartLimitIntervalSec=300`,
`StartLimitBurst=10` (in `[Unit]`, where systemd 255 reads them), `UMask=0077`,
`PrivateTmp=true`, `NoNewPrivileges=true`, `ProtectSystem=strict`,
`ProtectHome=true`, `ProtectKernelTunables=true`, `ProtectKernelModules=true`,
`ProtectControlGroups=true`, `PrivateDevices=true`.

`PrivateNetwork` is deliberately not set for the Agent or the synchroniser: both
must reach GitHub, and the Agent must also reach the ECS instance metadata endpoint
to observe its own cloud identity.

`ProtectSystem=strict` leaves the configuration, keys and bundle read-only. The
only writable paths are the Agent's own state directory and, for the synchroniser,
the installed registration file plus the same state directory. Because
`ProtectHome=true` hides `/root`, `HOME` is redirected into the writable state
directory so git has a home.

### Control Center

`go-runtime-host-registration-publish.service` — `Type=oneshot`, `User=root`,
`WorkingDirectory=/usr/local/libexec/go-runtime-host`,
`ExecStart=/usr/local/libexec/go-runtime-host/.venv/bin/python -B /usr/local/libexec/go-runtime-host/registration_publisher.py`,
same hardening shape, `ReadWritePaths=/var/lib/go-command-center/runtime-host-v1`.

`go-runtime-host-registration-publish.timer` — `OnBootSec=5min`,
`OnUnitActiveSec=6h`, `Persistent=true`.

The timer is not coupled to the existing Boss Request service, and the legacy
six-action enum is unchanged.

### Frozen Runtime unit

The PR #287 Runtime unit is not modified. It keeps `User=go-runtime`,
`PrivateNetwork=true`, `MemoryMax=256M`, `CPUQuota=50%` and `TasksMax=32`, and
receives no GitHub credential, no Evidence private key, no Docker socket and no
Control Center signer.

---

## 7. Observed digests

Management Agent bundle as it will be installed at
`/opt/go/runtime-host-agent` (six files, the blob bytes at the commit of this
round, no CR):

| file | sha256 |
|---|---|
| `adapter.py` | `85d2612086251d1ca0bf313751b130bd49b6469fd477457dd1b3b5da3c0d13ad` |
| `agent_service.py` | `629c6bddba2849a5ff2f8c8672561ecf60b5f44e99d9dc6b54dea8d15f280dbf` |
| `channel.py` | `a18a475720bf3a85bd423e6824e06027653de28879e13896540c7f646fd2fe6a` |
| `flow.py` | `8ee50e74f7bfcb6b83e19f33c5ef1fb7dc46264305b59cdabb1bff1ec19c9be1` |
| `git_transport.py` | `27ed601093476cf62c6c651d1d81fad34dab5d979b0153ccce52bc8c08a16a8c` |
| `registration_sync.py` | `86af565ece5ead475dd382d339a6d5d2e83a832113ed5625b1c1133c39c95af0` |

Canonical manifest is 481 bytes; `executor_sha256` recomputed two independent ways:

```
executor_sha256 = 593a01acf4a593e04e5243673dfe33830e1401de2b7dcf5c865c4d20391e7c7b
```

This differs from the value used by the first host-channel E2E
(`037a8fbaa22163bbfd047e764e676fd55bc8301e768dff924c1092c768e8cf58`) because the
bundle gained `registration_sync.py` and `git_transport.py` changed bytes.

Consequence, recorded here as a deployment prerequisite rather than acted on in
this round: the `executor_sha256` bound in `publisher.json`, in `approval.json` and
in the install plan must be re-pinned to the value above, and the approval record
must be reissued for deployment scope, before the rotator can pass its binding
check. The rotator refuses to publish while the binding does not match.

---

## 8. Deployment bindings

Prepared for the deployment round: a canonical deployment plan and a
deployment-scoped approval record. The same `plan_sha256` is pinned in every place
that must agree, and any mismatch makes the rotator refuse to publish.

```
deployment plan   : /etc/go-command-center/runtime-host-v1/install-plan.json
plan_sha256       : e110bf679fb29c6da12023949f7c6150afa76b69f56f414fcfd311dcedd3216e
approval record   : /etc/go-command-center/runtime-host-v1/approval.json
approval_ref      : approval-6b57fa553b355e4e
approval_status   : HUMAN_APPROVED_RUNTIME_HOST_DEPLOYMENT
generation floor  : 2
rotation interval : 21600 s (6 h)
lifetime          : 86400 s (24 h)
```

The approval record carries `explicitly_not_claimed`: independent authority,
production approval, HK approval, external C1-C14 integration approval. It records
the deployment authorization reported by Eason after the Owner reviewed PR292, and
supersedes the bounded-test record `approval-7b9f6a99599db06b`.

The same `plan_sha256`, the deployment executor digest
(`593a01ac…`) and the deployment evidence key digest (`14a79fdc…`) are pinned
identically in `publisher.json` on the Control Center and in
`registration-sync.json` on the Runtime Host.

---

## 9. Tests

All tests run offline: temporary filesystem, in-memory transport, and a local bare
Git fixture. No network, no real GitHub transport, no SSH, no Runtime or Agent
start, no Task or Evidence publication.

```
PR292 baseline suite (test_adapter, test_channel, test_flow, test_git_transport,
                      test_agent_service, test_cc_test_publisher)
                                          71 tests  OK   (unchanged, not edited)
new suite (test_registration_publisher, test_registration_sync)
                                          46 tests  OK
total                                    117 tests  OK
```

New coverage includes: generation 1 → 2 → 3 progression; generation rollback
refusal; same-generation byte conflict refusal; wrong host, wrong agent, wrong
signer and expired candidate rejection; over-long lifetime rejection; plan /
candidate / executor / Evidence-key mismatch rejection; `registrations` objects not
appearing in a `tasks` or `evidence` key space; cross-namespace path rejection;
unknown-kind rejection; durable state persisted before any network write; ambiguous
push reconciled by readback only, with no second generation; unresolved push never
producing a second generation; conflicting remote object refused rather than
overwritten; atomic replacement; and preservation of the previous registration when
the replacement fails half way.

---

## 10. Known issues recorded, not changed

- `cc_test_publisher.check_binding` reads the plan file without closing the handle
  (`ResourceWarning` under CPython). Left exactly as validated on the real host;
  the tested bytes were not edited in this round.
- Registration scan is bounded to the 4 newest names, as described in section 5.
- The repository has no `.gitignore` on `main`; a WSL test run produced
  `__pycache__` artifacts that had to be removed from the staging area before
  commit. Recorded as an observed hazard.

---

## 11. State carried by this commit

```
REGISTRATION_PUBLISHER = READY   (source + tests)
REGISTRATION_SYNC      = READY   (source + tests)
AGENT_SYSTEMD          = READY   (unit verified)
CC_TIMER               = READY   (unit verified, 6 h interval)
RT01_TIMER             = READY   (unit verified, 5 min interval)

RUNTIME_HOST           = unchanged / STOPPED_HOLD at the time of this commit
MANAGEMENT_AGENT       = unchanged / STOPPED at the time of this commit
REGISTRATION_PUBLISHED = NO      (no real registration written by this commit)
NEW_REAL_TASK          = NO
NEW_EVIDENCE           = NO
EXTERNAL_TASK_TO_C1_C14_RUNTIME = NOT_IMPLEMENTED
REAL_AI_WORKER         = NOT_IMPLEMENTED
```

This document states what the source and the units are. Installing, enabling and
starting them on a host is a separate execution step; its live results are recorded
in the deployment round's own report and are deliberately not restated here.

No repository, credential, key or host was created by this commit.
