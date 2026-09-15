# C13 independent canonical runtime package acceptance

Review date: 2026-09-14 UTC. Reviewer: independent C13 runtime CI acceptance agent.

Result: **RUNTIME_PACKAGE_AND_INDEPENDENT_RESTORE_PASS_SCOPED** for PR #69 head `83b253931864f8c2664a0a897b9a5c833286d8c5`, workflow run [34795198840](https://github.com/yuguangzhi3836-glitch/GO/actions/runs/34795198840). This accepts the fixed package build and isolated image restoration. It is not Full Release, Sealed Node, worker liveness, or Hong Kong deployment acceptance.

## Independently observed evidence

I fetched the actual PR-head package script from GitHub and compared it byte-for-byte with the reviewed local file: equal, SHA256 `9051ccdf05656117df1d6d950312e8d76229454facda5dc013c0927a215155c9`. The workflow's remote original was also equal to the local reviewed workflow. I read C14's source review and independently read both completed GitHub job logs, rather than accepting the coordinator's status report.

| Job | GitHub result | Observed execution |
| --- | --- | --- |
| build `103826805378` | success | Checkout of exact head; 6 packaging safety tests passed; Docker build, source-bound package, smoke, and artifact upload completed |
| independent-restore `103827088259` | success | Separate job checkout of the same head; original artifact downloaded and its ZIP digest computed; image loaded from the package and executed with network none; restore receipt emitted and evidence uploaded |

Build and restore use separate GitHub-hosted `ubuntu-24.04` jobs. Restore has no Docker build step and calls `docker load` on the downloaded original image. The workflow uses read-only contents permission and removes checkout authentication before execution. No previous business regression was rerun by this review.

## Exact source, package, and image binding

| Identity | Value |
| --- | --- |
| Fixed business source commit | `c6ea4dd670db36e71f3839fb31e656a5c8806858` |
| Builder / tested PR head | `83b253931864f8c2664a0a897b9a5c833286d8c5` |
| Application Git tree | `995d0d83faf883bec980c896fe8a17b0f12360fa` |
| Source fingerprint SHA256 | `1c4d78c3c1bb5f448d0ebdb99d16a2d76419bbc663cc9ed8fae831e1d18c10c4` |
| Complete source archive files | 1332 |
| runtime-package.tar.gz SHA256 | `b297f139a236681019fe894f4f1a94068636649e1235a20502a383a610f16f63` |
| Image config ID | `sha256:47bb66c429868689e922ecc1bee668e9c12bfa24e2cddca1717e16887f34115d` |
| Image tag | `go-hotel:canonical-995d0d83-20260914` |
| Registry RepoDigests | Empty list, as observed; none invented |

The build log emits the candidate at 01:14:45 UTC and the package SHA above. The restore log at 01:16:05 UTC emits the same package SHA, image ID, application tree, and source SHA after successful verification and image execution. The emitted receipt explicitly retains sealed_node=HOLD, full_release=HOLD, deployment=NOT_RUN, production=HOLD.

The reviewed successful execution path verifies complete source archive contents and 1332-file fingerprint on both build and restore; checks the three fixed deployment-contract Git blob hashes; hashes every package member before Docker load; checks the loaded tag's actual image config ID; verifies the image's 1328 retained source files; and asserts absence of exactly four named pytest-cache files excluded by the canonical Dockerfile build context. Those four files remain in the complete source archive and do not represent missing business source. The image probe also asserts Alembic head 0133_flight_change_plan, imports seven worker modules, initializes a disposable SQLite database before the original image CMD, checks HTTP health status=ok, and requires more than 900 OpenAPI paths. These assertions completing is supported by the success path and receipt; individual probe JSON files remain in the uploaded artifact and are not separately claimed downloaded by this reviewer.

## Artifact identities

| Artifact | ID | Bytes | ZIP SHA256 |
| --- | --- | --- | --- |
| Original build delivery | `10328889188` | 114416212 | `0402a0308a459c661f9ed1a256923be2b589cbe5e4ddfcb424877e34704e4a5f` |
| Independent restore evidence | `10328978838` | 9026 | `bb6239dc64f583013d9d2a6a98ac93af21b1301a269a37e85d26152ebc1c4307` |

I cross-checked these against the GitHub artifacts API. The restore download log independently computes the build ZIP SHA256 `0402a030...e4a5f`, matching both the original upload log and GitHub artifact metadata. ZIP SHA and inner runtime-package SHA are different identities and must remain separate. Artifacts currently expire on 2026-12-13 according to GitHub; this is retained CI delivery, not a claim of indefinite binary retention. I did not personally download/recompute the ZIP in this workspace; the independent restore runner's verified download and executed restore are the evidence relied on.

## Original failed attempt retained

Run `34795009463`, old head `6d621e9be0fae87a2899c8271079f8c281c14a40`: build `103826275178` failed and restore `103826477238` was skipped. Docker built an image, but the original checker incorrectly required `/app/.pytest_cache/.gitignore`, a file excluded by the canonical build context. This was a packaging checker defect, not a business-source regression. The original FAIL and SKIP remain historical results; they are not overwritten with PASS.

Its failure-only artifact `10328963570` was 177506 bytes / four uploaded files, ZIP SHA256 `164ef6af1c235c4c8d8a6baeb07b43786955375633ef188c5a04183e6363c30d`. It was not a completed runtime delivery. The subsequent repair precisely distinguishes the 1332-file source archive from the 1328-file runtime image and asserts excluded cache files are absent. No business source was changed to solve this packaging defect.

## Preserved raw logs

Each local file below was compared with the entire decoded GitHub job-log tool response and matched exactly, including final newline. Hashes are over UTF-8 file bytes, not compressed GitHub log archives.

| File | Bytes | SHA256 |
| --- | --- | --- |
| c13-runtime-package-first-build.log | 67241 | `7f61c5976df616df060f2b07654abbd2becedc93a8968145650b612be4f8541b` |
| c13-runtime-package-build.log | 66777 | `34a275e9cfedf783345ea439e368a3fdb7d5386420ae58571358a5abbded8f81` |
| c13-runtime-package-restore.log | 23601 | `1e517e9c95d8e8b7a1149df7d7c4ee9d9bf1b2f3014fc8214ed5b9810400c641` |

## Acceptance limits and decision

No remaining must-fix issue was found within this runtime packaging and independent restore scope. PR #69 may inherit the unchanged application's previously accepted business CI; this packaging acceptance does not reopen it. Merge of the reviewed packaging changes is supported by this scoped result, subject to an unchanged-head/diff check by the coordinator.

The package records floating upstream dependencies resolved at build time; it does not claim a frozen toolchain or byte-identical future rebuild. Its saved image is what was independently restored. Worker imports do not prove worker liveness, health/OpenAPI do not prove complete business journeys, and SQLite smoke does not replace PostgreSQL acceptance. The Python image is not Sealed Node. No signed CANARY/VERIFY, approved deployment plan, runtime receipt, or all-four-gate release closure was produced by this workflow. Hong Kong runtime was not touched by this review. Full Release and Production remain HOLD; deployment was not run.
