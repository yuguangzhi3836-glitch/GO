# C13/C14 Lite V2 — GitHub ephemeral execution backend

This package is the **execution backend** for two cells the Owner already defined.
It does not define, rename or replace them, and it is not a scheduler.

```text
cell identity       C13 / C14                      — the Owner's 14-Cell model
task identity       existing ledger / issue task   — ci/round2/validate_ledger.py
execution identity  one GitHub Actions run         — this package
```

A C14 run and a C13 run each produce one **sealed bundle**. The bundles are bound
to the existing ledger as the `c14` / `c13` gate evidence, with the two AI
execution identities as the two `reviewer` values the ledger already requires to
differ. Nothing here creates a task registry, a cell registry or a state machine.

## What each cell is

| Cell | Is | Is not |
|---|---|---|
| C14 | constitution, permission / IAM, legal, regulatory, contract, AI-behaviour rules | a second quality tester; it runs no Docker, no PostgreSQL, no regression / recovery / journey suite |
| C13 | independent quality acceptance: regression, security, recovery, journey, frozen machine inventory | the author's own self-test; self-test is never accepted as C13 |

Order is **C14 first, then C13 on the same frozen candidate**. `NOT_APPLICABLE` is
a recorded C14 terminal state with scope, basis and rule version — never a skip.

## Files

| File | Role |
|---|---|
| `lite_canonical.py` | canonical JSON + SHA256, same convention as `go_deploy_request.py` |
| `lite_errors.py` | `Reject` / `Block` vocabulary and the six failure classes |
| `lite_candidate.py` | frozen candidate contract, freshness, dispatch binding |
| `lite_review_brief.py` | the task the candidate was answering: its pull request, resolved read-only and matched uniquely (or refused) |
| `lite_identity.py` | execution identity and machine-checked independence |
| `lite_bundle.py` | sealed C14 / C13 bundles, `NOT_APPLICABLE` record, roots |
| `lite_prerequisite.py` | the C13 prerequisite gate over the sealed C14 record |
| `lite_execution_record.py` | how one execution is identified to the ledger |
| `lite_github_run.py` | run / artifact identity assertions, digest recomputation |
| `lite_readback.py` | same-run (or terminal) API readback of run + artifact |
| `lite_ledger_binding.py` | adapter onto the **existing** `ci/round2` ledger validator |
| `lite_chain.py` | end-to-end verification of one C13+C14 round |
| `lite_ai_reviewer.py` | read-only structured-output reviewer + quota classification |
| `lite_cli.py` | the entry point the workflows call |
| `lite_schemas.py` | generates `schemas/*.json` from the enforced field tuples |
| `lite_workflow_check.py` | offline workflow contract checks |
| `lite_fixtures.py` | synthetic fixtures — clearly synthetic, never live facts |
| `test_lite_*.py` | contracts, positive lifecycle, 24-case negative suite, ledger integration |

## Independence, precisely

Machine-checked, not documented:

```text
implementation_execution_id != c13_execution_id
implementation_execution_id != c14_execution_id
c13_execution_id            != c14_execution_id
c13_github_run_id           != c14_github_run_id
c13_nonce                   != c14_nonce
```

`Independent` means *independent AI review execution* and nothing more. It is not
an independent authority, organisation, GitHub account, cloud account, ECS, HSM,
KMS, WIF or registration authority.

## Nothing here can act

Every record carries `authorizes_any_action = false`. A
`DEPLOYMENT_ELIGIBLE` preview is a statement about evidence; a human still issues
the deployment instruction, and C13/C14 can never deploy, merge or restart.

## Run the suite

```sh
python -m unittest discover -s control-plane/c13-c14-lite -p 'test_*.py'
python control-plane/c13-c14-lite/lite_schemas.py --check
python control-plane/c13-c14-lite/lite_workflow_check.py
```

## What is deliberately not here

No witness layer, no aggregator, no `FINAL_ROOT`, no receipt verifier, and no signature
chain whose only purpose would be to prove that a reviewer was independent. Since
*independent AI review execution* means a fresh API execution with its own prompt and its
own correct input, this package records that execution and the two identities the ledger
already requires to differ - and nothing more. GitHub records which run produced which
record; a second root over those same fields would protect against nothing.

## Which commit the backend runs from

The production workflows execute the backend from **the run's own commit**
(`github.sha`) and check the reviewed candidate out separately at `candidate_sha`.

```text
EXECUTION_BACKEND_SHA    = github.sha      # which code did the review
REVIEWED_CANDIDATE_SHA   = candidate_sha   # what was reviewed
```

The two are different things and are never assumed to be equal. Nothing outside the
default branch has to stay alive for a dispatch to work.
