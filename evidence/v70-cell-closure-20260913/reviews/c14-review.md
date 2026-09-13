# C13 independent review — C14 release input guards

## Decision

`C13_SCOPED_CODE_REVIEW=PASS` and `C14_SCOPED_INPUT_GUARD=PASS` for the reviewed
file hashes below. No newly introduced P0/P1 defect was found within the
malformed-input / actor-separation repair scope.

`COMPLETE_RELEASE_EVIDENCE_CHAIN=HOLD`. This result is not release approval,
production qualification, a legal/compliance opinion, or permission to deploy.
HK DEPTH48 was not accessed or changed. Production remains HOLD.

## Independent provenance and scope

C13 read the repository root/application AGENTS instructions, README and
OPERATING_CONTEXT. C13 did not implement or edit the business repair. The
baseline release module was fetched read-only directly from fixed commit
`286e294d92df4b7d1c0073116a8e628734abec6c`, Git blob
`9e3deb62132f9f9068771102e9358f39988dd4e4`:

https://github.com/yuguangzhi3836-glitch/GO/blob/286e294d92df4b7d1c0073116a8e628734abec6c/application/src/go_hotel/autonomy/release.py

Reviewed candidate files:

| Path | SHA256 |
| --- | --- |
| application/src/go_hotel/autonomy/release.py | add9483e8e11e115a8bdb57791528a4137577088e396bdbcdb18cb302a1f3802 |
| application/tests/autonomy/test_c14_release_evidence_guards.py | 051e330942d6f969aeed58f43bd4d4d4621379bf3e8801e5a2978cc0d00508c2 |

Review additionally inspected the Cell registry, definitions, exports and all
visible application call sites of `authorize_promotion`. The helper currently
has tests/exported-library usage; no runtime deployment caller was found.
The parent must bind this review to the eventual aggregate source commit/tree.

## Original developer evidence checked

The three XML files in `c14-evidence/` were parsed independently:

| Original developer run | XML result |
| --- | --- |
| baseline.xml | 82 tests: 59 failures, 23 passes, no errors/skips |
| fixed.xml | 82 tests: 82 passes, no failures/errors/skips |
| inherited-controls.xml | 60 tests: 60 passes, no failures/errors/skips |

These are developer-run historical artifacts. C13 has not relabeled them as
independent runs or claimed that 59 failures mean 59 separate exploit paths.

## Independent executions

C13 separately executed the new tests plus the unchanged Build 01, Build 01.1,
and DEPTH16 authority tests: **142 passed in 0.32 seconds**, zero failures,
errors or skips. Raw JUnit: `c13-review/c14-independent.xml`; SHA256:
`07b47da77cf3caccb30034006679345bc3a3f73544a92c54e9aa253472b3dbf9`.

Command, from the GO source directory:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=application/src /workspace/scratch/2d68c25b0133/go-venv/bin/python -m pytest --noconftest -p no:cacheprovider -o addopts='' application/tests/autonomy/test_c14_release_evidence_guards.py application/tests/autonomy/test_v7_ai_org_build01.py application/tests/autonomy/test_v7_ai_org_build01_1_legal_authority.py application/tests/autonomy/test_depth16_current_authority.py -q --tb=short --junitxml=/workspace/scratch/2d68c25b0133/c13-review/c14-independent.xml
```

C13 also independently enumerated all **160** combinations of five typed risk
classes and five boolean flags, with registered distinct actors and legacy
empty references. Every output agreed with the baseline risk decision table.
This additional matrix is a compatibility probe, not 160 new business features
and not evidence-completeness acceptance.

## Semantic findings

1. Raw strings cannot bypass enum identity comparisons; truthy strings/integers
   cannot impersonate PASS flags. Invalid inputs now fail with explicit
   GovernanceViolation instead of falling through or leaking incidental errors.
2. Builder, validator and releaser must be nonblank registered Cell identities;
   C13 remains the validator and cannot simultaneously be the releaser. The
   C14-inclusive existing registry is used without adding/changing capabilities.
3. Valid R0/R1 inputs retain their restricted/qualified outcomes. R2 retains
   shadow then canary progression. Valid R3 stays deterministic-controlled and
   R4 prohibited independently of pass flags. Badly typed R3/R4 inputs now
   raise before classification, a deliberate fail-closed input boundary change.
4. Existing empty-reference behavior is deliberately preserved. Reference lists
   are also accepted by the guard although the annotation says tuple; this does
   not provide immutability, retrieval, authenticity or source binding.
5. The patch does not authenticate actors, retrieve referenced evidence, check
   signature/freshness, validate policy version or tie the candidate ID to a
   source tree/artifact. These are remaining evidence/authority boundaries,
   not capabilities proven by these tests.

## Required reporting boundary

An empty `evidence_refs=()` can still return `AUTONOMOUS_QUALIFIED` from this
legacy classification helper. Therefore **passing C14's scoped guard tests
must never imply a complete C14 Gate → C13 acceptance → Evidence chain**.
The function's enum output is not sufficient completion evidence. Even a
nonempty opaque reference string is not proof that corresponding evidence
exists or matches this candidate.

The current authorized repair can be accepted as a scoped P1 malformed-input
guard while the complete evidence chain remains HOLD. Enforcing nonempty,
authenticated, source-bound evidence requires an explicit compatibility
contract/caller integration and separate acceptance. The existing qualification
registry already has stricter evidence, policy and production-accountability
checks; those were not weakened or replaced here.

No development result in this review triggers installation, migration, staging
deployment or Production changes.
