# Atomic switch plan + rollback facts — runtime-root v4 builder / admission

> **Plan only. Not executed.** This document exists so that whoever performs the
> switch (a later, separately authorised turn) has the exact files, hashes,
> forbidden states and rollback point in one place.
> Companion: `RUNTIME_ROOT_MERGE_EVIDENCE_20261002.md`.

## 1. Why the two halves cannot move separately

The builder and the admission contract are **a pinned pair**. The builder stamps a
`dockerfile_sha256` into every artefact it produces; admission resolves the
*expected* recipe from the declared executor generation. So:

| State | Result |
|---|---|
| **A** — HK builder = v4, admission = v3-only | every fresh v4 artefact is refused: `candidate_build_dockerfile_sha256` (fail-closed) |
| **B** — HK builder = v3, admission = v4 | the staged recipe no longer matches the builder that produced the artefact, and v4 evidence is expected but not producible |

Both states break the currently-working `TEST_PR → admission` path. Neither half is
useful alone, and installing one half is **worse than installing neither** because
it converts a working chain into a refused one. Therefore the switch is a single
maintenance transaction.

## 2. Half 1 — HK builder (host files)

| File (installed path observed on HK) | current sha256 | target sha256 | executor version |
|---|---|---|---|
| `/opt/go-hk-agent-rebuilt/hk_agent/test_pr.py` | `86c3cd05…2199` | **`723c6414…4d63db`** | `test-pr-v3` → **`test-pr-v4-runtime-root`** |
| `/opt/go-hk-agent-rebuilt/hk_agent/transport.py` | `e4e2244c…52194` | `e4e2244c…52194` (**already equal — no byte change**) | — |
| `/usr/local/libexec/go-hk-test-pr/Dockerfile.go-application-python-v2` | `caad37b1…f8741b` | **`542c8703…12dfca`** | — |

Notes:
* `transport.py` is **already** the PR #245 head revision on the live host, i.e. the
  reason-code plumbing is live. Installing the merged component is byte-identical
  for this file, so the switch changes exactly **two** files on the host.
* The integrity anchor is the component's own `SHA256SUMS` (33 entries),
  regenerated in this PR; the component's installer verifies it with
  `sha256sum -c SHA256SUMS`, and that is a `git archive`-LF comparison — install
  from LF bytes, not from a CRLF working copy.
* `test_pr.py` is the file whose self-check the executor runs; `Dockerfile…v2` is
  the recipe it builds with. Both must land together, with the executor taken out of
  flight for the swap, then brought back.

## 3. Half 2 — admission (repository + Actions)

There is **no host install point** for admission: it is a CLI that runs inside
`.github/workflows/command-center-candidate-admission-v1.yml`. "Installing" it means
landing these files on the branch the workflow runs from.

| File | current (`main`) sha256 | target sha256 |
|---|---|---|
| `control-plane/command-center-candidate-admission-v1/command-center/go-candidate-admission` | `9d40e590…9f17d2` | **`eb0fcfd3…9f17c`** |
| `control-plane/command-center-candidate-admission-v1/contracts/release_candidate_v1.schema.json` | `9d0d7149…a0fc22` | **`b10220c3…e9dac`** |
| `.github/workflows/command-center-candidate-admission-v1.yml` | `main` revision | this PR's revision |
| `control-plane/command-center-state-v1/contracts/failure_evidence_v1.schema.json` | `b703c779…9a809c` | **`16391837…537980`** |

The admission half must be live **before or with** a v4-built artefact being
submitted: a v4 artefact presented to the old admission is refused, and the old
`CURRENT_CANDIDATE` (v3 evidence) presented to the new admission is refused by
design — the new workflow prints
`CURRENT_CANDIDATE_HOLD: fresh v4 TEST_PR evidence required`.

## 4. Forbidden end states (assert before and after)

* **both new, but no v4 evidence yet** → `CURRENT_CANDIDATE_HOLD` stays printed;
  that is the *expected* state until a fresh v4 `TEST_PR` runs. Do not read it as a
  failure, and do not try to clear it by relabelling the historical candidate.
* **HK new + admission old** ⇒ state A. Symptom: `candidate_build_dockerfile_sha256`.
* **HK old + admission new** ⇒ state B. Symptom: recipe/runtime mismatch against the
  staged builder.
* **historical v3 evidence relabelled as v4** ⇒ must remain `REJECT`; the admission
  tests pin this (`test_relabelled_real_v3_image_cannot_become_v4`). Any change that
  makes it pass is a defect, not a fix.

## 5. The maintenance transaction (for the later authorised turn)

1. **pre-read** — record, on both halves: the live file hashes above, the executor
   version string (`grep EXECUTOR_VERSION`), and the current admission verdict for
   `CURRENT_CANDIDATE` (`REJECT` expected).
2. **quiesce** — stop accepting new builder work (the agent timer), confirm no
   builder in flight.
3. **change half 1** — stage the two host files from LF bytes with the component
   manifest as the anchor; verify `sha256sum -c SHA256SUMS` on the extracted tree
   first, then atomically swap, keeping the previous bytes as the rollback point.
4. **change half 2** — land the admission files so the workflow revision is live.
5. **post-read** — re-hash both halves; run the admission workflow on a v4-shaped
   synthetic record (offline/shadow) and confirm ACCEPT; confirm the historical
   record still `REJECT`s.
6. **shadow / health** — restart the agent, observe one idle cycle, confirm no
   unexpected refusals.
7. **on any failure — roll back both halves** (§6). Never roll back one side.

## 6. Rollback facts

Rollback = **restore half 1 AND half 2 together.**

**Half 1 (HK builder)** — restore the previous bytes:

| File | previous sha256 (rollback target) | new sha256 (to be removed) |
|---|---|---|
| `hk_agent/test_pr.py` | `86c3cd05…2199` (= commit `15a89f91`) | `723c6414…4d63db` |
| `hk_agent/transport.py` | `e4e2244c…52194` (unchanged) | `e4e2244c…52194` |
| `Dockerfile.go-application-python-v2` | `caad37b1…f8741b` (= `main`) | `542c8703…12dfca` |

Because `15a89f91` is a real commit on
`fix/hk-test-pr-executor-regression-pr172-20260924`, both previous builder bytes are
recoverable from Git — but recover them by hash, not by branch tip, since the tip
carries later commits.

**Half 2 (admission)** — previous Git content is exactly `main`'s revision of the
four files in §3 (`9d40e590…`, `9d0d7149…`, `b703c779…`, plus `main`'s workflow).
Rollback = revert those paths to the `main` revision; the hashes above prove the
restore.

**Rollback verification:** re-hash both halves against the "previous" column and
re-run the admission workflow; the historical candidate must return to `ACCEPT`
against its own pinned recipe (`HISTORICAL_GO` semantics), and the pre-switch
behaviour must be reproduced byte-for-byte.

## 7. Follow-up after a successful switch

* the next candidate must be **rebuilt** with the v4 executor — a fresh
  `HK_STAGING_TEST_PR` is the identity of the candidate (`plan_derivation` cites its
  `task_id`); you cannot admit a candidate built by the old builder;
* the historical `CURRENT_CANDIDATE` and its signed v3 Evidence must **not** be
  edited or relabelled; a new coherent
  source/build/image/Evidence/package set must be produced, and
  `candidate_contract_sha256` recomputed with `candidate_fact.py`;
* the intended rebuild target is the PR named for it at the time of the switch
  (recorded as PR #315 head `3cbc38a2…` on the date of this document) — **its own
  content gates must be resolved first**, and this merge neither rebuilds nor admits
  it.
