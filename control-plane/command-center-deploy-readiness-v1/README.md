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

## Why this revision exists (CC V1-06.1)

The first revision treated `CANARY` and `RELEASE_GATES` as advisory and reported
the plan's canary declaration instead of re-deriving it. That allowed

```text
DEPLOY_READY=YES   while   the live Bridge would deterministically reject
```

which is worse than no verdict: it reads as permission. So the live Boss Request
Bridge is now the fact source. Its bundle contract
(`boss-deploy-request-v1/go_deploy_request.py`) is ported here rule for rule, the
`BRIDGE_ACCEPTANCE` gate fails whenever those rules would refuse, and **no gate
is advisory any more**.

Load-bearing consequences:

* `CANARY` is `PASS` only when the canary proof itself verifies under the
  published identities, binds to *this* candidate, and completed inside the
  canary window — not because the plan says so.
* `RELEASE_GATES` is `PASS` only when every release gate the live contract
  requires carries `PASS`.
* `LIVE_SWITCH_PROVENANCE` is `PASS` only when the switch state is covered by a
  change record whose declared value equals the observed channel value and which
  is signed by a **Human Approval authority distinct from the Task signer**. A
  switch that is simply `on` keeps the verdict out of `YES`.
* `HUMAN_APPROVAL` now verifies the approval's signature against that same
  distinct authority. If the published contract expresses one key in both roles
  the evaluator reports an identity collision and refuses to call any approval
  proven.
* The Human Approval authority is read from the published identity contract
  (`identity/VERIFIER_IDENTITIES_V1.json`, role `HUMAN_APPROVAL`, identity
  `GO-DEPLOY-HUMAN-APPROVAL-AUTHORITY`). A contract that does not publish it
  fails closed.

A test re-reads the live Bridge's source and fails if any ported constant, exact
field set, topology list, gate name set or freshness window drifts. The copy in
this component therefore cannot silently diverge from the real gate.

## What it reads

| Input | What it is | Required |
|---|---|---|
| `--control-state` | the derived `CURRENT_CONTROL_STATE.json` | yes |
| `--go-repo` | a GO checkout: the two canonical pointer files the state document names, **and** the published verifier identities under `identity/` | yes |
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
  switch-provenance.json
                     the change record for the switch: field, value, changed_at,
                     change_record, approved_by, approval_id, valid window and the
                     before/after digests, signed by the Human Approval authority
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
| `HUMAN_APPROVAL` | yes | an unexpired approval binding the same plan digest, verified against a Human Approval authority distinct from the Task signer |
| `TEST_PR` | yes | the candidate commit has a signed, successful TEST_PR on the control bus |
| `VERIFY` | yes | the live runtime was verified, by signed Evidence, inside the freshness window |
| `CURRENT_RUNTIME` | yes | the verified runtime matches the image the plan expects to be current |
| `LIVE_SWITCH` | yes | the live request switch would accept a DEPLOY request *(live fact)* |
| `LIVE_SWITCH_PROVENANCE` | yes | the switch state is covered by a change record, signed by the distinct approval authority, whose value matches the observed channel |
| `CANARY` | yes | the plan's canary proof verifies, binds to this candidate and is inside its window |
| `RELEASE_GATES` | yes | the plan carries PASS for every release gate the live contract requires |
| `BRIDGE_ACCEPTANCE` | yes | the live Bridge's own rules, re-derived offline, would accept this request |

`advisory_holds` still exists so the document shape is stable, and it is always
empty: a gate the live Bridge blocks on may not be advisory here.

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

Run against `PROJECTION_20260915`, first with no live bundle and then with the
channel configuration read read-only on the Command Center. In both runs
`mandatory_gates=13` and `advisory_holds` is empty.

```text
DEPLOY_READY=NO                          (both runs)

without a bundle
  FAIL     TEST_PR   the TEST_PR for this commit did not succeed: TASK_EXPIRED
  FAIL     VERIFY    the newest verified VERIFY is 164911 s old, window 86400 s
  UNKNOWN  everything not listed, including LIVE_SWITCH and LIVE_SWITCH_PROVENANCE

with the read-only channel bundle
  FAIL     LIVE_SWITCH              deployment_requests_disabled
  FAIL     DEPLOYMENT_PLAN          the plan store holds no plan
  FAIL     TEST_PR, VERIFY          as above
  UNKNOWN  PACKAGE_BINDING, HUMAN_APPROVAL, CURRENT_RUNTIME,
           LIVE_SWITCH_PROVENANCE, CANARY, RELEASE_GATES, BRIDGE_ACCEPTANCE
```

`LIVE_SWITCH` reports `deployment_requests_disabled`, which is the intended
fail-closed posture: the switch is off, so no DEPLOY Request would be accepted.
`LIVE_SWITCH_PROVENANCE` stays `UNKNOWN` because the change record for that
switch state is not yet signed by a Human Approval authority distinct from the
Task signer.

The `identity` block reports `approval_authority_published=false` for this tree:
no separate Human Approval authority is published yet, so an approval presented
today would be refused rather than called proven.

The `TEST_PR` reason changed once the canonical candidate was moved to the PR
head. It used to be "no signed TEST_PR exists for the declared commit 8a22a4fc" —
unsatisfiable, because the controlled channel can only resolve a PR head. It now
names the real failure: the Task exists, was signed, and expired unclaimed. That
is a failure a future round can actually clear.

That is the honest answer. It is not a statement that deploying is a bad idea,
and it is definitely not permission.

## Not installed, and not in scope

```text
INSTALLED=NO     the evaluator is defined and CI verifies it. Nothing schedules
                 it, and no live bundle is published anywhere.
ROLLBACK_READINESS=NOT_IN_SCOPE   CC V1-09 / #104 owns it. This evaluator says so
                                  rather than guessing.
```

It does not create, sign or publish a Task, it cannot open the request switch,
and it does not touch Production.
