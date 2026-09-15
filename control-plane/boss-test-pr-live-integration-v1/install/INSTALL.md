# Installation record - CC V1-02 failure closure (live), and why the shipped scripts were not run

Installed on the Hong Kong host on 2026-09-15, under
`APPROVAL_SCOPE=PRE_DEPLOY_REMEDIATION_ONLY`. The controlled failure scenario is the
one the operator authorised: a `HK_STAGING_TEST_PR` whose builder image
(`go-hotel:aoluguya-direct-r3-1-20260906`) no longer exists on the host, so the
attempt fails at `docker image inspect` — before any container is created and before
anything in the business runtime is touched.

## Only one file needed installing, and one script had to be refused

The candidate ships six HK-side files and two CC-side ones, plus install scripts
pinned to the *archived* baseline. On the live host, five of the six were already
byte-identical to the candidate, and the CC side is already ahead of it:

| file | live before | verdict |
|---|---|---|
| `hk_agent/test_pr.py` | `97fe8c17…` | identical to the candidate — the TEST_PR integration landed on 09-12 |
| `hk_agent/core.py` | `44b04dd8…` | identical |
| `hk_agent/deployment_actions.py` | `7400ef03…` | identical |
| `Dockerfile.go-application-python-v1` | `bec10f47…` | identical, already at `/usr/local/libexec/go-hk-test-pr/` |
| `agent.json` | `55702440…` | already carries the test-pr fragment |
| `hk_agent/transport.py` | `550eecc8…` | **the delta: the failure closure** |

`install/install-command-center.sh` was **not** run and must not be. It installs the
candidate's Bridge and `boss-request-bridge-v1.3.json`, i.e. it would roll the CC host
back from `1.5.0-control-plane-health` with a four-action channel contract to a
`{VERIFY, TEST_PR}` bridge with a version-3 config — regressing live liveness
(#98) to re-add something the CC side never needed for #97. The failure closure is
entirely agent-side; the Request channel was already newer.

`install/install-hk-agent.sh` was also not run as-is: both its `preflight.sh` hash
gates and its `test ! -e` gates describe the state *before* TEST_PR was installed
(`transport.py` = `4301a7e9…`, `agent.json` = `82ab805b…`, no `test_pr.py`), and the
live host is past that. Instead the single delta file was installed with the same
discipline the scripts exist to enforce: live pre-hash recorded, backup taken,
post-hash recorded, permissions and owner set explicitly, syntax compiled first.

## Evidence

```
BEFORE   /opt/go-hk-agent-rebuilt/hk_agent/transport.py
           550eecc865c71896e3c26be4707d544b0bc25a30b6db7e11c21296e5c682db84
BACKUP   /var/lib/go-hk-agent/ccv102-install-backup-20260915T134007Z/transport.py.before
           (hash re-verified equal to the live pre-hash)

AFTER    /opt/go-hk-agent-rebuilt/hk_agent/transport.py
           6f329b2eae7bc627229002e998cf17ee9d95b2e1fb6fc7cb22a508b52ad5fbe0
           root:root 0644, 30908 bytes, identical to the repository working tree
         stale __pycache__/transport.* removed so no cached bytecode can shadow it
         import smoke: VERSION 0.5.7-rebuilt, FAILURE_STATUS FAILED,
         kinds HANDOFF_FAILED/EXECUTION_FAILED/RESULT_REJECT/EVIDENCE_BUILD_FAILED/
         EVIDENCE_PUBLISH_FAILED, 13 closed reason codes

BUSINESS RUNTIME  docker ps --format '{{.Names}}|{{.Image}}' | sort | sha256
                    BEFORE f745da1b38933ef7014d1d345baf52cb70fa7620551fae186b588eea53d6da27
                    AFTER  f745da1b38933ef7014d1d345baf52cb70fa7620551fae186b588eea53d6da27
                  no test-pr container was ever created; the attempt stopped at
                  `docker image inspect`
AGENT             go-hk-agent.timer active, service Result=success ExecMainStatus=0

SMOKE - a fresh Request, so nothing historical was replayed:

  request       boss-hk-test-pr52-ccv102-failure-20260915T1343Z (new request_id,
                published as go-control-tasks PR #22, head 74f151f1c61009ac88afacffb95a3d4486f4616c)
  task          go-boss-test-pr-52-9b2e2fd1d565 (new task_id, deterministic from the request)
  claimed       YES  2026-09-15T13:42:21Z, attempt 1, attempt_budget_exhausted
  outcome       failed, failure_stage subprocess, reason EXECUTOR_NONZERO_EXIT,
                return_code 1, stderr "No such image: go-hotel:aoluguya-direct-r3-1-20260906"
  evidence      go-control-evidence@permission-test commit
                8658efc149a65bce9eaec795bca5c336fc77da4b, one file added
  ledger        ATTEMPT_ROWS = 1  (DUPLICATE_EXECUTION=NO)
                processed status failed, evidence_ref 8658efc1…

  SIGNED_FAILED_EVIDENCE        PASS   status FAILED, signed by the HK evidence identity
  FAILURE_CONTRACT              PASS   validated against failure_evidence_v1.schema.json:
                                       17 required keys, every const/enum/type satisfied,
                                       no unimplemented keyword
  STATE_PROJECTION_EXECUTION_FAILED
                                PASS   lifecycle EXECUTION_FAILED, assertion FAILED,
                                       reason "the signed Evidence reports a non-success
                                       status: kind=EXECUTION_FAILED, stage=subprocess,
                                       reason_code=EXECUTOR_NONZERO_EXIT",
                                       evidence.signature_verified true,
                                       verifier_identity "Hong Kong agent evidence signer"
  RETRY_PERMITTED               FALSE  retry_permitted/replay_authorized/authorizes_any_action
                                       all false, and the projection separately reports that
                                       the artifact claimed none of them
  DEPLOYMENT_PERFORMED          NO
  BUSINESS_RUNTIME_CHANGED      NO

  counts by_lifecycle after the projection: COMPLETE 25, EXECUTION_FAILED 1,
                                            POLICY_HOLD 4, TASK_EXPIRED 20
```

`install/publish_request_pr.py` is the operator tool used to submit the Request. It
publishes bytes it is handed, refuses any shape it does not recognise, and holds no
signing key. `install/validate_against_contract.py` is the contract check above; it
is driven by the contract file itself rather than by a second copy of it.

## A side effect worth recording

The liveness Evidence from #98 aged past its 1800 s window during this work, so
`hk_agent_online` returned to `UNKNOWN` — correctly. `stale Evidence != ONLINE` is
the property the state layer asserts, and it was just observed live rather than only
in a test. Continuity for #98 is the next item on the list for exactly this reason.

## Rollback

```
cp /var/lib/go-hk-agent/ccv102-install-backup-20260915T134007Z/transport.py.before \
   /opt/go-hk-agent-rebuilt/hk_agent/transport.py     # then verify the hash is 550eecc8…
rm -f /opt/go-hk-agent-rebuilt/hk_agent/__pycache__/transport.*.pyc
```

The rollback touches one file. It does not touch the published failure record, the
Task, the business runtime, the agent's ledger or Production. Nothing in this install
writes to the CC host.
