# TD-J live proof, fresh signed VERIFY, and the B3-R declared-runtime correction

> 2026-09-16. Three facts are recorded here: the TD-J fix was installed on
> HK-STAGING-01 and proved live; one fresh bounded VERIFY produced a signed
> SUCCESS Evidence that really published; and the runtime pointer's image identity
> was corrected so the declared runtime and the proven runtime agree.
>
> Nothing here is an approval and nothing here authorises a deploy. The request
> switch is unchanged, no deployment plan exists, and `DEPLOY_READY` is `UNKNOWN`.

## 1. TD-J installed on HK-STAGING-01

```text
FILE      /opt/go-hk-agent-rebuilt/hk_agent/transport.py
          6f329b2eae7bc627229002e998cf17ee9d95b2e1fb6fc7cb22a508b52ad5fbe0  (30908 B)
      ->  340da98f95acdb0c212aa116681da8d8344c6da306e44dfcf332c67ee1957de8  (32155 B)
INSTALLED 2026-09-16T07:07:18Z by atomic rename, root:root 0644
BACKUP    /var/backups/HK-CHANGE-20260916T070702Z-tdj-evidence-workspace/
VERIFIED  post-install sha256 equals the approved value; py_compile outside the agent
          tree PASS; import smoke unchanged (VERSION 0.5.7-rebuilt, 13 closed reason
          codes, same 5 failure kinds, same 9 stage mappings, same 6-action allowlist)
          with `_publish_workspace` now present; timer active/enabled, Result=success,
          NRestarts=0; the three following ticks completed with no failure and no
          import or runtime error
```

The agent-side install record lives with the component:
`control-plane/boss-test-pr-live-integration-v1/install/INSTALL.md`.

## 2. A fresh bounded VERIFY, and the Evidence that published

One Request, published with the component's own operator tool, was the whole
workload of this round.

```text
REQUEST        boss-hk-verify-tdjfix-20260916T0729Z-176f2e
REQUEST PR     chenzhenxi1-sudo/go-control-tasks #28  (open, non-draft, 1 file)
REQUEST AUTHOR chenzhenxi1-sudo
REQUEST COMMIT b14bb32fed1ad4a1818933b7771293ab26b16a9f
TASK           go-boss-request-verify-20260916T073128Z-adaf1e8b9da4
NONCE          oOSaQBMal-vM6usb_c6DIIRIqUJiAWyA
TASK SIGNATURE VALID  (verified against the published task identity,
                       SHA256:bkwH368MFv+n+18Pca6MB1jV4jZtBbsn8yjC1bf/hns)
PARAMETERS     candidate_image_id == expected_current_image_id
               == sha256:1c9598d699c21620f4a3b489662f7b11be07acb46440516b74452dd2b6065132
               (derived by the Bridge from the VERIFY baseline; the caller cannot set them)
PASS           15:32:15 -> 15:33:35  (80 s, the deployctl VERIFY really ran)
               processed=1, rejected=84 (all task_not_claimed), no failure record,
               evidence_commits=["abf715029bee0643da02f9d197ddb4f05930156b"]
EVIDENCE       evidence/go-boss-request-verify-20260916T073128Z-adaf1e8b9da4-oOSaQBMal-vM6usb_c6DIIRIqUJiAWyA.json
COMMIT         abf715029bee0643da02f9d197ddb4f05930156b  (2026-09-16T07:33:32Z, parent cd7048f48c9b)
STATUS         SUCCESS          executor_result VERIFY_OK   executor_version 0.4.3-rollback-runtime
SIGNATURE      VALID against the published evidence identity
               SHA256:WZ2gG4WHnO5zmijyK8TSOHFpY+EBkk8TWbSbfbRjFNw
BINDING        Evidence task_id + nonce equal the signed Task's
GATES          alembic_current / alembic_head / api_health / candidate_image /
               compose_baseline / env_baseline / expected_current_image /
               worker_process_liveness all PASS
```

This is the live proof of TD-J. The 2026-09-16T05:02:20Z VERIFY was equally
successful at the executor and lost its Evidence to the workspace collision; this
one published on the first attempt, from the fixed agent.

`SAME_PASS_MULTIPLE_EVIDENCE` was **not observed**: the pass claimed exactly one
Task and published exactly one record. No Task was invented to force the scenario;
the multi-publication path is covered offline by the component's regression tests.

## 3. B3-R — the declared runtime did not match the proven runtime

With freshness resolved, the readiness `VERIFY` gate failed for a second,
pre-existing reason that the freshness failure had masked:

```text
declared   sha256:57beafa250f42eb1319ae561e0b79f432bb80d7171592392303a31446cd8ac6c
           from docs/canonical-baseline/CURRENT_HK_RUNTIME.json  image.image_config_id
verified   sha256:1c9598d699c21620f4a3b489662f7b11be07acb46440516b74452dd2b6065132
           from the signed VERIFY Evidence, and equal to `docker inspect <container>.Image`
           for all eight business services
```

Provenance audit, read-only:

```text
· The file carried both values from its creation (cb6d585, and unchanged through
  edff13f and cf4ba70): image_config_id = 57beafa2… alongside image_id_short =
  1c9598d699c2, which is the short form of the image that is actually running.
· `docker image inspect sha256:57beafa2…` on the host: No such image. The only
  DEPTH48 image present is go-hotel:depth48-runtime-6d0fd905 -> 1c9598d6….
· 57beafa2… appears in exactly six tracked files: this pointer, GO_CURRENT_STATE.md,
  and the two frozen PROJECTION_2026091{4,5} evidence documents that read the pointer.
  A code search returns zero hits in chenzhenxi1-sudo/go-control-evidence and
  chenzhenxi1-sudo/go-control-tasks: no Task and no Evidence ever carried it.
· The pointer's own convention is that this field is the image identity: the
  superseded runtime block records image_config_id = 66c54087…, which is exactly the
  value the control plane used for that generation's DEPLOY/VERIFY identity.
```

So the pointer named an image that is not the runtime, while its own short id and
the signed Evidence named the runtime. The correction is the pointer, not the
comparison: the state projector and the readiness evaluator must keep comparing the
repository-declared runtime against the signature-proven runtime, and the negative
test that asserts DRIFT when they disagree is untouched and still passes.

```text
CORRECTED  docs/canonical-baseline/CURRENT_HK_RUNTIME.json
             image.image_config_id  57beafa2… -> 1c9598d6…
             (image_id_short unchanged and now consistent with it; a note in the
              image block records what was corrected and why)
           docs/project/GO_CURRENT_STATE.md
             the same image identity in the current-state table

NOT TOUCHED  control-plane/command-center-state-v1/evidence/PROJECTION_2026091{4,5}/**
             — those are frozen historical projections. The DIFFER relation they
             recorded was correct at that time, and it stays recorded.
```

## 4. Projection and readiness after the correction

An offline projection was run from the current control bus and evidence sources
(`state_projection.py`, published identities, GO checkout carrying the correction):

```text
runtime_verification_state   MATCH
verdict / image_relation     MATCH / MATCH
repository_declared_image    sha256:1c9598d6…
live_proven_image            sha256:1c9598d6…
```

Deploy readiness, re-run against that projection (13 mandatory gates):

```text
DEPLOY_READY = UNKNOWN          (no mandatory gate FAILed; nine are UNKNOWN)

PASS     APPROVED_CANDIDATE     rc1-depth48-pr52-bd25d7ac exists at bd25d7ac
PASS     SOURCE_BINDING         candidate block agrees with the pointer
PASS     TEST_PR                the candidate commit was built and tested by a signed TEST_PR
PASS     VERIFY                 the live runtime is established by signature-verified
                                Evidence inside its window
UNKNOWN  PACKAGE_BINDING / DEPLOYMENT_PLAN / HUMAN_APPROVAL / CURRENT_RUNTIME /
         LIVE_SWITCH / LIVE_SWITCH_PROVENANCE / CANARY / RELEASE_GATES /
         BRIDGE_ACCEPTANCE      — all nine need a deployment plan bundle

B3 CLEARED (VERIFY PASSes)      B4 OPEN      switch unchanged (false)      no deploy
```

`UNKNOWN` is the correct verdict and is not rounded up: a mandatory live fact
nobody could prove keeps the answer out of `YES`. `YES` would be an observation and
still would not be an approval.

## 5. Gates run after the change

```text
command-center-state-v1             tests 195  failures 0  PASS   (incl. RuntimeSeparationTests:
                                    drift-when-declared-and-proven-disagree still PASS)
command-center-deploy-readiness-v1  tests  63  failures 0  PASS
command-center-candidate-admission-v1 tests 68 failures 0  PASS
command-center-request-visibility-v1 tests 49 failures 0  PASS
boss-test-pr-live-integration-v1    manifest sha256sum -c 21/21 OK

No deploy, no rollback, no migration, no live mutation, no new Task, no new
Evidence, and no second VERIFY Request was created by this round.
```

## 6. NEXT_ACTION

```text
为已 admission 且 TEST_PR PASS 的同一个 canonical RELEASE_CANDIDATE_V1
构建 B4 deployment plan bundle，补齐 PACKAGE_BINDING / DEPLOYMENT_PLAN /
HUMAN_APPROVAL / CURRENT_RUNTIME / LIVE_SWITCH / LIVE_SWITCH_PROVENANCE /
CANARY / RELEASE_GATES / BRIDGE_ACCEPTANCE。

不得执行真实 DEPLOY；先把 readiness 推到 DEPLOY_READY=YES 后停止，
等待当次 Human Approval。
```

The previous NEXT_ACTION ("issue another fresh bounded VERIFY Request") is
withdrawn: a signed VERIFY_OK Evidence exists, it is inside its freshness window,
and the gate that reads it now passes.
