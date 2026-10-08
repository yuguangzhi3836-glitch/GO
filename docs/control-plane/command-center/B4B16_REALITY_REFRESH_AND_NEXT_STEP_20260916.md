> **HISTORY / BREAK-GLASS REFERENCE**
>
> This document is not the normal current operating path.
>
> Normal deployment and inspection are defined by [`/AGENTS.md`](../../../AGENTS.md) and use GO Forge.
>
> Do not issue `HK_STAGING_*` requests unless the Owner explicitly authorizes Old Command Center fallback mode.

---

# B4-B1.6 — reality refresh: where CC V1 actually stands against the new #103

Date: 2026-09-16
Scope: **read-only.** No code change, no live access, no install, no Request / Task /
Evidence, no TEST_PR / VERIFY / CANARY / DEPLOY / ROLLBACK, no switch, no RDS, no
database, no Production. The only repository change is this record plus the handoff
corrections in §7.

This round exists because #103 gained a Scope Clarification and an Authority Boundary,
and because a decision on the next step must come from the current state rather than
from a two-day-old snapshot.

## 1. What was re-read from GitHub (not from cached context)

```text
PR #109              open / Draft=true / merged=false / base main 8610a4db
head                 cc/v1-finalization-20260914 @ 1c3615379df1b3f9e15647bc6089e5449b9200e8
                     (67 commits, 218 files, +38301 -935)
Issue #103           open, updated 2026-09-16T15:44:00Z, 2 comments
Issue #104..#108     all open, last touched 2026-09-14
local vs origin      0 ahead / 0 behind — no foreign commits to audit
The GitHub head equals the local head, so nothing was reset, rebased or overwritten.
```

The two new #103 sections are read and adopted:

* **Scope Clarification** — controlled RDS / Alembic forward migration is part of
  #103, with the new acceptance labels (`MIGRATION_SOURCE_BOUND`, `RDS_PRESTATE_MATCH`,
  `ALEMBIC_FORWARD_MIGRATION`, `RDS_POSTSTATE_MATCH`, `MIGRATION_EVIDENCE`,
  `ARBITRARY_SQL_ALLOWED=NO`, `DESTRUCTIVE_DOWNGRADE_ALLOWED=NO`), the explicit
  forbiddens (arbitrary SQL, caller-controlled revision, arbitrary shell into RDS,
  destructive downgrade/reset/drop, blind retry, migration A + image B, Production),
  and the required order (candidate → tested lineage → live pre-state → forward
  migration → post-state → cutover → VERIFY → Evidence). A candidate that needs no
  migration keeps the image-only path.
* **Authority Boundary** — `CC validates deployability, not product desirability`.
  CC may not refuse for "we never did this", "the business change is large", "the
  design is unusual", "CC would have implemented it differently", or "upstream chose
  something new that already passed its own approval". Refusals must be objective,
  machine-readable and repairable.

## 2. Conflicts between the current work and the new #103

**C1 — the migration capability does not exist at any layer (V1, but not the nearest
step).** Today a legitimate Alembic migration is refused three times over:

```text
candidate admission   MIGRATION_REQUIRED = False                 -> REJECT candidate_migration_required
deploy gate           any(plan[k] is not False for k in
                      ['migration','production','automatic_rollback'])
                                                                 -> Reject('forbidden_operation')
HK executor           no migration capability at all; only the read-only VERIFY
                      gates alembic_current / alembic_head
```

`migration_required=true → refuse` can no longer be the final V1 behaviour, and it is
also the clearest instance of the Authority Boundary problem: it refuses for a policy
reason rather than a deployability fact. **It does not block the imminent deploy**,
because the canonical candidate is image-only (live head `0133_flight_change_plan` ==
its `migration_head`). It blocks the boss-side product versions that already exist
(`0136_merge_go_ai_journey`, then `0137`). Scheduled, not started: see §6.

**C2 — the Authority Boundary is otherwise already satisfied.** Apart from C1, the
candidate contract refuses only for objective reasons (mutable source, digest
mismatch, artifact/evidence/package disagreement, topology, rollback target). No
product-desirability rule was found, and none was added.

**C3 — the handoff's own entry point had drifted (fixed here).** §11's NEXT_ACTION
still described installing the B4-B1.2 files and issuing two fresh TEST_PR runs —
work completed in B4-B1.3, round 2 and B4-B1.5. §12 still declared CI red, which was
true at `eef48f8`/`789d6ba` and is false at HEAD (11 check-runs, 0 failure). Left
uncorrected, the next session would have started by redoing finished work. Both are
now dated notes in place, with the older text kept readable rather than rewritten.

**C4 — the committed control-state projections are stale inputs, and they are
supposed to be.** `PROJECTION_20260914/20260915` are immutable historical records
(their README says so). Readiness computed from the 09-15 one reports
`TEST_PR=FAIL(TASK_EXPIRED)` and `VERIFY=FAIL(164911 s old)`. Those are artifacts of
the input, not defects: see §3.

**C5 — the deployment path is fail-closed by design.** The current channel enables
`HK_STAGING_VERIFY`, `HK_STAGING_TEST_PR`, `CONTROL_PLANE_HEALTH` and keeps
`CANARY`/`DEPLOY` disabled with `deployment_requests_enabled=false`. That is the
required posture, not a defect; opening it is a human decision.

## 3. The current readiness, computed from current inputs

The committed projections cannot answer "what is true now", so a **fresh projection**
was produced from the live repositories at pinned revisions — read-only, no writes to
either bus:

```text
go-control-tasks     main              c381c80136338f5d53898961a58fc0a123e6044f
go-control-evidence  permission-test   3ae4c96c492c21e57a1edf861f1adc54156b7a9c
go-repo (pointers)   cc/v1-finalization-20260914 @ 1c3615379df1b3f9e15647bc6089e5449b9200e8
verifier keys        identity/keys/cc-task-manifest-signing.pub + hk-evidence-signing.pub
projection           103 tasks / 78 evidence, task+evidence signatures VERIFIED,
                     identity binding BOUND, identities separated, hk_agent_liveness PROVEN,
                     live_verified_runtime = sha256:1c9598d6… (age ≈ 8.3 h, inside the window)
                     1 anomaly: TASK_PARAMETER_CONTRACT_DRIFT on go-boss02-canary-20260909T014228979291Z
                     (the known, deliberately annotated superseded parameter shape)
```

Two projections are enough to see what the staleness was doing:

| gate | from the committed 09-15 projection | from the current projection |
|---|---|---|
| APPROVED_CANDIDATE | PASS | PASS |
| SOURCE_BINDING | PASS | PASS |
| TEST_PR | **FAIL** (TASK_EXPIRED) | **PASS** — a signed TEST_PR for this commit exists |
| VERIFY | **FAIL** (164911 s old) | **PASS** — signature-verified, inside the window |
| the other nine | UNKNOWN | UNKNOWN |
| `deploy_ready` | NO | **UNKNOWN — no mandatory FAIL** |

```text
PACKAGE_BINDING / DEPLOYMENT_PLAN / HUMAN_APPROVAL / CURRENT_RUNTIME / CANARY /
RELEASE_GATES / BRIDGE_ACCEPTANCE   -> UNKNOWN: an approved plan bundle was not supplied
LIVE_SWITCH / LIVE_SWITCH_PROVENANCE -> UNKNOWN: a live channel bundle was not supplied
```

So the repository side is clean, and **the blocker is the plan / live path**, not the
evidence chain. Note the fresh projection was deliberately **not committed**: without
`--requests-dir`/`--request-facts-dir` it carries `requests: 0` where the committed
records carry 15, and a projection that loses the Request view would be a regression
rather than an update.

## 4. The single NEXT_ACTION

Nothing repository-side is on the critical path any more; every remaining input is
live, upstream or human:

```text
1  human authorisation to open the CANARY/DEPLOY request channel on the CC host
   (currently enabled_request_actions = VERIFY / TEST_PR / CONTROL_PLANE_HEALTH,
    deployment_requests_enabled=false)
2  a CANARY run for this exact candidate           (live execution, 1800 s window)
3  a preflight run                                 (live execution, 300 s window)
4  the four release gates declared PASS and exact-bound to this candidate
   (upstream: Boss GPT / Cells), carried in the plan
5  an authenticated GitHub Human Approval bound to the exact candidate + HK-STAGING-01
6  the plan registered on the CC host -> DEPLOY_READY=YES -> dry-run PASS -> real DEPLOY
```

Step 1 is the first thing that can happen, and it is a human decision this round must
not take. The round therefore **stops at that boundary**, as instructed.

## 5. What this round did not do

No live access of any kind (no SSH to HK or CC), no install, no store or switch
change, no Request / Task / Evidence, no TEST_PR / VERIFY / CANARY / DEPLOY / ROLLBACK,
no RDS or database action, no Production. The two bus repositories were **cloned
read-only** to compute the projection and nothing was pushed to either. No previously
proven work was redone: B4-B1.3's install, round 2's TEST_PR and B4-B1.5's
reconciliation all stand as they were.

## 6. The migration item, scheduled rather than started

#103 now requires a bounded capability that does not exist. Per its own instruction it
must be built along the minimal chain and must not become a new gate, signer, command,
approval layer or general-purpose DBA platform. The repository-side pieces, and where
each belongs:

```text
candidate side (offline, testable now)
  the declared migration identity + the check that the candidate's own Alembic lineage
  is a single verifiable chain whose head is the declared migration_head — a checked
  fact, not a claim, in the same way the builder Dockerfile digest is checked today
executor side (needs a live install, later round)
  verify live pre-state, run the controlled forward migration, verify the target head,
  and carry all of it in the same signed Evidence as the cutover
plan / task side (repository + Bridge install)
  the live head and the approved target head bound into the plan and the Task, with no
  caller-supplied revision or SQL
fail-closed set
  pre-state mismatch, ambiguous lineage, missing candidate-bound test proof, failed or
  mismatched post-state
```

Starting it now would be designing the contract surface ahead of the executor that must
produce the proof, so this round records the chain and leaves the decision of *when* to
the next authorised round. The image-only path keeps working unchanged meanwhile.
