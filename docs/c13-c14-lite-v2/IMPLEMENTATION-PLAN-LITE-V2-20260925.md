# C13/C14 Lite V2 — implementation plan and this round's outcome

- Baseline reference: **PR #247** @ `4c6561b4` (`DESIGN_AND_FACT_BASELINE_ONLY`).
  Sourced by reference only: `#247` is not merged, is not evidence, and no part of
  this round's code was pushed into it.
- This branch: `cc/c13-c14-lite-v2-github-backend-20260925`, based on `origin/main`
  `aa2ec62b`.

## What this round did

| Work package | Content | State |
|---|---|---|
| **L0** | repository recon → `IMPLEMENTATION-MAP-20260925.md` (KEEP / MODIFY / NEW / DROP_FROM_HARD_PATH) | done |
| **L1** | contracts + JSON schemas + engine + CLI (`control-plane/c13-c14-lite/`) | done |
| **L1b** | the two production workflows + a `POC_ONLY` quota/readback workflow | done |
| **L1c** | negative suite (24 cases) + synthetic positive lifecycle + ledger integration | done |
| **L2** | remote minimal PoC (real AI quota + same-run run/artifact readback) | see the round report |
| **L3** | CC `ReviewVerifier` / `WitnessLedger` / `FinalAcceptanceAggregator` | **next round** |
| **L4** | HK `AcceptanceWitness` + independent witness key | **next round** |
| **L5** | local end-to-end harness | covered by the synthetic lifecycle + ledger integration |
| **L6** | scheduler / issue writeback wiring | **next round** (`DRY_RUN` adapter only, this round) |

## Contract decisions worth recording

1. **One C14 record type** carries `PASS_SCOPED / FAIL / BLOCKED / NOT_APPLICABLE`.
   The `not_applicable` stanza is mandatory for `NOT_APPLICABLE` (scope, basis,
   rule set, rule version, why) and forbidden for every other verdict.
2. **Roots are recomputed from received bytes.** `C14_ROOT` / `C13_ROOT` are
   SHA256 over the canonical record without its own root field. A bundle whose
   verdict, findings or candidate was edited after sealing fails on recomputation.
3. **Artifact identity never lives inside the sealed record** (that would be
   circular). It lives in the execution record, and its GitHub-computed digest is
   re-derived from the downloaded zip.
4. **The dispatch input is per cell** (`c14_task_id`, `c13_task_id`, and one ledger
   reference each), because one round is two executions of two cells with two
   different ledger tasks. Bundles must match their own cell's task exactly.
5. **`FAIL`/`BLOCKED` C14 blocks C13** — `BLOCK`, not `REJECT`: it is a legitimate
   state that must not unlock a formal C13 acceptance. A *candidate mismatch*, by
   contrast, is a `REJECT`.
6. **A quota failure is `BLOCKED` with `failure_class = AI_QUOTA_EXHAUSTED`** —
   never `FAIL`, never a fallback to the author's own review.
7. **The stub reviewer is permanently labelled** `LOCAL_STUB_DETERMINISTIC`, and
   the round decision records the provider per cell, so a synthetic pass can never
   be mistaken for a real AI review.

## Acceptance answers

```text
14_CELL_ISSUE_MODEL_PRESERVED                 = YES   (validator imported by path, unmodified)
NEW_PARALLEL_C13_C14_SCHEDULER_CREATED        = NO
C14_LITE_BACKEND_IMPLEMENTED                  = YES
C13_LITE_BACKEND_IMPLEMENTED                  = YES
C14_DOES_NOT_DUPLICATE_C13_QUALITY_MACHINERY  = YES   (no Docker / PostgreSQL in the C14 record or workflow)
C13_MACHINE_AND_AI_JOBS_CREDENTIALLY_SEPARATE = YES
ISSUE_TASK_BINDING_ENFORCED                   = YES
CELL_ID_BINDING_ENFORCED                      = YES
FRESH_EXECUTION_ENFORCED                      = YES   (one ai_execution_id per role, machine-checked)
SAME_CANDIDATE_BINDING_ENFORCED               = YES
C14_PREREQUISITE_ENFORCED                     = YES
TAMPER_DETECTION                              = YES
AUTHORIZE_ANY_ACTION                          = NO
```

## Remote evidence (POC_ONLY workflow, this branch)

The quota probe and the same-run readback were obtained by a real run, not asserted
here in advance. Final run `36110672586` @ `cec9646d` concluded **success** with:

```text
AI_CREDENTIAL_USABLE = YES      a real provider response came back (execution id present)
AI_FAILURE_CLASS     = NONE     no provider / quota failure was reported
AI_REVIEW_VERDICT    = BLOCKED  the model's own verdict on the synthetic POC scope
READBACK             = run identity + artifact name + GitHub-computed digest verified
                       artifact *bytes* NOT re-hashed
```

⇒ the historical `You have no credits remaining` does **not** reproduce: the AI
credential is usable, so D-1 is no longer the blocker it was.

### Finding: the artifact ZIP (and the job log) cannot be fetched with this credential

Downloading the artifact zip fails with
`Server failed to authenticate the request` from the storage endpoint that both
`GET /actions/artifacts/{id}/zip` and `GET /actions/jobs/{id}/logs` redirect to —
from inside the run (with the default `GITHUB_TOKEN`) and from this workstation
(with the account token) alike.

Consequences for the design, recorded deliberately:

1. The V1 binding that **is** achievable and is enforced here is the one in the
   task's own section 6 step 2: `run.status/conclusion/head_sha/path` plus
   `artifact.workflow_run.id`, `artifact.name` and **`artifact.digest`, which
   GitHub computes and the submitter cannot self-report**.
2. The additional step 3 check (download the zip and re-hash it) is **not
   achievable with the default credential**. `lite_readback.py` therefore keeps
   `--bytes-mode strict` as its default and records
   `bytes_verified=false` + the reason only when explicitly asked to degrade; a
   caller that needs the byte proof must use a credential that can read the
   storage endpoint, and the next round's CC/HK witness is the right place for it.
3. `head_sha` is the workflow ref commit, never the reviewed candidate. The
   candidate is bound by the in-run `git rev-parse HEAD` check, the artifact name
   and the sealed bundle. Passing the wrong expectation here was a real failure,
   now guarded by an offline workflow check.

The synthetic stub remains the only thing that produces a PASS in this repository:
the real provider answered `BLOCKED` for the POC scope, which is exactly why the
POC scope is not a product candidate.
