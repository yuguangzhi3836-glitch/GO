# C13/C14 Lite V2 — round evidence: registration merge, ledger identity, first real C14

- Round: `V70-R3` · ledger `Issue #68` · activation comment `5833230504`
- Task pair: **C14** `V70-R3-C14-01` · **C13** `V70-R3-C13-01` (C13 not dispatched this round)
- Scheduler request: `V70-R3-C13C14-01`
- Candidate: `7db7b2aa52ecabc1ff1c92d9d1673f44f5ce68c5` (`main`)
- Application tree: `dd815baf0105cce603e9a28b002cfb9d8b95d186`
- Date: 2026-09-25 · all writes listed in §6; everything else read-only

---

## 1. Registration merge — confirmed read-only

`WORKFLOW_REGISTRATION_MERGED = YES`

```text
PR #252            merged=true · draft=false · merged_at 2026-09-25T13:22:27Z
merged_by          chenzhenxi1-sudo
merge commit       REGISTRATION_MERGE_SHA = 7db7b2aa52ecabc1ff1c92d9d1673f44f5ce68c5
merge commit tree  85ab281cfc10375081fe36c96482cf108c56280b
parent 1           aa2ec62b68b49679c6d54217c7cb75f63a9c3ef0   (old main)
parent 2           85533dd5790b8cfbbf48e3ae387cb47aab82a8d3   (#252 head)
commit signed      GitHub gpgsig present
change             2 files · +528 / -0 · 1 commit
origin/main        aa2ec62b…  →  7db7b2aa5…   (fast-forward observed on fetch)
```

> ⚠ Recorded as a fact, not a judgement: the merge was performed **under the
> implementation account** `chenzhenxi1-sudo`. The human merge gate was exercised, but the
> merging identity is the same account that implements and dispatches. Whether merge
> authority should sit on a different identity than `chenzhenxi1-sudo` is not decided by
> this round.

### 1.1 The two production workflows are registered on the default branch

`BOTH_PRODUCTION_WORKFLOWS_REGISTERED = YES`

```text
workflow id 366980580  C14 rule and compliance review (Lite V2)
                       .github/workflows/c14-rule-compliance.yml   state=active
workflow id 366980579  C13 quality acceptance (Lite V2)
                       .github/workflows/c13-quality-acceptance.yml state=active
```

Byte identity of what was registered — the file on `main` **is** the file that was reviewed
in #252, not a re-derived copy:

```text
c14-rule-compliance.yml   main blob a9400e2fde4be173ce6d910f88d8ceb6dbdc42f4
                          #252 head blob a9400e2fde4be173ce6d910f88d8ceb6dbdc42f4   SAME
c13-quality-acceptance.yml main blob 5d5ccdafe73d19ddec5ec2a34ca4803f21cd8dee
                          #252 head blob 5d5ccdafe73d19ddec5ec2a34ca4803f21cd8dee   SAME
```

Repository state after registration:

```text
.github/workflows/ 文件数     26 → 28   （实测 28）
其中 c13/c14                   2
control-plane/c13-c14-lite     仍不存在于 main（backend 未合并）
control-plane/c13-c14-witness  仍不存在于 main
```

### 1.2 The pinned execution backend is still reachable (the registration's only runtime dependency)

```text
WORKFLOW_EXECUTION_REF = a67ea8ac0cbf7990ce7fa1570eef7a0de29bab40
  GET /repos/.../commits/<ref>                  HTTP 200
  is ancestor of #251 head 3085ba157…           YES  (so the ref survives on an open branch)
```

This matters for rollback: if #251 is ever closed **and** its branch deleted, the pinned
`ref:` inside both registered workflows stops resolving and the next dispatch fails at the
first checkout. The registration therefore has a soft dependency on the #251 branch staying
alive — recorded here because it is not visible from `main` alone.

### 1.3 The registered pair passes the backend's own offline structural checks

`REGISTERED_PAIR_STRUCTURAL_CHECK = PASS`

Run against the bytes taken from `main` (`git archive 7db7b2aa5`), using the backend from the
pinned execution ref, with PyYAML available:

```text
checked : c14-rule-compliance.yml, c13-quality-acceptance.yml
failures: (none)
gate    : PASS
not registered by design: c13-c14-lite-poc.yml   (POC_ONLY; #252 added exactly two files)
```

---

## 2. Merge SHA recorded into the rollback / evidence records

`REGISTRATION_MERGE_SHA_RECORDED = YES`

- `docs/c13-c14-lite-v2/C13-C14-LITE-V2-ROLLBACK-RUNBOOK-20260925.md`
  - header: adds `REGISTRATION_MERGE_SHA`, both parents, root tree, `merged_by`
  - §1.1: main before **and** after, workflow count 26 → 28, both workflow ids and the
    byte-identity of the registered blobs
  - §1.2: the first real C14 run, its roots, and its two artifact digests + retention warning
  - §1.3: the pinned execution ref's reachability and its dependency on the #251 branch
  - §1.4: the ledger activation record, its comment id, and how rollback should treat it
  - §3 / §5: rollback checklist and measured post-merge rollback facts

---

## 3. Round / task identity — taken from the real 14-Cell ledger

`TASK_IDENTITY_SOURCE = REAL_LEDGER` · `TASK_ID_FABRICATED = NO`

The identity was **written into the ledger before the dispatch**, so the dispatch input is a
value that already existed in the ledger rather than a string invented at dispatch time.

```text
ledger                    Issue #68  (V7.0 14-CELL EXECUTION LEDGER, open)
ledger round id           V70-R3
C14 task id               V70-R3-C14-01
C13 task id               V70-R3-C13-01
scheduler request id      V70-R3-C13C14-01
activation comment        5833230504  (append-only, 2026-09-25T13:30:16Z)
comment author            chenzhenxi1-sudo
comment bytes             2594 · sha256 a2b859eef1d91e0987470419242cf057390a95a0cdd47afe45b653eb45904948
readback                  BYTE-IDENTICAL = True
issue body / history      unchanged · comments 38 → 39
```

### 3.1 How the ids were derived (not invented)

- The round id is the round the ledger **already** records, `V70-R3` — no new round was opened.
- The two task ids extend the grammar the same round already uses for C01–C12
  (`V70-R3-C01-01` … `V70-R3-C12-01`) ⇒ `V70-R3-C14-01` / `V70-R3-C13-01`.
- The authority relied on is the standing rule the ledger itself carries on those two rows:
  *"Activate only on a new frozen candidate"* (C14: *"…before C13"*), plus the Owner's
  C13/C14 gate-team execution order recorded in the ledger.

### 3.2 ⚠ First non-Owner record in that ledger

Before this round, **all 38 comments on #68** were authored by `yuguangzhi3836-glitch`
(the Owner). The activation record is authored by `chenzhenxi1-sudo`. It is additive only —
no body edit, no comment edit, no deletion — and it states its own authority basis and
claims no verdict, no execution and no release authority. It is recoverable: the Owner can
delete it, or supersede it with a `C13_C14_MODE = DISABLED | RETIRED` record in the
ledger's own format. This is flagged rather than assumed to be acceptable.

### 3.3 One fact recorded before the verdict arrived

The candidate's `application/` subtree is **byte-identical** to the tree the ledger already
carries for the earlier candidate `37d9a420…`:

```text
37d9a420…  :application = dd815baf0105cce603e9a28b002cfb9d8b95d186
8ffcde66…  :application = dd815baf0105cce603e9a28b002cfb9d8b95d186
aa2ec62b…  :application = dd815baf0105cce603e9a28b002cfb9d8b95d186
7db7b2aa5… :application = dd815baf0105cce603e9a28b002cfb9d8b95d186
```

Historical `PASS_SCOPED` is **not** transferable to a new SHA, so the gates were re-run — but
the result must not be read as "the application layer was reviewed and passed again", because
the application layer did not change in this candidate.

---

## 4. First real C14 production dispatch

### 4.1 The run

```text
RUN_ID       36141430817
RUN_URL      https://github.com/yuguangzhi3836-glitch/GO/actions/runs/36141430817
workflow     .github/workflows/c14-rule-compliance.yml   (dispatched on ref=main)
event        workflow_dispatch · attempt 1
head_sha     7db7b2aa52ecabc1ff1c92d9d1673f44f5ce68c5
created_at   2026-09-25T13:30:51Z      updated_at 2026-09-25T13:31:50Z
status       completed · conclusion SUCCESS
job 108091954474  "C14 fresh rule review (read-only, no quality sandbox)"  success
  steps 1–12 all success (checkout backend → checkout candidate → identity bind →
  scope digest → contract → AI review → seal → publish → API readback → publish readback)
```

`C14_TRIGGERED_BEFORE_C13 = YES` · `C13_DISPATCHED = NO` · `DEPLOY_PERFORMED = NO`

### 4.2 The real verdict (accepted as given)

`C14_VERDICT = PASS_SCOPED`

```text
C14_ROOT                411382da06dd4f4d5a0a9b470f61c758bf51d7b3aada5fb3711ae6ddd96e9cef
review_execution_id     resp_0dcaf7bc10c7b2a6006ab677b837a887d1b92d181eb2b13ae7
ai_provider / model     OPENAI_RESPONSES_API / gpt-5.6-sol
failure_class           null
blocking_issues         []
remediation_status      NOT_REQUIRED
opinion_sha256          321ce97b31b1754169407e5ecbda9298932f90466c40f987e4d655ec8ff83fb3
prompt_sha256           a85d5801a1434f149e2ff6e9a31c463694e111cab9f33cc754ac9dd8dd58acec
input_sha256            a7f63b45ca44cd2723e0ee030e0d1a0121ae33dcb908d31760bc555cc52987ef
rule_review_scope_sha2  843bed6169d0c834c0d08daf3952ea122af545c4f46b68461da252dfd80aadd8
nonce                   c14-36141430817-1-27821
authorizes_any_action   false
```

Findings the reviewer itself returned (both `INFO`, verbatim):

- `C14-SCOPE-001` — the candidate declares GO_CONSTITUTION, PERMISSION_BOUNDARY and
  AI_BEHAVIOUR_RULES, each at version `unversioned`.
- `C14-SCOPE-002` — **"The supplied changed_paths list is empty; therefore no candidate
  change affecting rules, permissions, IAM, contracts, regulatory duties, or AI behaviour is
  evidenced within the supplied review scope."**

Summary (verbatim): *"Scoped read-only C14 review passed on the supplied facts. No changed
paths or evidenced rule-boundary changes were provided. This verdict does not authorize
merge, deployment, or release."*

### 4.3 The identity the record actually carries — all correct

```text
cell_id              C14
task_id              V70-R3-C14-01                                        ← the ledger id
ledger_reference     {"round_id":"V70-R3","cell_id":"C14","task_id":"V70-R3-C14-01"}
issue_number         68
request_id           V70-R3-C13C14-01
candidate_sha        7db7b2aa52ecabc1ff1c92d9d1673f44f5ce68c5
application_tree     dd815baf0105cce603e9a28b002cfb9d8b95d186
github_run_id        36141430817 · attempt 1
principal_id         chenzhenxi1-sudo
```

### 4.4 Artifact bytes — downloaded and re-hashed, not taken from metadata

```text
artifact 10866698116  c13c14-lite-c14-7db7b2aa52ecabc1ff1c92d9d1673f44f5ce68c5
  size 2884 B · github digest sha256:b09e75cfa08f240469426733230ae5846ca781eb3fad0581da2ec4efabf85244
  re-hashed here  sha256:b09e75cfa08f240469426733230ae5846ca781eb3fad0581da2ec4efabf85244   MATCH
  members: c14_bundle.json · c14_contract.json · c14_opinion.json
artifact 10866808048  c13c14-lite-c14-readback-7db7b2aa52ecabc1ff1c92d9d1673f44f5ce68c5
  size 678 B · github digest sha256:508f9e6a3c60fd3df49b76439978307f401f99fd1d9119ad2d5971b141e8b537
  re-hashed here  sha256:508f9e6a3c60fd3df49b76439978307f401f99fd1d9119ad2d5971b141e8b537   MATCH
  members: readback.json
both expired=False
```

The two-step download works and the byte proof now succeeds (`bytes_verified = true`,
`bytes_mode = strict`), which CCV1-143 could not achieve outside the run. Inside the run the
`GITHUB_TOKEN` reads the storage endpoint fine; the earlier failure was caused by forwarding
the `Authorization` header to the signed URL.

Readback self-consistency:

```text
recomputed_digest == artifact.digest     True
head_sha == expected_head_sha            True   (7db7b2aa5… == 7db7b2aa5…)
run_status recorded                      "in_progress"  — in-run snapshot, structurally expected
```

### 4.5 Independent re-derivation performed on the downloaded bytes

`C14_ROOT` recomputes here from the bundle's own bytes:

```text
claimed    411382da06dd4f4d5a0a9b470f61c758bf51d7b3aada5fb3711ae6ddd96e9cef
recomputed 411382da06dd4f4d5a0a9b470f61c758bf51d7b3aada5fb3711ae6ddd96e9cef   MATCH
```

⇒ the sealed record is internally consistent. Integrity only, as always: `C14_ROOT` is a
public recomputation and proves nothing about authenticity on its own.

---

## 5. 🔴 Three real defects the first real dispatch exposed

All three were invisible until a real dispatch ran against a real merge commit. None of them
was caused by this round's inputs, and none of them is fixed in this round.

### D-1 — the changed-path boundary is **empty** for a merge commit

The "Bind the exact frozen candidate identity" step runs:

```sh
git -C candidate diff-tree --no-commit-id --name-only -r HEAD > changed_paths.txt
```

`git diff-tree` does **not** diff a merge commit unless `-m` / `-c` / `--cc` is given, so for
`7db7b2aa5` (a merge commit) this writes **0 lines**. Reproduced locally:

```text
git diff-tree --no-commit-id --name-only -r 7db7b2aa5            -> 0 lines
git diff-tree --no-commit-id --name-only -r 7db7b2aa5^1 7db7b2aa5 -> 2 lines
  .github/workflows/c13-quality-acceptance.yml
  .github/workflows/c14-rule-compliance.yml
```

Proven from the record itself, not inferred — the frozen scope digest matches the digest of
an **empty** changed-path list and does not match the digest of the two real paths:

```text
declared rule_review_scope_sha256                                843bed61…
digest over changed_paths = []                                   843bed61…   MATCH
digest over the 2 files PR #252 really added                     1356d60f…   no match
```

Consequences: the AI's facts say "nothing changed", and every C14/C13 verdict on a merge
commit reviews an empty change boundary. The reviewer's own `C14-SCOPE-002` finding is that
fact, surfaced honestly by the model. Fix direction (not applied): pass `-m --first-parent`,
or derive the boundary from the candidate contract rather than from `HEAD` alone.

### D-2 — the record's `workflow_sha` is not the workflow that ran

```text
bundle.workflow_sha   8889221c5907e13a59aea3021cbc22e0d225d401
backend pin a67ea8ac0 copy of that file   8889221c5907e13a59aea3021cbc22e0d225d401   ← it is this one
registered / executed blob on main        a9400e2fde4be173ce6d910f88d8ceb6dbdc42f4   ← not this one
```

Cause: `LITE_WORKFLOW_SHA="$(git rev-parse HEAD:$LITE_WORKFLOW_IDENTITY)"` runs in the
**first** checkout — the backend repo pinned to `a67ea8ac0` — while the workflow definition
that actually executed is the registered file on `main`. So `workflow_sha` / `workflow_ref`
bind to the pre-registration copy of the file, not to the executed definition. A later change
to the registered workflow on `main` would **not** move this digest, which defeats the
anti-drift purpose the field exists for.

### D-3 — the sealed record declares a smaller rule set than the review was given

```text
bundle.applicable_rules          ["GO_CONSTITUTION"]
bundle.applicable_rule_versions  {"GO_CONSTITUTION": "unversioned"}
prompt / facts rule set          GO_CONSTITUTION, PERMISSION_BOUNDARY, AI_BEHAVIOUR_RULES  (3)
```

Cause: `lite_cli.py:244` seals `applicable_rules` as
`opinion.get("applicable_rules") or spec.get("applicable_rules", ["GO_CONSTITUTION"])`.
The C14 output schema has no `applicable_rules` field and `_env_spec()` never sets the key
(the workflow exports no `LITE_APPLICABLE_RULES`), so the **single-element** fallback is used
— while `_facts()` at `lite_cli.py:126` uses a **three-element** fallback for the same
concept. The sealed record therefore understates the rules the review was actually run
against.

### D-4 (informational) — `run_status` inside the readback is `in_progress`

The readback is produced inside the run, so it cannot observe its own terminal conclusion.
Structurally expected, not a defect; recorded so the `null` conclusion is not mistaken for a
failed verification.

---

## 6. Writes performed this round

```text
1  Issue comment on #68      5833230504   (ledger task-identity activation record)
2  workflow dispatch         run 36141430817  (.github/workflows/c14-rule-compliance.yml, ref=main)
3  repo docs, this round     C13-C14-LITE-V2-ROLLBACK-RUNBOOK-20260925.md (update)
                             C13-C14-LITE-V2-ROUND-EVIDENCE-CCV1-145B-20260925.md (new)
```

Explicitly **not** done: no C13 dispatch, no deployment, no CC/HK connection or write, no
installation, no key generation, no change to `main`, no comment on any Owner PR, no edit to
the #68 body or to any historical comment, no new branch or registry or scheduler.

### 6.1 Raw evidence stored with this record

`docs/c13-c14-lite-v2/evidence/CCV1-145B-20260925/` — the bytes GitHub returned, not
re-typed values, with a `SHA256SUMS` covering every file:

```text
c14_bundle.json · c14_contract.json · c14_opinion.json · readback.json
github-run.json · github-jobs.json · github-artifacts.json
github-artifact-10866698116.zip   sha256 b09e75cf…   == GitHub's own digest
github-artifact-10866808048.zip   sha256 508f9e6a…   == GitHub's own digest
ledger-activation-issue68-comment5833230504.md   sha256 a2b859ee…  == the posted comment
collector-output.log
```

The two ZIP digests in `SHA256SUMS` equal the digests GitHub computes for the same artifacts,
so this copy can be checked against the platform without trusting either side.

> Verification note: `SHA256SUMS` is over the **committed** bytes. This repository sets
> `core.autocrlf=true`, so a Windows working copy may hold CRLF while the blob holds LF —
> check with `git cat-file blob <rev>:<path>`, not against the working tree. The two ZIPs are
> binary and unaffected either way.

---

## 7. What the PASS_SCOPED does and does not mean

```text
IS a real C14 terminal verdict for candidate 7db7b2aa5…            YES
IS bound to the ledger task id V70-R3-C14-01                       YES
IS internally consistent (C14_ROOT recomputes)                     YES
MEANS the two registered workflow files passed a C14 rule review   NO  (D-1: empty boundary)
MEANS the declared rule set was fully reviewed                     NO  (D-3: one rule recorded)
MEANS the workflow definition is bound by digest                   NO  (D-2)
UNLOCKS C13 for the same frozen candidate                          YES (ledger rule: C14 PASS_SCOPED → C13)
AUTHORISES merge / deploy / release                                NO  (authorizes_any_action=false)
```

`FINAL_RELEASE = HOLD` · `HK_DEPLOY = HOLD` · `PRODUCTION = HOLD` — unchanged.

## 8. Next gate (needs a human decision, not taken here)

1. Decide whether D-1 / D-2 / D-3 are fixed before C13 is dispatched, or C13 runs as-is for
   the same candidate and the defects are carried as findings. D-1 propagates to C13: its
   machine-test scope is frozen the same way.
2. Dispatch C13 (`V70-R3-C13-01`, same candidate) only if the above is decided.
3. Decide whether the #68 activation record's identity (written by the implementation account)
   should be re-declared by the Owner.
