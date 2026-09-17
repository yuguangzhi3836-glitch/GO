# Installation record - CC V1-03 liveness producer (and the Bridge revision it needed)

Installed on the Command Center host (`go-cc`, `i-j6c7k6k01biwlbnwutu5`,
cn-hongkong) on 2026-09-15, under
`APPROVAL_SCOPE=PRE_DEPLOY_REMEDIATION_ONLY`, `OPTION=A`,
`CONTROL_PLANE_HEALTH_BRIDGE_EXTENSION=AUTHORIZED`.

This install is two things at once, because the first one does not work without the
second: it installs the producer, and it installs the Bridge revision that makes the
producer's Request able to become a signed Task.

## Why the Bridge had to change first

`CONTROL_PLANE_HEALTH` was already valid on the HK agent (`core.py` allowlist,
`transport.py` dispatch to a read-only probe) and already understood by the
projector, which answers `hk_agent_online` from signed liveness Evidence and says
"a past success is not proof of current liveness". The producer's own contract
already emitted exactly that action and nothing else.

What refused it was the only Task signer:

```text
validate_request()      action not in {VERIFY, TEST_PR, DEPLOY}          -> Reject("action")
process()               action != VERIFY                                  -> Reject("legacy_mode_verify_only")
armed_process()         action != VERIFY                                  -> Reject("legacy_mode_verify_only")
load_channel() (v4)     allowed_actions must equal exactly three members
```

So the Request could never reach a signature, and `hk_agent_online` could only ever
read `UNKNOWN`. The producer removes the *missing mechanism*; this revision removes
the *missing permission*.

## What was changed in the Bridge (`boss-deploy-request-v1`, `1.5.0-control-plane-health`)

```text
HEALTH_ACTION = "CONTROL_PLANE_HEALTH"
HEALTH_PARAMETERS = {}          a constant, copied -- never derived from the Request
CHANNEL_ACTIONS = [VERIFY, TEST_PR, DEPLOY, CONTROL_PLANE_HEALTH]

validate_request        HEALTH added to the accepted action set. Its field set is the
                        five common fields (schema_version, request_id, action_id,
                        environment, requested_at), so there is no image, service,
                        path, env, command, plan_id or pr_number to carry.
derive_health           builds the Task: fixed empty parameters, HK-STAGING-01,
                        GO-COMMAND-CENTER authority, signed with the existing task key.
derive_formal_task      now an explicit, fail-closed dispatch. This is the substantive
                        fix: before it, an unnamed action fell through to derive(),
                        i.e. it silently became a VERIFY. Now anything not named is
                        refused with action_not_enabled_in_channel.
channel_v4              extracted as a pure function so the contract is testable without
                        a root-owned file; the action list is still compared for exact
                        equality, so health cannot be toggled by editing a field.

UNTESTED-BY-DESIGN, UNCHANGED: the DEPLOY branch, deployment_requests_enabled (still
false), the approved-plan contract, the arm/release budget, and VERIFY / TEST_PR
semantics. No health Request can reach any of them.
```

## What is installed

```
/opt/go-command-center/liveness-producer-v1/command-center/go-liveness-producer
/opt/go-command-center/liveness-producer-v1/command-center/liveness-producer-policy-v1.json
/opt/go-command-center/liveness-producer-v1/contracts/agent_liveness_producer_v1.schema.json
/etc/systemd/system/go-liveness-producer.{service,timer}          300 s, hardened
/var/lib/go-command-center/liveness-producer-v1/                  ledger.jsonl, state.json, outbox/
/usr/local/libexec/go-boss-request-bridge                         replaced: 1.5.0-control-plane-health
/etc/go-command-center/boss-request-bridge-v1.json                action contract, now four members
/etc/go-command-center/boss-request-bridge-v1.manifest.json       the revision record
```

The producer never publishes to the bus. The wiring that does is
`control-plane/liveness-request-transport-v1`, a separate component with its own
timer and its own gate: it reads the outbox, refuses anything that is not a
well-formed `CONTROL_PLANE_HEALTH` Request with the five fields, and relays it
through ONE long-lived branch and ONE pull request. It cannot merge, cannot close,
and is idempotent per request id.

`install/liveness_request_wiring.py` -- the operator wiring that used to live here --
has been **removed**, not deprecated. It opened a new branch and a new pull request
for every probe, which is 48 open pull requests a day, and leaving it in the tree
would have left the forbidden shape one `python` call away.

## Evidence

```
BEFORE   Bridge   sha256 edcac357074d4600ed249322589f70504a4e5981f4cd247b8e8ba066a6d80178  (1.4.0-candidate)
         config   sha256 46915edf708db82dcb68d30b68e32870988a38f5c3dfd3cdc2f85e9309a20164  (3 actions)
         producer, its units and its state dir: ABSENT
BACKUP   /var/backups/CC-CHANGE-20260915T125153Z-health-bridge/  (bridge, config, manifest; hashes recorded)

AFTER    Bridge   503355dbd67d937a3d54721b33a00ad007460626df6dab57ad6121a79e0bf737  (1.5.0-control-plane-health)
         config   dafc81da30a61b1239a642e2ecab12905d20e5e1d325b527f3e6253c9a312f8c  (4 actions)
         producer 3c440600af0213f1c4c47cbc67b1128191e7f207fd1f00953331265cef4b3efe
         policy   ae68665353dd27a318e9343778f8b7986bdb5cba40a61dc024a24a1330cd1ce6
         installed bytes identical to the repository working tree

REVISION source cc/v1-finalization-20260914 @ 4c3391a1edff30c3f57ef316c6210b24780d6682
         the Bridge re-reads its root-owned channel config on every poll, so a config
         that disagreed with the binary fails closed rather than being half-applied

STATE    bridge timer   active/enabled, trigger 20:53:15 +0800, Result=success ExecMainStatus=0
         producer timer active/enabled, trigger 21:05:40 +0800, Result=success ExecMainStatus=0
         bridge ledger unchanged by the swap: sha256 9c795b9dbe478ec8109ae523d00b05f3846ecb32825f74bdb0cbb4721a22265b,
         20 requests (18 published, 2 ignored)
         deployment_requests_enabled is still false in the live config

GATES    boss-deploy-request-v1   bridge self-test 35/35 OK; run_checks PASS
                                  (manifest 9/9; 35 new checks + 35 bridge regressions)
         agent-liveness-producer-v1  selftest 28 PASS

SMOKE - the whole chain, one real probe:

  LIVENESS_REQUEST        producer tick 1 -> PUBLISHED, request_id liveness-control-plane-health-994153
                          outbox file carries exactly the five fields; LIVENESS_CLAIM=NONE
                          tick 2 in the same bucket -> DUPLICATE, nothing written
  REQUEST PR              go-control-tasks #21, branch boss-request-liveness-control-plane-health-994153,
                          head b17b1c939d8e235a5c0615026cc8d833d4bebdb5, 1 file added, non-draft
  BRIDGE_VALIDATION       accepted the action, validated the five-field schema, signed
  SIGNED_HEALTH_TASK      go-boss-health-20260915T125442Z-7b3296f6616f
                          parameters {} / environment HK-STAGING-01 / authority GO-COMMAND-CENTER
                          published to tasks/ on main at commit 01ac960455a935ceeb26cb9e84e4deff19e3a588
  HK_AGENT_PICKUP         claimed 2026-09-15T12:55:22Z, processed 12:55:29Z
  READ_ONLY_EXECUTION     eight gates PASS (schema, authority, environment, expiry, replay,
                          allowlist, signature, plus the executor's own); payload is
                          hostname / memory / disk / repo reachability and nothing else
  SIGNED_EVIDENCE         evidence/go-boss-health-…-8bZkK5Omk6PFHvp3hSmKl7T-EGyVUIWZ.json
                          at go-control-evidence@permission-test commit 4db0d0e8242a24624555a5d8d52e739a24d1dbd7
  STATE_PROJECTION        control_state.hk_agent_liveness.state = PROVEN,
                          "signature-verified liveness Evidence inside the freshness window"
  ANSWER SURFACE          CONTROL_STATUS_V1.json -> answers.hk_agent_online.state = PROVEN
                          (age 547 s, agent 0.5.7-rebuilt, host iZj6ccs8t04f1p4d8pe69zZ)

SMOKE - the negatives, as tests rather than as prose:

  health request with parameters ......... REJECT (schema_fields)   test_health_request_with_any_parameter_is_rejected
  wrong environment ..................... REJECT (environment)     test_health_wrong_environment_is_rejected
  unknown action ........................ REJECT (action)          test_health_unknown_action_is_rejected
  health -> deploy fallthrough .......... IMPOSSIBLE               test_health_cannot_fall_through_into_the_other_actions
  health -> test_pr fallthrough ......... IMPOSSIBLE               test_health_cannot_fall_through_into_the_other_actions
  health -> verify fallthrough .......... IMPOSSIBLE               test_unnamed_action_cannot_become_a_verify_task
  health in the deploy gate/arm ......... IMPOSSIBLE               test_health_cannot_participate_in_the_deploy_arm
  channel without health ................ REJECT                   test_channel_without_the_health_action_is_refused
  channel with a fifth or reordered set . REJECT                   test_channel_rejects_an_unknown_or_reordered_action
  existing three actions unchanged ...... PASS                     test_existing_actions_are_unchanged_by_the_health_extension
  unsigned / unverified probe != ONLINE . PASS                     test_fresh_unverified_probe_is_observed_never_proven
  stale probe != ONLINE ................. PASS                     test_stale_probe_is_unknown_and_reports_last_seen
  a past success != ONLINE .............. PASS                     test_successful_verify_never_implies_agent_online

ROLLBACK systemctl disable --now go-liveness-producer.timer
         rm /etc/systemd/system/go-liveness-producer.{service,timer}; systemctl daemon-reload
         rm -rf /opt/go-command-center/liveness-producer-v1 /var/lib/go-command-center/liveness-producer-v1
         restore the Bridge, its config and its manifest from
         /var/backups/CC-CHANGE-20260915T125153Z-health-bridge/ (the recorded hashes are the check)
         then restart go-boss-request-bridge.timer.
         The rollback does not touch the HK agent, the runtime, the ledger, the evidence
         repository or Production. The already-published health Task and its Evidence are
         records; they are not deleted by a rollback and do not need to be.

BOUNDARY EXECUTION_AUTHORITY=NO / DEPLOYMENT_AUTHORITY=NO / DEPLOY_PERFORMED=NO
         PRODUCTION_TOUCHED=NO / deployment_requests_enabled=false (unchanged)
         VERIFY, TEST_PR and DEPLOY permissions and semantics unchanged
         the health path cannot carry image/service/path/env/command, cannot become
         VERIFY/TEST_PR/DEPLOY/ROLLBACK, and takes no part in the arm, the approved plan
         or the release budget
         HUMAN_APPROVAL_SIGNER == TASK_SIGNER remains a separate blocker for Step 6 and
         was NOT addressed or excused by this authorization
```
