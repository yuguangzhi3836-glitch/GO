# Explicit frozen review base compatibility

Change classes: CONTROL_PLANE, TEST_ONLY, DOCUMENTATION.

Owner authorized the minimal compatibility repair for #558/#559. This is not
another Persistent Runtime architecture phase, deployment authority or an
authorization to increase the model budget, attempts or circuit breaker.

## Why

#559 freezes #558 at `22df468b7ed22a66707d3108e3d9568597619f04`, whose actual
base is `chenzhenxi/hk-unified-pr365-registration-20261003` at
`2254cf3f141124900e19f3205b6928e1c172074a`. The old main-only admission rule
cannot admit it. Its eleven explicit test paths also exceed the old 400-character
wire limit. Rewriting the PR base, deleting tests, repeating paid development or
creating a second business review issue would not resolve these defects.

## Contract

A Formal C14 REVIEW Issue may explicitly add BOTH fields:

```
Candidate base ref: chenzhenxi/hk-unified-pr365-registration-20261003
Candidate base SHA: 2254cf3f141124900e19f3205b6928e1c172074a
```

Admission verifies live PR number, base ref/SHA, head SHA and GitHub comparison
merge base. The frozen base must be an ancestor, and an explicit regular-file
machine inventory is mandatory whenever the two base lines are written.
Builder admission is unchanged.

The optional `frozen_base` object is part of the canonical Runtime payload and
execution-request digest. It is copied unchanged into the C13 payload and the
existing dispatch JSON envelope; neither workflow gains an input beyond the
platform's ten-input limit. It is review data, unlike delivery metadata in that
same envelope. In the trusted backend checkout, both reviewers recheck live PR
brief base/head/number and local Git ancestry before AI; the machine job checks
before candidate tests as well. Complete base-to-head differences remain mandatory.
Base ref/SHA/PR already enter the existing Lite facts/input digest through
`review_brief`; no second ledger, scheduler or signature system is introduced.

Issue/SHA round and idempotency keys deliberately remain unchanged. A base/scope
edit changes the payload digest, never grants a fresh attempt. Existing tasks
must be inspected before any ingress update; never delete/recreate/reset an
in-flight or terminal task. `max_attempts=1`, existing sealed C14 admission to C13,
and all model/circuit-breaker limits remain unchanged.

Only the textual explicit-inventory cap changes to 2048 characters. The maximum
twenty files, restricted path/node grammar, exact candidate-tree regular-file
checks, order and duplicate refusal remain. Changed-test auto-selection retains
its existing 400-character bound. No #559 test is dropped.

## Verification and adoption

- Local Runtime suite: 673 tests PASS, including fifteen new cases.
- Local Lite suite: 297 tests, OK with its existing one skip.
- Four new integration cases use real multi-commit Git histories, including an
  unrelated-root negative control. One checks workflow gate placement.
- The candidate C13 wrapper runs all ten dependency-free ingress/transport cases.
  The five Git/PyYAML integration cases run in the existing Runtime CI, because
  the currently installed C13 machine image lacks those tools. No tests silently
  skip, no image/bootstrap installation is implied by local verification.
- Read-only plan against #558's actual Git objects and current GitHub PR/base:
  eleven files resolved; application tree `f5ac1022d87c3dc9daa97532b1445e6f0b02bc16`;
  round `FORMAL-REVIEW-I559-22df468b7ed2`; payload SHA256
  `4f5777c135b1a553e7f008722491394791809186af39670da0d08fca176fc022`.
  This is a local plan, not an enqueue/claim/run or business C13 verdict.

Review this compatibility candidate on main through its own C14→C13 round first.
Merge/install require separate approval and installed-source readback. The workflow
backend and installed consumer/review worker must all carry compatible bytes before
enabling the explicit #559 fields. Keep #559 as the unique business review entry.
After confirming no existing task/run, update #559 in place with the two exact
base fields and the Owner authorization; retain the eleven-test inventory.
Require actual enqueue/claim/run and sealed independent C14→C13 receipts.

#562's approval/installation does not install this patch. No business deployment,
payment, registration instruction, threshold increase or old verdict transfer is
part of this change. #558 image/package acceptance remains its own review scope.

---

## Auto-frozen candidate base (2026-10-08) — supersedes the opt-in requirement

Change classes: CONTROL_PLANE, TEST_ONLY, DOCUMENTATION.

The 2026-10-07 repair above made a non-`main` candidate reviewable only if the Owner
hand-wrote the two base lines. That made the Owner the source of a fact GitHub already
knows, and it refused ordinary stacked/release-branch candidates for not carrying the
right paperwork - `REVIEW_CANDIDATE_BASE_IS_NOT_MAIN`.

The formal Review path now FREEZES THE CANDIDATE'S REAL BASE, whichever branch the pull
request is actually aimed at:

```
Candidate PR + frozen HEAD
  -> read the live PR
  -> take base_ref / base_sha / head_sha from GitHub
  -> verify the head is still the frozen commit
  -> freeze the base (that IS the frozen identity)
  -> verify that base is an ancestor of the frozen commit (GitHub compare)
  -> the full base -> head diff is the review range
  -> the frozen identity enters the C14 payload digest, the wire envelope, and C13
```

`Candidate base ref:` / `Candidate base SHA:` are still accepted, and their meaning is now
an ASSERTION, not a permission: when written they must equal what GitHub reports, and a
mismatch is refused (`REVIEW_CANDIDATE_BASE_MOVED`) rather than resolved. Writing them also
keeps the explicit machine-inventory requirement. Leaving them out refuses nothing.

What deliberately did NOT change:

- Builder admission still requires a `main`-based Draft PR; `CandidatePrBaseIsNotMain` is
  now only the Builder path's refusal, and the Builder never calls the review resolver.
- `max_attempts=1`, the model/circuit-breaker limits, the Issue/SHA round identity and the
  idempotency keys.
- The machine-inventory rules: 20 files, 2048 characters for the explicit inventory, the
  400-character changed-test bound, the restricted path/node grammar and the
  regular-file/tree checks.
- No service, queue, database, scheduler, reviewer, verifier, authority layer, attempt or
  AI budget is added. The extra read is one existing GET (`/compare/{base}...{head}`).

The executor-side gate (`c1_review_base.py`) accepts a payload that carries no binding at
all by freezing the brief's own live PR facts, so a round admitted before the binding
existed is still checked instead of being exempted.

Verification of this revision is recorded in the PR that carries it (branch, HEAD, exact
changed paths, test commands and results). Installation to a Runtime host is a separate,
separately authorised step with its own installed-source readback.

---

## An explicit, human-raised review revision (2026-10-08) — a corrected brief can be reviewed

Change classes: CONTROL_PLANE, TEST_ONLY, DOCUMENTATION.

### The failure this answers

The C14 round for #559 ran, executed correctly and sealed `FAIL`. Its single MAJOR
(`C14-IAM-001`) was about the pull request's DESCRIPTION - it claimed no permission change
while the diff adds a supplier-onboarding `admin:connector` boundary. The Owner corrected
the description in place. The candidate SHA did not move, the issue did not change, and the
round identity is a function of exactly those two things - so the corrected brief could not
be reviewed at all. That is a real failure with no answer in the previous design.

### The rule

`review_round_identity(issue_number, candidate_sha, revision=1)`. One derivation, one extra
suffix:

| revision | `ledger_round_id` |
|---|---|
| 1 (default, and the historical round) | `FORMAL-REVIEW-I559-22df468b7ed2` |
| 2 | `FORMAL-REVIEW-I559-22df468b7ed2-R2` |

Every other name is derived from the round id, so they all move together: `-C14` / `-C13`
task ids, `review_request_id(candidate_sha, ledger_round_id)` and the Runtime
`task_idempotency_key`. There is no second identity algorithm: the revision is a suffix on
the string the contract already produces, not a parallel derivation.

Revision 1 is byte-identical to what this channel has produced since the identity existed,
which is what keeps every recorded Evidence row, sealed receipt and idempotency key valid.

### How it is raised, and by whom

An Owner may write one optional line in a Formal Review issue:

```
Review revision: 2
```

- Absent means revision 1. `Review revision: 1` is identical to leaving it out.
- The value is a plain decimal, `1..99`. Zero, negatives, non-integers, `2.5`, `1e2`,
  leading zeros and blank values are refused (`REVIEW_REVISION_INVALID`), as is the upper
  bound (`> 99`).
- Written twice with two different values it is refused (`REVIEW_REVISION_AMBIGUOUS`)
  rather than resolved by preference, exactly as the `Candidate PR:` / `Candidate SHA:`
  lines already are. The same value twice is one revision stated twice.
- **Nothing else may raise it.** No verdict, retry counter, timer or automation. Only an
  Owner editing the issue can, which is what makes a new round a human statement that the
  inputs changed rather than a machine's guess that they might have. The Builder path does
  not pass a revision at all and is therefore always revision 1: a Builder cannot commission
  a re-review of its own `FAIL`.

### What deliberately does NOT change

- `max_attempts = 1`. A revision-n round is still exactly one attempt. The revision creates
  a NEW round; it never retries an old one, never resets an old task, and never re-runs an
  old GitHub Actions run.
- C14 admission to C13: still only `PASS_SCOPED` / `NOT_APPLICABLE`. `FAIL` and `BLOCKED`
  still create no C13 and no round decision.
- The frozen-base behaviour above. Raising a revision does not re-read the pull request any
  differently, does not re-freeze the base, and does not change the machine inventory.
- Builder admission, the machine-inventory rules, and every existing Evidence row.
- No new payload field, schema version, DB column, queue, service, scheduler, reviewer,
  verifier or authority layer. `ledger_round_id` is already in the payload and already
  travels to the C13 half, so the suffix needs no new wire field.

### Scope note

Raising a revision is the Owner saying the round's INPUTS changed. It is not a way to
re-litigate a verdict on unchanged inputs - if nothing about the brief changed, the correct
answer is the original sealed verdict.
