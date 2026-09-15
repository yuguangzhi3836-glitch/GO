# CC V1-07 — DEPLOY dry-run rehearsal

Issue: **#102 · CC V1-07｜部署预演｜验证 DEPLOY Request Dry-Run 与拒绝路径**

Rehearses the DEPLOY Request path and publishes nothing.

```
TASK_CANDIDATE   every blocking check PASSes; a non-executable candidate was produced
REJECTED         at least one blocking check FAILs
UNPROVEN         nothing refused, but something could not be established
```

`REJECTED` outranks `UNPROVEN`: one definite refusal decides the outcome whatever
else is unknown. `UNPROVEN` is never a pass.

## A TASK_CANDIDATE is not a Task

```json
{"kind": "TASK_CANDIDATE",
 "executable": false, "signed": false, "publish_authorized": false, "signature": null,
 "parameters_source": "APPROVED_PLAN_BUNDLE",
 "candidate_is_a_task": false}
```

It carries no nonce, no validity window and no signature. This component holds no
private key and has no code path to a signer, a publisher or an executor, so the
candidate cannot become work without a separate, approved, human-authorised
issuance. `DEPLOY_PERFORMED` is false in every outcome, including a legal one.

## What it reads

| Input | What it is | Required |
|---|---|---|
| `--request` | one DEPLOY Request file | yes |
| `--deploy-readiness` | the read-only verdict from CC V1-06 | yes |
| `--store` | an append-only dry-run record store | no |
| `--consumed-history` | a read-only export of what the live channel has consumed | no |

The candidate's every value — `plan_id`, `source_commit`, `candidate_image_id`,
`expected_current_image_id` — is read out of **the approved plan the readiness
verdict approved**. No image, service list, path, environment file, shell command
or executor path is accepted from a caller at all.

A record is an observation: `consumes_nothing: true`. Only the live channel
consumes a plan or an approval. Rehearsing the same Request twice against the same
store is refused as `duplicate_request_id` rather than silently re-run, and the
record is written once because its id is the request identity.

## Four stages, in order, all reported

| Stage | Checks |
|---|---|
| `REQUEST_SHAPE` | readable, size, JSON, duplicate keys, field set, schema version, request_id, action, environment, `requested_at` type / format / freshness, `plan_id`, file-name binding |
| `REQUEST_IDENTITY` | this request_id has not already been rehearsed against this store |
| `PLAN_CONSUMPTION` | the live channel has not already consumed this plan or approval |
| `READINESS` | one check per gate from the readiness verdict |

A later stage is still evaluated and reported even when an earlier one already
refused, so **one run shows every problem** rather than the first one.

## No new refusal vocabulary

Every request-side reason is a token the Boss Request Bridge can itself raise, and
the test suite extracts the Bridge's own vocabulary from its three sources — both
call shapes, 96 tokens — and fails if this component can emit anything outside it.
The check table lives in the contract, so a check cannot be declared in prose and
forgotten in code, and every declared check is asserted to have a code path.

Gate-derived refusals use the gate name as the reason code with
`reason_origin = DEPLOY_READINESS_GATE`, so a refusal always names which of the two
things refused: the channel vocabulary or the readiness gates.

## Failing closed

```
missing / unreadable / oversized Request            rejected with its own token
duplicate JSON key                                  rejected
wrong field set, schema version, action, environment rejected
stale or future requested_at                        rejected
plan_id malformed, file name not bound to request_id rejected
already rehearsed request_id                        rejected
plan or approval already consumed                   rejected
any FAILing readiness gate                          rejected, reason = the gate name
no store supplied                                   UNPROVEN (a replay cannot be detected)
no consumed history supplied                        UNPROVEN (live consumption unknown)
any UNKNOWN readiness gate                          UNPROVEN
a YES verdict that cannot name what it approved     rejected
```

## Usage

```sh
python control-plane/command-center-deploy-dry-run-v1/command-center/go-deploy-dry-run \
  dry-run --request <requests/<request_id>.json> \
          --deploy-readiness <DEPLOY_READINESS.json> \
          [--store <dir>] [--consumed-history <file>] \
          --now <ISO8601> --out <dir>

python control-plane/command-center-deploy-dry-run-v1/command-center/go-deploy-dry-run selftest
python control-plane/command-center-deploy-dry-run-v1/run_checks.py <outdir>
```

## Verified, not installed

```
INSTALLED=NO     the rehearsal is defined and CI verifies it. Nothing schedules it,
                 no request is ever picked up automatically, and no live bundle is
                 published anywhere. It is a rehearsal of the path, not a running
                 part of it.
```

It never publishes a DEPLOY Task, never touches the deploy enable switch, never
executes a deployment, never contacts Hong Kong and never touches Production.
