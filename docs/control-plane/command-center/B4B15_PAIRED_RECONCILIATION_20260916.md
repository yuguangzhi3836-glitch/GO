> **HISTORY / BREAK-GLASS REFERENCE**
>
> This document is not the normal current operating path.
>
> Normal deployment and inspection are defined by [`/AGENTS.md`](../../../AGENTS.md) and use GO Forge.
>
> Do not issue `HK_STAGING_*` requests unless the Owner explicitly authorizes Old Command Center fallback mode.

---

# B4-B1.5 — the paired reconciliation: the canonical candidate now names the v3 artifact

Date: 2026-09-16
Scope: **repository-side only.** No SSH, no install, no store change, no Request /
Task / Evidence, no TEST_PR / VERIFY / CANARY / DEPLOY / ROLLBACK, no switch, no
production, no database. `deployment_requests_enabled` untouched.

The success of the previous round was an artifact in a store and a signed result in an
evidence repository. This round writes those facts back into the canonical candidate,
as one set, without rewriting the history that led to them.

## 1. The paired move

Only what the fresh signed result actually changed. Every old value was asserted
before it was replaced, so this could not reconcile a file that had already moved.

```text
artifact_digest                    sha256:fe0d2c36…  ->  sha256:6b92050e…
build_definition.executor_version  test-pr-v2        ->  test-pr-v3
test_result_identity.task_id       …-0673b27f427c    ->  …-0342850d8822
test_result_identity.evidence_id   24bad37a…         ->  1865b17d…   (the commit)
test_result_identity.artifact_digest  fe0d2c36…      ->  6b92050e…
artifact_package.durability        NOT_PROVEN        ->  PROVEN
artifact_package.package_sha256    null              ->  e70238c7…
```

Unchanged, and asserted unchanged: `candidate_id`, `source_repository`,
`source_commit`, `application_tree`, `source_fingerprint`, `migration_head`,
`migration_required`, `required_services`, `rollback_relation`, and the other five
`build_definition` fields (`profile`, `dockerfile`, `dockerfile_sha256`,
`builder_image_tag`, `builder_image_id`) — those are facts about the builder, and the
executor version does not redefine them.

No TEST_PR was issued. The source did not change; another build would only have
produced a third unrelated artifact.

## 2. History is preserved, not rewritten

The block that described the previous reconciliation was moved **verbatim** into
`release_candidate_reconciliation_history[0]`; `release_candidate_reconciliation` now
carries this round's event. Nothing in the old block was edited to match the present.

Verified mechanically (`PairedReconciliationTests`): the history entry is
byte-for-byte the old block, it still names the v2 task, the v2 evidence commit and
the superseded artifact, and it still carries its own `why_not_case_b` — which says
the executor version and gate results were identical *for that event*. It was true
then, so it stays.

Consumers were checked first: `release_candidate_reconciliation` is read by exactly
one thing (the admission suite's evidence-identity test, for `new_evidence_commit`),
and the document's other readers (`state_projection`, readiness) read the top-level
source fields and the `release_candidate_v1` block only. So the new key is additive
and breaks nothing.

## 3. The new reconciliation says what really changed

It matters that this one cannot reuse the previous wording. `verdict` is
`CASE_A2_SAME_SOURCE_AND_BUILDER_BASELINE_NEW_EXECUTOR_GENERATION_AND_DURABLE_ARTIFACT`,
and `what_changed` / `what_did_not_change` / `why_not_a_repeat_of_the_previous_case`
record:

```text
changed      executor_version v2 -> v3 (the sealed-artifact builder)
             artifact_digest (a new immutable image; a rebuild is not bit-reproducible)
             artifact_durability NOT_PROVEN -> PROVEN
             gate_results 3 gates -> 4 (B4-B1 added artifact_sealed)
unchanged    source commit, PR number, application tree, fingerprint, build profile,
             Dockerfile + digest, builder image, deployment_performed=false
```

The old wording ("executor_version identical", "gate_results identical") is not
copied forward, because it would now be false.

## 4. Verification

```text
component suite       99 tests OK   (86 before this round, +13)
real admission run    ACCEPT, every check PASS, durability PROVEN, deployable true,
                      is_a_deploy_approval false
builder binding        candidate v3 + evidence v3 -> PASS
                       candidate relabelled v2 + evidence v3 -> REJECT
                       candidate_test_result_evidence_builder_version
set mutations          wrong package SHA                      -> REJECT
                       superseded image + new package         -> REJECT
                       new image + replaced (v2) Evidence     -> REJECT
                       PROVEN with no package address         -> REJECT
                       PROVEN claim with no evidence supplied -> REJECT + unknown recorded
evidence identity      evidence_id == 1865b17d… (commit); the blob id 0500b1a0… is
                       carried as audit information only; the fixture's blob id and
                       file digest both recomputed and matched
history                the superseded block preserved verbatim; three generations of
                       builds still on record
CI E2E block           rehearsed locally 23/23, including the two new mutation cases
readiness suite        63 tests OK (untouched, re-run because CI runs it)
manifest               regenerated from index blobs; worktree and git archive 0 FAILED
```

## 5. What the reconciliation does and does not move

The previous round's plan expected `PACKAGE_BINDING` to go from BLOCKED/NOT_PROVEN to
PASS. It does not, and cannot, from a repository-side round. The gate reads:

```python
def gate_package_binding(inputs):
    body, candidate = inputs.plan_body(), inputs.candidate
    if body is None or candidate is None:
        return gate("PACKAGE_BINDING", "UNKNOWN", "the plan or the candidate is missing, …")
```

With no plan supplied it is **UNKNOWN** — so the real run reports UNKNOWN. The clause
the reconciliation *did* change is the one that used to fire once a plan existed:

```text
superseded candidate + a plan approving it   -> FAIL   artifact_package_not_proven
reconciled candidate + the same plan shape    -> PASS
```

(Measured by calling the gate function itself on candidate-shaped input; no plan was
created, no approval made, no rule changed, no output edited. This is not a readiness
verdict.)

The remaining blocker for that gate is therefore an **approved plan**, which belongs to
the Human Approval flow and is not a candidate-side gap.

## 6. A behaviour that changed, and why the assertion moved rather than the rule

With a candidate that declares `durability: PROVEN`, an evidence-less admission run now
returns **REJECT** with `candidate_artifact_package_mismatch`, where before this round
it returned UNKNOWN. The rule did not change; the candidate did. The evidence is what
makes a package claim checkable, so a candidate asserting a proven package that no
proof covers is refused by name — and the absent evidence is still recorded as the
unknown it is.

That means the component's own docstring ("the verdict is UNKNOWN rather than ACCEPT")
was only true for a candidate making no package claim, and the workflow's assertion
`an_absent_test_result_context_is_unknown_not_accepted` was only true of the
pre-reconciliation candidate. Both were corrected to describe the behaviour that
exists, rather than the rule being loosened to keep the old wording true. A new test
pins the pair: REJECT, with the absent-evidence unknown alongside it.

## 7. Live

Nothing was touched on any host. The store still holds the object the previous round
sealed; this round only believes the signed result about it.
