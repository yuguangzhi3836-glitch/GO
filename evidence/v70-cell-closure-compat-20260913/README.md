# V7 Cell convergence — inherited pagination compatibility follow-up

Current canonical compatibility review and fixed-source frozen CI: PASS.
PR66 source merge is confirmed at 779ca25e1e14f141fc6626040fcf026d034f706e.
Full release and deployment: HOLD. Production: HOLD. Hong Kong: NOT_ACCESSED.

The user explicitly authorized uploading this round's source, tests, original
acceptance logs and Evidence to the private yuguangzhi3836-glitch/GO repository,
creating a Draft PR, running isolated CI, and merging/deploying. Authorization
does not manufacture technical Gate results or signed deployment material.

## Source identity and retained work

- Canonical parent: 286e294d92df4b7d1c0073116a8e628734abec6c.
- First candidate / original CI source: 9f28f822110e187c22baf82391063c8b05c039c1.
- First application tree: b9aee82e8c3932a540349b1f62b714c5ea52e837.
- Parallel local compatibility tree (not adopted): f14040676fbaed9a9f5bf6e698b716385ebf40b2.
- Parallel local source SHA256: 550c7e2d7c7a408f6a82021e85221a3db3c1c7e34160da8ec9cb52d655117f04.
- Adopted tested head: ddd2b9d82d560ba2657a7904f061fb20196d5924.
- Adopted main merge: 779ca25e1e14f141fc6626040fcf026d034f706e.
- Canonical application tree: 995d0d83faf883bec980c896fe8a17b0f12360fa.
- Canonical source SHA256: 1c4d78c3c1bb5f448d0ebdb99d16a2d76419bbc663cc9ed8fae831e1d18c10c4.
- Source files remain 1332; no test or application path added or removed here.
- Parallel operations-console SHA256: e945428dec148fcabdb904a3fcbd9232a3bed6a657a61dbb78869d0866113724.
- Canonical operations-console SHA256: dd8ce37a8fa8def78d855012086f22c841aacdda8bbe7437f8322297e53a9a38.

The six preceding P1 repairs and 119 new regression cases are inherited, as are
the PR62 pagination/search and PR64 capacity improvements. They were not
redeveloped. The previous evidence directory remains the first-round record,
bound to its recorded source; this directory contains the additional finding
and the two explicitly separated source fingerprints. While the local follow-up
was being assembled, another authorized execution updated and merged PR66.
Readback confirmed that its route differs from the local follow-up only by one
blank line; C14 independently confirmed complete AST equivalence. The local
parallel patch was not committed to the application branch or substituted for
the accepted canonical source. This archive changes evidence only and inherits
the accepted application tree. Original local test hashes remain bound to the
local variant; actual canonical CI is recorded separately below.

## Actual full regression finding and minimal fix

The first four-shard frozen run covered all 253 test files, partitioned
64/63/63/63. Results: 1932 tests, 1925 passed, one failed, six skipped.
The sole failure was test_admin_hotel_refund_amount_is_real_column in
tests/test_depth41_transaction_views.py. Its existing direct Python call to
vertical_snapshot received FastAPI Query objects as ordinary default values;
order_id.strip failed. This is distinct from the earlier local DBMOVED issue.

C12 changed only an Annotated import and four parameter declarations, retaining
ordinary Python defaults and the existing HTTP ge/le/max_length constraints.
The administrator dependency, function body, SQL, refund projection and
pagination behavior are unchanged. No existing test was edited.

C12 reproduced the old failure (one failed), then passed the full original
transaction-view file (12) and original SQL/HTTP pagination tests (28).
C14 independently compared the exact old Git blob and all unaffected AST,
checked the original test records and returned PASS_SCOPED. C13 independently
passed the direct-call regression (one) and HTTP parameter/role checks (nine).
Reports and original local XML/log records are preserved here.

## First fixed-commit CI originals

| Run | Scope | Actual first result |
| --- | --- | --- |
| 34764800518 | New isolated scoped workflow | 119 new cases + 11 capacity + 28 pagination PASS |
| 34764800483 | Full retention and frontend/HTTP | Shards: 1925 PASS / 1 FAIL / 6 SKIP; frontend270, compatibility34, HTTP150 checks PASS |
| 34764800484 | Browser and PostgreSQL | Six same-order browser journeys and independent ledgers PASS_SCOPED; PostgreSQL16.4 migration to0133 and six concurrency checks PASS |
| 34764800494 | Mobile source/native linking | PASS_SCOPED; generated projects are not physical-device or signed-build acceptance |

The initial-ci directory preserves all nine completed original job-log texts
returned through the authorized GitHub connector, plus C13's independently
reconstructed test-file partition. The six skips are not counted as passes.
The separate PostgreSQL job passes six cases, but absent artifact JUnit node IDs
are not silently inferred to prove a one-to-one skip substitution.

Artifact metadata and upload logs report their ZIP digests. Temporary artifact
download references returned HTTP403 in this environment, so no downloaded-ZIP
digest verification or full binary/screenshot archive is claimed. The original
artifacts remain attached to their exact GitHub runs. Their retention periods
do not substitute for permanent binary archive evidence.

## Remaining gates and next action

Canonical runs 34781824271, 34781824424, 34781824291 and 34781824295 all completed
successfully on ddd2b9d82d560ba2657a7904f061fb20196d5924. Four full shards covered
253 files and reported 1926 PASS, zero failures/errors and six PostgreSQL skips.
The dedicated PostgreSQL16.4 job ran the same six cases with six PASS and no
skip. C13 established the mapping from the fixed runner environment, skip
conditions and exact dedicated selection, not merely equal counts. The scoped
workflow passed the 119 new repair cases, 11 capacity cases and now 34 pagination
and direct-call cases. Frontend, HTTP, browser ledgers and mobile source/linking
checks passed within their declared scope. No test rerun was initiated here.

The nine canonical job-log originals are retained in canonical-ci/. The latest
C13 canonical review records these results and source/merge identities. The
historical package/archive jobs were skipped by their exact old-candidate guards;
they do not constitute a runtime package or sealed-node PASS.

The source repair is complete and inherited. The next remaining execution
boundary is the fixed canonical candidate's deployment evidence chain, not a
repeat of the business repair or already-passed CI.

The current deployment plan contract additionally requires all four release
gates PASS, a candidate runtime package/image binding, fresh signed CANARY and
VERIFY, and a registered signed approval plan. These are not produced by this
source change. No guessed plan, Task, signature or runtime mutation is allowed;
the current Hong Kong DEPTH48 runtime and Production remain unchanged.
