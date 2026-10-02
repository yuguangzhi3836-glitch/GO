# Runtime-root builder + admission merge — evidence (2026-10-02)

> Status: **source-integration + offline/shadow verification only.** Nothing here was
> installed, deployed, merged, or executed against a live host.
> Companion: `RUNTIME_ROOT_ATOMIC_SWITCH_20261002.md` (how the two halves must move
> together, and the rollback facts).

## 1. Why a merge, and not either source verbatim

The HK `HK_STAGING_TEST_PR` builder has three distinct historical facts that must
survive in one file:

| # | Fact | Where it lives | What it is |
|---|---|---|---|
| **A** | v4 runtime-root binding | owner PR **#311** (`pr/311` head `d386c77e`) | `runtime_source_digest`, `rm -rf /app` → `COPY . /app`, `PYTHONPATH=/app/src`, import-origin assertion, `EXECUTOR_VERSION = test-pr-v4-runtime-root` |
| **B** | uvicorn[standard] dependency-graph gate | live HK builder, commit **`15a89f91`** (PR #245 line) | `STANDARD_DEPENDENCY_PROFILE_SHA256`, `STANDARD_DEPENDENCIES_PROGRAM`, `_verify_dependency_profile` — a frozen, networkless dependency graph probe |
| **C** | failure-reason plumbing for B | live HK `transport.py` (PR #245 head `c09515a1`) | the `TEST_PR_*_REJECT` reason codes and `executor_version` on failure Evidence, without which a B refusal lands as `UNCLASSIFIED_REJECT` |

`main` has **neither A, nor B, nor C**. #311 has A but **not** B or C — and its own
base predates them. Copying #311 verbatim would therefore **delete the live
dependency check** (≈98 lines), which is exactly the kind of "update removes a
check" this project forbids. So the correct artefact is a deliberate three-way merge.

## 2. Baselines — read back from GitHub, not from any handoff

Every value below was re-read from the live repository on 2026-10-02 (CST), because
head SHAs move.

| Item | Value |
|---|---|
| `main` (base of this branch) | `4931fc3374b61e0fa03a1c98f0fae38bce4301ae` |
| PR **#311** head (SOURCE A) | `d386c77e3113f5eaa6be35107f2ef8889b7066df` |
| PR **#315** head (future rebuild target only) | `3cbc38a2ab254f7a28a6c2db9f9392d499aa2112` |
| PR **#245** head / branch `fix/hk-test-pr-executor-regression-pr172-20260924` (SOURCE B/C) | `c09515a17e255e4a80cd682c2b50c4b975d0c6ce` |
| commit **`15a89f91`** (the exact live builder revision) | `15a89f91` |
| `#311` base / merge-base with `main` | `b616d92ed53be2dfafb3ebd775d2f55a453fb238` |
| SOURCE B/C merge-base with `main` | `aa2ec62b68b49679c6d54217c7cb75f63a9c3ef0` |

`main` advanced only **2 commits** past `#311`'s base (and only in
`control-plane/runtime-host-channel-v1/**` + one doc), so **SOURCE A applies onto
`main` with zero overlap**. The huge "deletions" a naive `git diff main pr/311`
shows are `main`'s own advancement, **not** #311 reverting anything — this is the
single most important detail for reviewing this merge.

### Byte identities (sha256)

| Path | main | #311 | live HK | merged (this PR) |
|---|---|---|---|---|
| `hk-staging/hk_agent/test_pr.py` | `d1c454fc…d3f1f0` | `f92aabd6…7b612a` | `86c3cd05…2199` (= `15a89f91`) | **`723c6414…4d63db`** |
| `hk-staging/Dockerfile.go-application-python-v2` | `caad37b1…f8741b` | `542c8703…12dfca` | `caad37b1…f8741b` (= main) | **`542c8703…12dfca`** |
| `hk-staging/hk_agent/transport.py` | `8b874207…afbd0d` | (untouched) | `e4e2244c…52194` (= PR #245 head) | **`e4e2244c…52194`** |
| `command-center/go-candidate-admission` | `9d40e590…9f17d2` | `eb0fcfd3…9f17c` | n/a (Actions) | **`eb0fcfd3…9f17c`** |
| `contracts/release_candidate_v1.schema.json` | `9d0d7149…a0fc22` | `b10220c3…e9dac` | n/a | **`b10220c3…e9dac`** |
| `command-center-state-v1/contracts/failure_evidence_v1.schema.json` | `b703c779…9a809c` | (untouched) | n/a | **`16391837…537980`** |

Note `86c3cd05` is stable across **all** commits of the PR #245 line — the live
dependency check is not a moving target.

## 3. Merge method

Base = `main`. A = `pr/311`. B = PR #245 head. The two sources touch `test_pr.py`
in mostly disjoint regions, so the file was produced with a real three-way merge
(`git merge-file`), leaving **exactly one** conflict — the dependency line — whose
resolution is forced by this project's rule:

* take **B**'s call (`_verify_dependency_profile(_dependency_profile(…), runner)`) —
  it performs both the profile comparison and the frozen probe, so it subsumes
  `main`'s inline comparison and keeps the check **live**; and
* keep **A**'s `source_check` binding, which is the v4 runtime-root gate.

### Merge proof (line level, not a spot check)

Extracted additions relative to `main` and intersected against the merged file:

```
A added non-blank lines: 26   -> A lines MISSING from merged: 0
B added non-blank lines: 90   -> B lines MISSING from merged: 0
merged lines not traceable to base/A/B: 0
```

So the merged `test_pr.py` is exactly `A ∪ B` over `main` — **nothing dropped,
nothing invented**. The resulting `execute()` runs, in one pass:
`_verify_dependency_profile(...)` → `runtime_source_digest` binding → the
`docker run … --workdir /app … find_spec('go_hotel') … compileall -q /app/src && alembic heads`
gate.

## 4. Changed files

**SOURCE A — HK builder half**
* `hk-staging/Dockerfile.go-application-python-v2` (v4 recipe: `RUN rm -rf /app`, `WORKDIR /app`, `COPY . /app`, `ENV PYTHONPATH=/app/src`)
* `hk-staging/hk_agent/test_pr.py` (**merged A ∪ B**)
* `tests/test_runtime_source_root.py` (new)
* `tests/test_live_integration.py`, `tests/test_test_pr_durability.py` (version assertion → v4)
* `RUNTIME_ROOT_FIX_20261002.md` (new, from #311)

**SOURCE A — admission half**
* `command-center/go-candidate-admission` (`BUILDER_EXECUTOR_VERSIONS = (v4, v3, v2)`, `BUILDER_DOCKERFILE_SHA256_BY_VERSION` pinned pair, `check_build` resolves the recipe by declared generation)
* `contracts/release_candidate_v1.schema.json` (recipe-pair semantics)
* `tests/fixtures/real/Dockerfile.go-application-python-v2` (new; the frozen historical recipe, byte-identical to `main`'s `caad37b1…`)
* `tests/test_candidate_admission.py` (`RuntimeRootBindingTests` + `HISTORICAL_GO` seam)
* `README.md`
* `.github/workflows/command-center-candidate-admission-v1.yml` (historical-vs-current admission; prints `CURRENT_CANDIDATE_HOLD`)

**SOURCE B/C — live dependency check + its reason plumbing**
* `hk-staging/hk_agent/transport.py`
* `tests/test_dependency_compatibility.py` (new)
* `command-center-state-v1/contracts/failure_evidence_v1.schema.json` (closed reason-code set extended with the `TEST_PR_*` codes)

**This merge's own additions**
* `tests/test_merged_runtime_root_and_dependency.py` (new — the co-existence guard; see §6)
* `RUNTIME_ROOT_MERGE_EVIDENCE_20261002.md`, `RUNTIME_ROOT_ATOMIC_SWITCH_20261002.md` (this pair)
* the three regenerated `SHA256SUMS` manifests

### Why the manifests were regenerated, not copied

Both sources ship a stale manifest because both branched before `main` moved. In
particular `main` has already advanced `tests/test_artifact_store.py`
(`3760faad…`, PR #245's manifest still says `7f158aab…`) — copying either
manifest would publish a wrong hash. The three manifests
(`boss-test-pr-live-integration-v1`, `command-center-candidate-admission-v1`,
`command-center-state-v1`) were regenerated from the **index blobs** with the rule
"every tracked file under the component except `SHA256SUMS` itself, byte-sorted",
after first proving that rule reproduces `main`'s three manifests **byte-for-byte**.

## 5. Inherited test coverage mapped to the required cases

| Required | Provided by |
|---|---|
| Test 1 runtime root | `test_runtime_source_root.test_recipe_and_deployment_share_one_source_root`, `RuntimeGateTests` |
| Test 2 stale base source | `SourceRootTests.test_old_builder_passes_candidate_checks_but_compose_loads_old_frontend`, `…replacing_deployed_root_loads_both_fixes…` |
| Test 3 source digest | `SourceRootTests.test_source_digest_rejects_old_frontend_and_extra_base_files`, `test_digest_gate_program_runs_and_refuses_stale_bytes` |
| Test 4 dependency profile preserved | `test_dependency_compatibility.StandardDependencyTests` (behavioural, incl. `test_standard_profile_requires_isolated_probe`) |
| Test 5 dependency mismatch rejection | `StandardDependencyTests` rejections + `PR172ExecutorRegressionTests` |
| Test 6 runtime-root mismatch rejection | `SourceRootTests.test_digest_gate_program_runs_and_refuses_stale_bytes`, `RuntimeGateTests` |
| Test 7 admission generations | `test_candidate_admission.RuntimeRootBindingTests` |
| Test 8 cross-generation spoof | `RuntimeRootBindingTests.test_current_builder_rejects_old_recipe_and_legacy_rejects_new_recipe`, `…cannot_use_a_v3_result_or_the_reverse`, `test_relabelled_real_v3_image_cannot_become_v4` |

## 6. The merge's own guard (why the inherited suites are not enough)

Every inherited test proves **one** capability. None can fail if the merge dropped
the other. `tests/test_merged_runtime_root_and_dependency.py` closes that gap by
driving the merged `execute()` once with the shared recording runner and asserting,
**behaviourally**:

* the isolated dependency-graph probe is invoked **exactly once** (`--network none`,
  `--read-only`, `-I`, argv tail = `STANDARD_DEPENDENCIES_PROGRAM`);
* the runtime-root gate is invoked **exactly once** (`--workdir /app`,
  `PYTHONPATH=/app/src`, script contains `find_spec('go_hotel')`,
  `/app/src/go_hotel/__init__.py`, `runtime_source_digest`, `compileall -q /app/src`,
  `alembic heads`, and **no** `/workspace`);
* a legacy profile still takes the legacy path and needs no probe;
* a failing dependency probe, an unrecognised profile digest, and a failing
  runtime-root gate each fail the build **closed** (no `save`, no artefact).

Because a lost B would make a standard-profile build raise
`TEST_PR_DEPENDENCY_PROFILE_REJECT`, and a lost A would remove the `/app` gate,
these assertions fail if either side of the merge is lost.

## 6b. Measured results (real Linux — WSL `Ubuntu-24.04`, Python 3.12)

Run from a `git archive` (LF) extraction of this commit's `control-plane hk-staging
deploy docs command-center .github`. Point-in-time counts.

**Manifest verification** (LF extraction, `sha256sum -c`):

| component | entries | CR bytes | non-OK lines |
|---|---|---|---|
| `boss-test-pr-live-integration-v1` | 36 | 0 | **0** |
| `command-center-candidate-admission-v1` | 14 | 0 | **0** |
| `command-center-state-v1` | 79 | 0 | **0** |

**Builder suites** (module by module — the tests dir has no `__init__.py`):

| module | ran | fail | err | skip |
|---|---|---|---|---|
| `test_artifact_store` | 103 | 0 | 0 | 0 |
| `test_candidate_digest_wiring` | 32 | 0 | 0 | 0 |
| `test_dependency_compatibility` | 22 | 0 | 0 | 0 |
| `test_hk_install_fact` | 74 | 0 | 0 | 0 |
| `test_installed_identity_wiring` | 14 | 0 | 0 | 0 |
| `test_live_integration` | 35 | 0 | 0 | 0 |
| `test_media_mount` | 31 | 0 | 0 | 0 |
| **`test_merged_runtime_root_and_dependency`** | **6** | **0** | **0** | **0** |
| `test_migration_guard` | 21 | 0 | 0 | 0 |
| `test_runtime_source_root` | 6 | 0 | 0 | 0 |
| `test_test_pr_durability` | 18 | 0 | 0 | 0 |
| **total** | **362** | **0** | **0** | **0** |

**Admission:** `run_checks.py` → `status: PASS`, `tests: 156`, `failures: 0`,
`errors: 0`, `skips: 0`; the two test modules run `108 + 48 = 156`, all pass.

**Offline shadow matrix** (merged admission code, no install, no network, no host):

| case | expected | observed | rejected by |
|---|---|---|---|
| historical valid v3 evidence + historical recipe | ACCEPT | **ACCEPT** | — |
| historical v3 declared + v4 recipe | REJECT | **REJECT** | `candidate_build_dockerfile_sha256` |
| fresh v4 candidate + v4 evidence + v4 staged recipe | ACCEPT | **ACCEPT** | — |
| v4 declared + old (legacy) recipe | REJECT | **REJECT** | `candidate_build_dockerfile_sha256` |
| no evidence supplied | not ACCEPT | **UNKNOWN** | (design: never accepted, nothing refuted) |
| source/artifact digest mismatch | REJECT | **REJECT** | `candidate_artifact_digest` |
| cross-generation: v4 declared, v3 signed evidence | REJECT | **REJECT** | `candidate_test_result_evidence_builder_version` |
| cross-generation: v3 declared, v4 signed evidence | REJECT | **REJECT** | `candidate_build_dockerfile_sha256` |
| relabelled historical v3 image claiming v4 | REJECT | **REJECT** | `candidate_test_result_evidence_builder_version` |

One deliberate deviation from the task's wording: the "no evidence" row is
**`UNKNOWN`**, not `REJECT`. The component's contract is that absent evidence is
"never accepted" but is *also* not refuted, so it is reported as `UNKNOWN` — the
workflow asserts `an_absent_test_result_context_is_never_accepted`. The matrix is
PASS under that (stricter) rule.

## 7. Proven / not proven

**Proven here:** the merged sources carry both checks; the merged builder compiles
and passes its suites; the admission generations bind v2/v3/v4 to their own recipe
and reject cross-generation combinations; the manifests are internally consistent;
nothing was installed.

**Not proven (open):**
* no real `docker build`, no real `HK_STAGING_TEST_PR`, no live host was touched;
* the *behavioural* size of the old split-root defect on production candidates is a
  separate, earlier finding and is not re-measured here;
* whether the owner already knows about the split-root defect;
* PR #315 is **only** named as a future rebuild target — it is not rebuilt, not
  admitted, and not deployed by this change.

## 8. Explicitly not done

No install. No deploy. No CANARY/VERIFY/DEPLOY. No Task replay. No DB migration. No
change to `#311`/`#315` (branches, commits, merges, comments) and no merge of
anything. No write to HK-STAGING or the Command Center. No credential action.
