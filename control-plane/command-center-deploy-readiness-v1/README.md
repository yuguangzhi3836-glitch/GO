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
* there is no `RELEASE_GATES` gate. The four product-release declarations the
  plan used to carry (`three_end_ux`, `six_vertical_closed_loop`, `sealed_node`,
  `final_release`) were removed from the deploy contract on 2026-09-17: they are
  upstream product-acceptance verdicts, no machine process in this repository can
  produce them, and the live executor never read them. Reporting on them would
  make this evaluator a product reviewer, which is the opposite of the boundary
  Issue #103 draws. The one name that stood for a real technical fact,
  `sealed_node`, is now established by the signed TEST_PR the plan carries and the
  ported TEST_PR proof checks it.
* there is no deploy switch, and nothing that stands in for one. A deployment is
  authorised by the authenticated DEPLOY Request, so `DEPLOYMENT_AUTHORIZATION`
  `PASS`es only when the plan's authorization cites an exact Request digest and its
  id is the **derived form** of that digest. An authorisation that was picked or
  written rather than derived cannot be expressed, and keeps the verdict out of
  `YES`; `LIVE_DEPLOY_MODE` separately reads whether the deployed configuration
  declares that mode at all.
* `HUMAN_APPROVAL` `PASS`es only when the approval is unexpired, binds the same
  plan digest, scope and environment, and names one of those authorised GitHub
  identities. An approval that names anyone else fails the gate, and the live
  Bridge refuses such a request before it reads the plan at all.
* The authority is an **authenticated GitHub identity, not a key** (2026-09-16
  scope reset): no approval is signed, no approval public key is published and
  none has to be rotated. The authorised logins are ported from the live gate and
  a test re-reads `go_deploy_request.py` so the two allowlists cannot drift. See
  `docs/project/CC_V1_SCOPE_20260916.md`.

A test re-reads the live Bridge's source and fails if any ported constant, exact
field set, topology list, gate name set or freshness window drifts. The copy in
this component therefore cannot silently diverge from the real gate.

## What it reads

| Input | What it is | Required |
|---|---|---|
| `--control-state` | the derived `CURRENT_CONTROL_STATE.json` | yes |
| `--go-repo` | a GO checkout: the two canonical pointer files the state document names, **and** the published verifier identities under `identity/` | yes |
| `--live-bundle` | an **operator-supplied, read-only** directory of live-host facts | no |

The plan store (`/etc/go-command-center/deployment-plans-v1`) and the deployed
Command Center configuration are **live-host facts an offline evaluator cannot
read**. When the bundle is absent those gates are `UNKNOWN` *by construction*
rather than assumed — which is exactly why the evaluator can be run safely from
anywhere.

```text
live-bundle/
  <plan_id>.json     the registered plan bundle (plan + approval + the TEST_PR,
                     canary and preflight task and evidence objects)
  channel.json       {"deployment_authorization", "publish_enabled",
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
| `HUMAN_APPROVAL` | yes | an unexpired approval binding the same plan digest, scope and environment, naming one of the authorised GitHub identities |
| `TEST_PR` | yes | the candidate commit has a signed, successful TEST_PR on the control bus |
| `VERIFY` | yes | the live runtime was verified, by signed Evidence, inside the freshness window |
| `CURRENT_RUNTIME` | yes | the verified runtime matches the image the plan expects to be current |
| `LIVE_DEPLOY_MODE` | yes | the deployed configuration declares request-authorised deployments and would accept a DEPLOY request *(live fact)* |
| `DEPLOYMENT_AUTHORIZATION` | yes | the plan's authorisation is derived from an exact authenticated DEPLOY Request: it cites that Request's digest and its id is the derived form of it |
| `CANARY` | yes | the plan's canary proof verifies, binds to this candidate and is inside its window |
| `BRIDGE_ACCEPTANCE` | yes | the live Bridge's own rules, re-derived offline, would accept this request |

`advisory_holds` still exists so the document shape is stable, and it is always
empty: a gate the live Bridge blocks on may not be advisory here.

## Failing closed, in every direction

```
candidate without a usable commit            FAIL
incomplete source identity                   FAIL
plan approves a different source             FAIL
candidate artifact not sealed (durability != PROVEN)  FAIL
                                                   (an image id proves a build, never
                                                   that the built bytes still exist; the
                                                   old digest-suffix rule is gone -- it
                                                   was never satisfiable and no digest
                                                   may be invented to satisfy it)
plan file name != plan_id                    FAIL
expired approval / approval for another candidate  FAIL
no TEST_PR for the candidate commit          FAIL
TEST_PR that did not succeed                 FAIL
VERIFY stale or drifted                      FAIL
runtime drift                                FAIL
mode not request / publish off / DEPLOY not allowed  FAIL
authorisation not derived from a Request     FAIL
plan / approval / channel not supplied       UNKNOWN
live runtime not proven                      UNKNOWN
```

## What it can never do

```text
is_execution_authority=false   can_create_task=false      can_publish_task=false
can_grant_the_deployment_authorization=false  holds_private_key=false
signs_anything=false
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

## The real answer, as re-read on 2026-09-17

Run against the `PROJECTION_20260915` control state, first with no live bundle and
then with the deployed channel configuration read read-only off the Command Center.
In both runs `mandatory_gates=12` and `advisory_holds` is empty.

```text
DEPLOY_READY=NO                          (both runs)

without a bundle
  FAIL     TEST_PR   the TEST_PR for this commit did not succeed: TASK_EXPIRED
  FAIL     VERIFY    the newest verified VERIFY is 164911 s old, window 86400 s
  UNKNOWN  PACKAGE_BINDING, DEPLOYMENT_PLAN, HUMAN_APPROVAL, CURRENT_RUNTIME,
           LIVE_DEPLOY_MODE, DEPLOYMENT_AUTHORIZATION, CANARY, BRIDGE_ACCEPTANCE

with the read-only channel bundle
  FAIL     DEPLOYMENT_PLAN          a bundle was supplied but no usable plan is in it
  FAIL     LIVE_DEPLOY_MODE         deployment_authorization_mode_not_request
  FAIL     TEST_PR, VERIFY          as above
  UNKNOWN  PACKAGE_BINDING, HUMAN_APPROVAL, CURRENT_RUNTIME,
           DEPLOYMENT_AUTHORIZATION, CANARY, BRIDGE_ACCEPTANCE
```

`LIVE_DEPLOY_MODE` reports `deployment_authorization_mode_not_request` because the
configuration installed on that host still carries the pre-2026-09-17 shape
(`deployment_requests_enabled`), which this revision no longer recognises. That is
the intended fail-closed reading of a host that has not been moved to this revision
yet: the installation is the file set `INSTALL_HANDOFF.md` names, and until it is
applied deployments are refused rather than silently governed by a field that no
longer means anything. Nothing else on the host is affected by that refusal — the
read-only probes keep running.

The earlier 2026-09-15 reading of the same two runs reported
`LIVE_SWITCH deployment_requests_disabled` and `LIVE_SWITCH_PROVENANCE UNKNOWN`,
and `mandatory_gates=13`. Those gate names, and the switch they belonged to, are
gone: a deployment is authorised by the authenticated Request, so there is no
standing state for a verdict to establish and no change record to attribute.

The `identity` block reports the two published signing roles and the authorised
approval identities (`approval_identities`). No approval public key is published
or expected: the Human Approval authority is an authenticated GitHub identity.

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

It does not create, sign or publish a Task, it cannot grant a deployment
authorisation, and it does not touch Production.
