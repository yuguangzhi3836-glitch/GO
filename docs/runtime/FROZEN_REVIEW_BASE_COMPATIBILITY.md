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
