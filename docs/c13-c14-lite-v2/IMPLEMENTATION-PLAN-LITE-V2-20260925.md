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

Remote-execution facts (quota, real run id, CI status) are reported in the round
report rather than asserted here, because this file is committed before any remote
run happens.
