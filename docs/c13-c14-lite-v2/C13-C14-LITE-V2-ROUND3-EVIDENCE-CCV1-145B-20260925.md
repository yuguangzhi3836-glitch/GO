# C13/C14 Lite V2 — Round 3 Evidence (CCV1-145B, 2026-09-25)

> Raw bytes for everything stated here are stored next to this file in
> `evidence/CCV1-145B-R3-20260925/` with a `SHA256SUMS` covering every file.

## 0. Headline

```text
PR254_MERGE_SHA         64715d308954049eb6675d81196d7f4cd853199b   (#254 MERGED 2026-09-25T23:07:13+08:00)
CANDIDATE               64715d308954049eb6675d81196d7f4cd853199b   (= current main, frozen this round)
LEDGER TASK IDENTITY    Issue #68 comment 5834704650 · V70-R3-C14-03 / V70-R3-C13-03 / V70-R3-C13C14-03
C14 RUN                 36152394748 · success · 15/15 steps green
C14 VERDICT             BLOCKED   (model-authored; failure_class null, blocking_issues non-empty)
C14_ROOT                d2b839cbba494708c18b5937197781bd8da2beba73a080645b16c468aadd7b6c
C13 DISPATCHED          NO  (gate is PASS_SCOPED or a lawful NOT_APPLICABLE; this is BLOCKED)
DEPLOY                  NO
```

**The one thing this round existed for**: the input shape that killed run `36148838395` — a
model-authored `BLOCKED` with no provider `failure_class` — now **seals successfully**. D-4 is
fixed, and proven so by a real run rather than by a test.

## 1. Registration and freeze (read-only)

```text
merge 64715d30  parent1 3cd7be752330f377e3446942da4f881df13d183d  (old main)
                parent2 2958b494317d6c959c9e988f86bfe895feb4767f  (PR #254 head)
                subject "Merge pull request #254 from yuguangzhi3836-glitch/cc/c13-c14-workflow-defect-fixes-20260925"
                merged_at 2026-09-25T15:07:13Z   merged_by chenzhenxi1-sudo

frozen candidate 64715d30
  root tree        d6b4e801d792ef7448fd1808632abe41170cd86b
  application tree dd815baf0105cce603e9a28b002cfb9d8b95d186
  first-parent changed paths: .github/workflows/c13-quality-acceptance.yml
                              .github/workflows/c14-rule-compliance.yml

registered workflow blobs on 64715d30 (re-measured)
  c14  cc43492e19b96b6128e030be8d62af91f7871703   == PR #254 head
  c13  d9b75b8ca7fb9e3197f97cb8f12ce4f1c269d055   == PR #254 head
main workflow count 28   (26 before any C13/C14 registration)
backend path on main       ABSENT (control-plane/c13-c14-* never merged)
WORKFLOW_EXECUTION_REF     48c2386d2dfc4d2e1e8c914dc7c7376af6bd1eb4  GET /commits -> HTTP 200
offline structural check   gate=PASS on the exact registered bytes
```

The candidate's `application/` subtree is **again** byte-identical to the one this project has
carried since `37d9a420…` (`dd815baf…`). The change in `64715d30` relative to its first parent is
entirely **outside** `application/`.

## 2. Ledger identity (taken from the real ledger, not invented)

Written to **Issue #68** as an append-only third activation — comment **`5834704650`**,
4443 bytes, `sha256 963dfff6…`, read back byte-identical, comments 40 → 41, body untouched.

```text
round               V70-R3            (unchanged; the sequence field advances instead)
C14 task id         V70-R3-C14-03
C13 task id         V70-R3-C13-03
scheduler request   V70-R3-C13C14-03
candidate           64715d308954049eb6675d81196d7f4cd853199b
```

Basis: the ledger's own repeated-activation convention (C01 appears as `V70-R3-C01-01` and later
`V70-R3-C01-03`) and its armed-row rule *"Activate only on a new frozen candidate"*. The record
states explicitly that **neither** previous activation is reused — #1's verdict was over an empty
boundary, #2 produced no sealed record at all.

⚠ Boundary fact carried forward: #68 was 38/38 Owner-authored before this line of work. These three
activations are the earliest non-Owner comments. They are additive only and supersedable.

## 3. The C14 run

```text
run 36152394748  .github/workflows/c14-rule-compliance.yml  workflow_dispatch  ref=main
head_sha 64715d30…  (= candidate)  run_attempt 1
2026-09-25T15:10:29Z -> 15:11:37Z   conclusion = success

steps (all success)
   1 Set up job                                        success
   2 Check out the execution backend (pinned commit)    success
   3 Check out the frozen candidate into candidate/     success
   4 Run actions/setup-python@v5                        success
   5 Bind the exact frozen candidate identity           success
   6 Bind the workflow definition that is executing     success
   7 Freeze the rule-review scope digest                success
   8 Build the frozen candidate contract                success
   9 Run one fresh AI rule review (read-only reviewer)  success
  10 Seal the C14 bundle                                success     <-- the step that died in r2
  11 Preserve the raw review evidence whatever ...      success
  12 Publish the raw review evidence                    success
  13 Publish the sealed C14 bundle                      success
  14 Read back run and artifact identity via the API    success
  15 Publish the run/artifact readback record           success

step 9 output   {"verdict": "BLOCKED", "ai_provider": "OPENAI_RESPONSES_API"}
step 10 output  {"bundle": ".../artifacts/c14_bundle.json",
                 "C14_ROOT": "d2b839cbba494708c18b5937197781bd8da2beba73a080645b16c468aadd7b6c",
                 "verdict": "BLOCKED"}                       exit 0  -> SEALED
step 11 output  {"raw_evidence": ".../raw", "files": 8, "missing": [],
                 "seal_status": {"step": "seal", "status": "SEALED", "exit_code": 0}}
```

## 4. The verdict, accepted as given

```text
verdict               BLOCKED
failure_class         null
remediation_status    OPEN
authorizes_any_action false
review_execution_id   resp_026e82e2ff0f1c6d006ab68f12660487d0a21183ff31a07024
blocking_issues[0]    "Compliance cannot be determined from rule names and a scope hash alone; the
                       applicable rule texts or an authoritative review artifact resolving rule
                       requirements against this candidate are required."

findings
  C14-001 [BLOCKER]  "The frozen candidate declares GO_CONSTITUTION, PERMISSION_BOUNDARY, and
                      AI_BEHAVIOUR_RULES applicable, but supplies neither their normative contents
                      nor evidence sufficient to assess compliance. The rule versions are
                      identified only as \"unversioned\"."
```

This is **not** a machinery failure and it is not being argued away. The reviewer is saying that
C14 as currently fed cannot conclude compliance: it receives rule **names** and a scope hash, never
the rule **texts**, and every version is `unversioned`. Two consecutive candidates have now
returned `BLOCKED` for this same reason. Whether that is the correct verdict for this input, and
what C14 should be given instead, is a design decision — **not changed this round**.

## 5. The four required verifications

### D-1 · changed-path boundary — correct

Both values below are independent of each other: the left one from the runner's own environment
dump inside the job log, the right one recomputed here from the local git object store.

```text
LITE_SCOPE_SHA256 (job log) = 1356d60fa9451d85f0d57456d957795c6ca73b1589da38efe8d6be4f4a4f9443

declared rule_review_scope_sha256 = 1356d60fa9451d85f0d57456d957795c6ca73b1589da38efe8d6be4f4a4f9443
digest over the REAL first-parent paths = 1356d60f…   MATCH
digest over an EMPTY path list          = 843bed61…   no match
```

`scope.json` inside the raw artifact carries the same digest and the same two paths, so the frozen
boundary is readable from the published bytes as well as from the sealed record.

⇒ **D1_CORRECT = YES**

### D-2 · workflow identity binding — correct

```text
record workflow_sha              cc43492e19b96b6128e030be8d62af91f7871703
LITE_WORKFLOW_SHA (job log)      cc43492e19b96b6128e030be8d62af91f7871703
registered C14 blob on main      cc43492e19b96b6128e030be8d62af91f7871703
pinned backend's own copy        0ffea233d6fe5da4fdc171ade1906b0212eef140   (the old wrong answer)
record workflow_ref              yuguangzhi3836-glitch/GO/cc43492e19b96b6128e030be8d62af91f7871703

equals the EXECUTED definition   YES
equals the old wrong answer      NO
```

⇒ **D2_CORRECT = YES** — and it does move when the registered file moves, which is the property
the field is supposed to have.

### D-3 · the sealed record's rule set — observable and consistent

D-3 was last round's open item (`D3_RECORD_OBSERVED_IN_RUN = NOT_OBTAINED`, because the run died
at the seal and there was no bundle to read). It is observable now:

```text
bundle.applicable_rules          ["AI_BEHAVIOUR_RULES", "GO_CONSTITUTION", "PERMISSION_BOUNDARY"]
bundle.applicable_rule_versions  {"AI_BEHAVIOUR_RULES": "unversioned",
                                  "GO_CONSTITUTION": "unversioned",
                                  "PERMISSION_BOUNDARY": "unversioned"}
spec.applicable_rules            same three
facts.applicable_rules (raw)     same three
scope.json rules (raw)           same three
LITE_APPLICABLE_RULES (job log)  GO_CONSTITUTION,PERMISSION_BOUNDARY,AI_BEHAVIOUR_RULES
```

One derivation, four consumers, all the same three rules. The sealed record no longer declares a
smaller set than the one the review was built from.

⇒ **D3_OBSERVABLE_AND_CONSISTENT = YES**

### D-4 · a model-authored non-pass can be sealed — proven in a real run

```text
verdict BLOCKED   failure_class null   blocking_issues: 1 entry
provider-failure shape  NO   (failure_class is null)
model-authored shape    YES  (failure_class null AND reasons present)
seal step               SUCCESS, exit 0, seal_result.status = SEALED
```

Compare with run `36148838395` on the same input shape: seal refused
(`c14_non_pass_requires_failure_class`), job failed, **zero artifacts**, and the reviewer's reasons
were destroyed.

⇒ **D4_MODEL_BLOCKED_SEALED = YES**

### raw review evidence — present, with one honest caveat

```text
artifact 10871828874  c13c14-lite-c14-raw-64715d30…  4737 B  sha256:4bbc0619…
manifest: schema go.c13c14.lite.raw_review_evidence.v1
          files 8 / missing []
          contract facts outcome scope seal_result seal_stderr seal_stdout spec
          every file's sha256 recomputed here and matched
          sealed_bundle_published_by_this_step: false
          authorizes_any_action: false
```

Three artifacts exist and each was downloaded and re-hashed locally; all three digests equal the
digest GitHub computes for the same artifact:

```text
10871833984  c13c14-lite-c14-64715d30…        2973 B  sha256:9d127345…   sealed bundle
10871828874  c13c14-lite-c14-raw-64715d30…    4737 B  sha256:4bbc0619…   raw review evidence
10871399271  c13c14-lite-c14-readback-…        679 B  sha256:01da0490…   readback
```

⚠ **The caveat, stated because it matters**: this round the seal **succeeded**, so the raw evidence
was published on the **success** path. The specific requirement "raw evidence must exist *even
when the seal refuses*" was therefore **not re-exercised in a live run this round**. It remains
covered only by the offline regression suite added in PR #254. It is not claimed as
live-verified.

## 6. Integrity and identity (recomputed locally)

```text
C14_ROOT claimed    d2b839cbba494708c18b5937197781bd8da2beba73a080645b16c468aadd7b6c
C14_ROOT recomputed d2b839cbba494708c18b5937197781bd8da2beba73a080645b16c468aadd7b6c   MATCH

cell_id C14 | candidate_sha exact | application_tree exact | issue_number 68
github_run_id 36152394748 | task_id V70-R3-C14-03
ledger_reference {cell_id C14, round_id V70-R3, task_id V70-R3-C14-03}
contract.request_id V70-R3-C13C14-03 | principal_id chenzhenxi1-sudo

readback: bytes_verified true / bytes_mode strict / head_sha == expected_head_sha true
readback recomputed_digest == artifact digest: true
```

`FINAL_ROOT` verification is the public, recomputable check (integrity). It is **not** a signature:
nothing here proves authenticity, and this record does not claim a witness signature for this run.

## 7. Writes performed this round

```text
1  Issue comment on #68     5834704650   (third activation: C14/C13 task identity -03)
2  workflow dispatch        run 36152394748  (.github/workflows/c14-rule-compliance.yml, ref=main)
3  repo docs                C13-C14-LITE-V2-ROLLBACK-RUNBOOK-20260925.md   (facts closeout)
                            C13-C14-LITE-V2-ROUND3-EVIDENCE-CCV1-145B-20260925.md  (this file)
                            evidence/CCV1-145B-R3-20260925/                (raw bytes + SHA256SUMS)
4  local commit only        on cc/c13-c14-lite-v2-defect-fixes-20260925   (NOT pushed)
```

Explicitly **not** done: no C13 dispatch, no deployment, no rollback executed, no HK live access,
no CC access, no credential or key touched, no change to `main`, no comment on any Owner PR, no
edit to the #68 body or to any historical comment, no deletion of any historical issue, workflow
run or artifact.

## 8. Open decisions (human)

```text
A  C14 has now returned BLOCKED twice on the same substantive ground: it is given rule NAMES and
   a scope hash, never the rule TEXTS, and every version is "unversioned". Decide whether to feed
   C14 the normative rule content (or an authoritative review artifact), or to accept BLOCKED as
   the correct and final answer for a candidate whose change surface never touches application/.
B  The "raw evidence survives a refused seal" path is only offline-tested. Decide whether it needs
   a dedicated live exercise before C13 is ever allowed to run.
C  C13 remains stopped and has still never been dispatched.
D  This round's docs commit is local only. Push needs authorisation.
```
