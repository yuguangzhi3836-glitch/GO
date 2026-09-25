# C13/C14 Lite V2 — round 2: the first verdict from the fixed machinery

- Merge #2: `REGISTRATION_MERGE_SHA_2 = 3cd7be752330f377e3446942da4f881df13d183d` (PR #253)
- Frozen candidate: `3cd7be752330f377e3446942da4f881df13d183d`
- Ledger: Issue #68, second activation, comment `5834220848`
- Task identity: **C14 `V70-R3-C14-02`** · C13 `V70-R3-C13-02` · request `V70-R3-C13C14-02`
- C14 run: **`36148838395` — `failure` at the seal step**, verdict `BLOCKED`
- `C13_DISPATCHED = NO` (gate not satisfied) · `DEPLOY = NO`

---

## 1. Registration #2 confirmed, and the registered bytes are the FIXED ones

```text
merge commit   3cd7be752330f377e3446942da4f881df13d183d   (2026-09-25T22:34:18+08:00)
parents        7db7b2aa52ecabc1ff1c92d9d1673f44f5ce68c5  +  55e437edcf673856bd875b37dab28be86cd22386
subject        Merge pull request #253 from .../cc/c13-c14-workflow-defect-fixes-20260925
```

Blob identity of the two production workflows — the files on the new `main` are exactly the
ones PR #253 carried, and demonstrably **not** the ones PR #252 registered:

```text
                       new main (3cd7be75)   PR #253 head (55e437edc)   PR #252 head (7db7b2aa5, defective)
c14-rule-compliance    0ffea233d6fe…          0ffea233d6fe…  SAME         a9400e2fde4b…  different
c13-quality-acceptance 899a17cf012d…          899a17cf012d…  SAME         5d5ccdafe73d…  different
```

Pinned execution ref: `37b31e0a5a8910400e138292d01badc67270b167` — remote reachability
re-measured `GET /commits/…` = **HTTP 200**, and the branch was **not** deleted.

## 2. Frozen candidate

```text
candidate_sha    3cd7be752330f377e3446942da4f881df13d183d
root_tree        b71ad60a25e3de6888125183163085b8f54252d9
application_tree dd815baf0105cce603e9a28b002cfb9d8b95d186
first-parent changed paths (measured)  .github/workflows/c13-quality-acceptance.yml
                                      .github/workflows/c14-rule-compliance.yml
```

The `application/` subtree is again byte-identical to the tree this ledger already carries for
`37d9a420…` / `8ffcde66…` / `7db7b2aa5…`. This round is therefore not about the application
layer — it is the first verdict produced by the **fixed** verification machinery.

## 3. Ledger activation #2 (append-only)

```text
issue            #68      comment 5834220848      created 2026-09-25T14:38:15Z
bytes / sha256   3506 / (recorded in the evidence directory)
readback         BYTE-IDENTICAL = True   comments 39 -> 40   body unchanged
ids minted       round V70-R3 (unchanged) · V70-R3-C14-02 · V70-R3-C13-02 · V70-R3-C13C14-02
```

The round id stays `V70-R3` and the sequence field advances to `-02`, following the ledger's own
precedent for repeat activations of one cell (C01 appears as `V70-R3-C01-01` and later
`V70-R3-C01-03`). Activation #1 (`5833230504`, tasks `…-01`) is **not** deleted and **not**
reused: its C14 verdict was produced over an **empty** changed-path boundary, so it cannot
stand as a verdict for this candidate. That is stated in the activation record itself.

## 4. ✅ D-1 / D-2 / D-3 verified against the real run

This is the point of the round, so the evidence is a direct measurement from the run's own
environment dump rather than a claim about the code.

### D-1 — the changed-path boundary is no longer empty

```text
old run 36141430817   LITE_SCOPE_SHA256 = 843bed6169d0…   ← equals the digest over an EMPTY list
new run 36148838395   LITE_SCOPE_SHA256 = 1356d60fa945…   ← equals the digest over the 2 REAL paths
```

Both digests were recomputed locally from the same rule set, so the comparison is exact:

```text
digest over changed_paths = the 2 real files   1356d60fa9451d85f0d57456d957795c6ca73b1589da38efe8d6be4f4a4f9443
digest over changed_paths = []                 843bed6169d0c834c0d08daf3952ea122af545c4f46b68461da252dfd80aadd8
```

⇒ `D1_FIXED_IN_REAL_RUN = YES`. The workflow step that freezes the boundary
(`--diff-merges=first-parent` + `test -s` + `fetch-depth: 2`) also completed **success** as
step 5 of the job.

### D-2 — the record binds the definition that actually executed

```text
old run   workflow_sha = 8889221c5907e13a59aea3021cbc22e0d225d401  ← the pinned backend's copy
new run   LITE_WORKFLOW_SHA = 0ffea233d6fe5da4fdc171ade1906b0212eef140  ← the registered definition
registered blob on new main  = 0ffea233d6fe5da4fdc171ade1906b0212eef140   ⇒ equal
```

⇒ `D2_FIXED_IN_REAL_RUN = YES`. The new step ("Bind the workflow definition that is actually
executing") completed success as step 6.

### D-3 — the declared rule set

```text
LITE_APPLICABLE_RULES = GO_CONSTITUTION,PERMISSION_BOUNDARY,AI_BEHAVIOUR_RULES
LITE_RULE_VERSION     = unversioned
```

Both inputs now reach the backend (they did not exist in the old workflow at all), and the
frozen scope digest was computed over all three rule sets.

⚠ **The sealed record could not be observed this run**, because the run failed at the seal, so
there is no bundle to inspect. D-3's record-level proof rests on:
`control-plane/c13-c14-lite/test_lite_defect_fixes.py` (4 tests, 3 failures + 1 error against the
pre-fix backend) and the same CLI path exercised locally. Stated as
`D3_RECORD_OBSERVED_IN_RUN = NOT_OBTAINED`, not as verified.

```text
D1_FIXED_IN_REAL_RUN = YES
D2_FIXED_IN_REAL_RUN = YES
D3_INPUTS_FIXED_IN_REAL_RUN = YES      D3_RECORD_OBSERVED_IN_RUN = NOT_OBTAINED
```

## 5. 🔴 New defect D-4 — a model-authored `BLOCKED` verdict cannot be sealed

### What happened

```text
run 36148838395   job 108116676694   steps 1–9 SUCCESS, step 10 "Seal the C14 bundle" FAILURE
step 9 output     {"verdict": "BLOCKED", "ai_provider": "OPENAI_RESPONSES_API"}
step 10 output    {"refused": "c14_non_pass_requires_failure_class", "detail": ""}
                  ##[error]Process completed with exit code 2
artifacts         NONE published (steps 11–12 skipped)
```

The `ai_provider` key in step 9's output proves this came through the **success** path of the
reviewer, not the provider-failure path (which prints `failure_class` instead). So the model
returned `BLOCKED` as its own opinion.

### Root cause

`lite_bundle.validate` (line ~266):

```python
if record["verdict"] in ("FAIL", "BLOCKED") and record["failure_class"] is None:
    raise Reject("c14_non_pass_requires_failure_class")
```

`failure_class` can only be produced by `lite_ai_reviewer.blocked_outcome(...)`, which is only
reached on the **provider-failure** path. The C14 opinion schema, however, lets the model return
`verdict: BLOCKED`, and neither the schema nor the reviewer supplies a `failure_class` for that
case. ⇒ **The schema and the seal disagree about who may declare BLOCKED.**

### Why this matters more than it looks

The consequence is not the failed run — it is that **the record is destroyed**. The reviewer's
findings, its summary and its reasoning live only in `$RUNNER_TEMP/c14.outcome.json`, which is
never published when the seal refuses. So the audit trail of a legitimate verdict is thrown
away, and the round cannot say *why* C14 returned `BLOCKED`.

This is exactly the class of failure this line of work is against: a machine refusing in a way
that also erases the evidence for the refusal.

### Fix directions (not applied — needs a decision)

1. **Never lose the record** (cheap, independent of the rest): publish the opinion/contract
   artifacts from an `if: always()` step with `if-no-files-found: warn`, so a refused seal still
   leaves the reviewer's reasoning on disk.
2. **Settle who may declare BLOCKED**: either add a declared `failure_class` enum to the C14
   opinion schema (so the model must say which class it means), or have the seal record a
   distinct class such as `AI_DECLARED_BLOCKED` for a model-authored non-pass, keeping the
   provider classes separate.
3. Then decide whether a model-authored `BLOCKED` on a candidate whose change surface is
   entirely outside `application/` is the correct verdict at all — it may well be, and if so the
   round's design should say so rather than failing the run.

## 6. C13 — not dispatched

`C13_ALLOWED = NO`. The gate is `PASS_SCOPED` or a lawful `NOT_APPLICABLE`; the verdict is
`BLOCKED`, with no failure class recorded. The previous round's `PASS_SCOPED` is **not** reused
and **not** carried forward.

## 7. Evidence

`docs/c13-c14-lite-v2/evidence/CCV1-145B-R2-20260925/` (`SHA256SUMS` covers every file):

```text
github-run-36148838395.json      github-jobs-36148838395.json
github-artifacts-36148838395.json   (empty — nothing was published)
job-log-108116676694.txt          ← carries the two decisive env dumps (LITE_SCOPE_SHA256, LITE_WORKFLOW_SHA)
ledger-activation2-issue68-comment5834220848.md
```

Attribution note: the two decisive values are read from the job log's step environment, which
GitHub writes from the runner's own environment. They are not self-reported by the backend.
