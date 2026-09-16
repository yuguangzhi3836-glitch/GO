# B4-B1.4 — build provenance bound to the signed result, and the evidence identity named

Date: 2026-09-16
Scope: **repository-side only.** No Hong Kong contact, no install, no TEST_PR, no
Request, no Task, no Evidence, no CANARY / VERIFY / DEPLOY / ROLLBACK, no change to
the deployment switch or to `CURRENT_CANDIDATE.json`'s recorded identities.

Two corrections to the previous round's handoff, and one blind spot in
`command-center-candidate-admission-v1` that the corrections exposed.

## 1. The blind spot, reproduced before it was fixed

`check_build` required a candidate's `build_definition.executor_version` to be *one
of* the recognised builders (`BUILDER_EXECUTOR_VERSIONS = ("test-pr-v3", "test-pr-v2")`).
`check_evidence` bound the signed TEST_PR result to the candidate's source commit and
artifact, and to the task that produced it — but **never read the result's own
`executor_version`**. Nothing therefore tied the declared builder to the builder that
actually ran, and the field was a claim no artifact could contradict.

Reproduced with the real artifacts in this checkout, before the change:

```text
evidence.executor_version                     = test-pr-v2
candidate.build_definition.executor_version   = test-pr-v2
[baseline]      v2 candidate + v2 evidence            -> ACCEPT  rejected=[]
[blind spot]    candidate CLAIMS v3, evidence IS v2   -> ACCEPT  rejected=[]
                checks: {rule: build, state: PASS,
                         observed: {executor_version: test-pr-v3, ...}}
```

That is exactly the statement the component's own source calls out as forbidden —
"Re-labelling an old candidate as v3 would be a false statement about how it was
produced" — reachable while every existing rule passed. The artifact id names an
image; it does not name the executor that produced it, so no amount of artifact
checking could have closed this.

### The fix

`check_evidence` now refuses a candidate whose declared builder the signed result
does not report:

```text
rule:    test_evidence
reason:  candidate_test_result_evidence_builder_version
compare: evidence.executor_version  ==  build_definition.executor_version
```

Both directions are refused (an older claim over a newer build, and a newer claim
over an older one), and a signed result that names no builder corroborates none —
silence is not corroboration. The token is declared in the contract's closed
refusal vocabulary, so the component still cannot emit a reason nobody can look up.
A v2-built candidate stays admissible, exactly as before: it simply has to be paired
with a v2 result, which is the point.

## 2. Correction: `evidence_id` is a record identity

The previous handoff's reconciliation plan proposed recording the **git blob id** of
the Evidence as `test_result_identity.evidence_id`. That plan is cancelled. The
field has always meant the Evidence's own identity on the evidence repository — its
commit, or a record id — and the canonical pointer has carried exactly that.

* No document in this repository ever said a blob id: the claim existed only in the
  handoff report and in the chat, so nothing in the tree needed correcting. Recorded
  here so the cancellation has a durable home.
* The schema is **not** changed. Its `evidence_id` description has always read
  "The evidence's own identity on the evidence repository (its commit or record
  id)", and the pattern is the shared identity pattern, so a record id remains
  expressible. The semantics are now pinned by tests instead of by prose:
  * contract level — the description still says commit or record id, and the pattern
    still accepts both a record id (`go-boss-test-pr-52-0673b27f427c`) and a commit;
  * data level — the canonical `evidence_id` equals the commit recorded in
    `release_candidate_reconciliation.new_evidence_commit`, is commit-shaped, and is
    **not** the blob id computed over the evidence bytes (the value that plan would
    have written);
  * refusal level — a path (`evidence/the-record.json`), a fragment, or an absent
    value is refused by name rather than recorded.
* The next reconciliation therefore records `1865b17d25e6baa6dd2bebc2bdee89cb9a621ad3`.
  The blob id `0500b1a098cc9b5e113922facb16b409372ef75a` may be recorded as audit
  information beside it, but it does not become `evidence_id`.

## 3. Correction: `build_definition.executor_version` moves with the artifact

The previous handoff said `build_definition` needs no change because the validator
accepts both `test-pr-v2` and `test-pr-v3`. Withdrawn. `build_definition` is the
description of **how the artifact was built**, and the new artifact
`sha256:6b92050e…` was built, tested and sealed by `test-pr-v3`. When the paused
reconciliation is resumed, `build_definition.executor_version` moves
`test-pr-v2 → test-pr-v3`, and nothing else in `build_definition` moves: `profile`,
`dockerfile`, `dockerfile_sha256`, `builder_image_tag` and `builder_image_id` are
unchanged facts about the builder and are not re-derived from the executor version.

The change in §1 makes that requirement enforceable rather than a note: pairing the
new v3 artifact with a candidate still claiming v2 now fails closed at admission,
instead of being accepted as a valid historical claim.

## 4. Verification

```text
component suite        86 tests OK  (79 before this round: +7)
built-in selftest      PASS
run_checks.py          status PASS, tests 86, refusal_reasons_declared 52
CI E2E block           rehearsed locally, 22/22 PASS, including the new case
                       a_builder_the_signed_result_does_not_corroborate_is_refused
manifest               component SHA256SUMS regenerated from index blobs;
                       worktree AND git archive both 0 FAILED
```

The new CI case is written against whichever builder the real evidence reports, so
it keeps meaning the same thing after the reconciliation moves the candidate to v3:
the claim and the proof have to move together.

## 5. What this round did not touch

* `docs/canonical-baseline/CURRENT_CANDIDATE.json` — its recorded identifiers are
  unchanged, as instructed. `artifact_digest` is still the older `sha256:fe0d2c36…`
  and `artifact_package.durability` is still `NOT_PROVEN`. The reconciliation that
  moves them is a separate, authorised round.
* No live host, no install, no Request / Task / Evidence, no CANARY / VERIFY /
  DEPLOY / ROLLBACK, no deployment switch, no PR merge.

## 6. Two defects found while working in this file

1. **A duplicated block from `51294bf` (B4-B1).** `check_artifact_durability` was
   defined twice, byte-identical, and the durability/deployability construction in
   `admit()` was written twice. Both copies were proven identical
   (sha256 of the two function bodies equal: `61b77e856285…`) before the first of
   each pair was removed, so the removal cannot change behaviour — the later
   definition and the later assignments are the ones that were already winning.
   It is fixed here rather than reported and left, because a second `def` silently
   overrides the first: an edit to whichever copy a reader opens may never run, and
   the file this round edits is precisely that file. Removed in its own commit so it
   can be reverted on its own. 906 → 846 lines.
2. **`TEST_PR_EVIDENCE_FIELDS` is declared and never used.** It lists the fields a
   signed TEST_PR result must carry for this component to bind a candidate to it,
   but no code path reads the constant — the individual fields are checked one by
   one instead. `executor_version` was added to it so the declaration matches what
   the binding now requires. Whether the constant should be enforced, or removed as
   a duplicate of the checks themselves, is left open here: enforcing it would add a
   refusal reason and change behaviour, which is outside this round's scope.
