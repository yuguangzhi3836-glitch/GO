# CC V1-06 — read-only Deploy Readiness evaluator

Issue: **#101 · CC V1-06｜部署判定｜实现只读 Deploy Readiness Evaluator**

Answers one question without doing anything: **can we deploy now, and if not, why not.**

```
DEPLOY_READY = YES       every mandatory gate PASSes
DEPLOY_READY = NO        at least one mandatory gate FAILs
DEPLOY_READY = UNKNOWN   no mandatory gate FAILed, but at least one could not be established
```

`UNKNOWN` is a first-class answer. A mandatory fact nobody could prove keeps the
verdict out of `YES` instead of being rounded up, and **`YES` is not an approval**
and authorises nothing.

## What it reads

| Input | What it is | Required |
|---|---|---|
| `--control-state` | the derived `CURRENT_CONTROL_STATE.json` | yes |
| `--go-repo` | a GO checkout, for the two canonical pointer files the state document names | yes |
| `--live-bundle` | an **operator-supplied, read-only** directory of live-host facts | no |

The approved plan store (`/etc/go-command-center/deployment-plans-v1`) and the
live Command Center request switch are **live-host facts an offline evaluator
cannot read**. When the bundle is absent those gates are `UNKNOWN` *by
construction* rather than assumed — which is exactly why the evaluator can be
run safely from anywhere.

```text
live-bundle/
  <plan_id>.json     the six-field approved plan bundle (plan + approval + the
                     canary/preflight task and evidence objects)
  channel.json       {"deployment_requests_enabled", "publish_enabled",
                      "allowed_actions", "allowed_environment"}
```

Symlinks are refused and every file is size-capped, matching the plan store's own
rules.

## The closed gate set

| Gate | Mandatory | What it means |
|---|---|---|
| `APPROVED_CANDIDATE` | yes | an approved candidate exists and declares a source at all |
| `SOURCE_BINDING` | yes | the candidate's own source identity is complete |
| `PACKAGE_BINDING` | yes | the plan approves **this** candidate, and its image/repo-digest pair is consistent |
| `DEPLOYMENT_PLAN` | yes | an approved plan exists for the release *(live fact)* |
| `HUMAN_APPROVAL` | yes | a well-formed, unexpired approval binding the same release *(live fact)* |
| `TEST_PR` | yes | the candidate commit has a signed, successful TEST_PR on the control bus |
| `VERIFY` | yes | the live runtime was verified, by signed Evidence, inside the freshness window |
| `CURRENT_RUNTIME` | yes | the verified runtime matches the image the plan expects to be current |
| `LIVE_SWITCH` | yes | the live request switch would accept a DEPLOY request *(live fact)* |
| `CANARY` | no | the plan declares canary digests |
| `RELEASE_GATES` | no | the plan's declared release gates |

Advisory gates are reported in `advisory_holds` and can never change the verdict —
and they are never omitted either, so a declared gate sitting at `HOLD` stays
visible.

## Failing closed, in every direction

```
candidate without a usable commit            FAIL
incomplete source identity                   FAIL
plan approves a different source             FAIL
repo_digest suffix != image_id               FAIL  (the existing Hong Kong contract
                                                   requires equality; a real image that
                                                   does not satisfy it is refused, never
                                                   accommodated by inventing a digest)
plan file name != plan_id                    FAIL
expired approval / approval for another candidate  FAIL
no TEST_PR for the candidate commit          FAIL
TEST_PR that did not succeed                 FAIL
VERIFY stale or drifted                      FAIL
runtime drift                                FAIL
switch closed / publish off / DEPLOY not allowed  FAIL
plan / approval / switch not supplied        UNKNOWN
live runtime not proven                      UNKNOWN
```

## What it can never do

```text
is_execution_authority=false   can_create_task=false      can_publish_task=false
can_open_the_request_switch=false  holds_private_key=false  signs_anything=false
accepts_caller_supplied_parameters=false  touches_production=false
is_a_deploy_approval=false     may_read_live_command_center_state=true
```

Every document it writes carries those ten values, the projection refuses a
verdict whose boundary block disagrees with them, and there is no code path from
a verdict to an executor. It also refuses any caller-supplied image, service,
path, environment or command: those values come from the plan, never from an
argument.

## Usage

```sh
python control-plane/command-center-deploy-readiness-v1/command-center/go-deploy-readiness \
  evaluate --control-state <CURRENT_CONTROL_STATE.json> --go-repo <GO> \
           [--live-bundle <dir>] --now <ISO8601> --out <dir>

python control-plane/command-center-deploy-readiness-v1/command-center/go-deploy-readiness selftest
python control-plane/command-center-deploy-readiness-v1/run_checks.py <outdir>
```

Then the projection carries the verdict:

```sh
python control-plane/command-center-state-v1/state_projection.py ... \
  --deploy-readiness <dir>/DEPLOY_READINESS.json
```

which surfaces it as `control_state.deploy_readiness` (`YES` / `NO`, or
`UNKNOWN` with a null value) plus `control_state.deploy_readiness_gates` with the
per-gate detail, and moves
`control_state.out_of_scope.deploy_readiness_evaluation` to `EVALUATED_READ_ONLY`.

## The real answer, as of the committed projection

Run against `PROJECTION_20260914` with no live bundle:

```text
DEPLOY_READY=NO
blocking  TEST_PR (the candidate commit 8a22a4fc has never been TEST_PR'd on the
                   control bus), VERIFY (the newest verified VERIFY is 116193 s old,
                   outside the 86400 s window), CURRENT_RUNTIME, PACKAGE_BINDING,
                   DEPLOYMENT_PLAN, HUMAN_APPROVAL, LIVE_SWITCH
advisory  CANARY, RELEASE_GATES (both unprovable without a plan)
```

That is the honest answer: two definite refusals and five facts nobody has
established. It is not a statement that deploying is a bad idea, and it is
definitely not permission.

## Not installed, and not in scope

```text
INSTALLED=NO     the evaluator is defined and CI verifies it. Nothing schedules
                 it, and no live bundle is published anywhere.
ROLLBACK_READINESS=NOT_IN_SCOPE   CC V1-09 / #104 owns it. This evaluator says so
                                  rather than guessing.
```

It does not create, sign or publish a Task, it cannot open the request switch,
and it does not touch Production.
