# C13 independent Node seal acceptance

Date: 2026-09-14 UTC. Reviewer: independent C13 acceptance agent.

Decision: **NODE_TOOLCHAIN_BUILD_AND_INDEPENDENT_RESTORE_PASS_SCOPED**, for PR #70 tested head `c6e6390477613d5006c61e2ff2154ccd5f3813fd`, [workflow run 34795835590](https://github.com/yuguangzhi3836-glitch/GO/actions/runs/34795835590). The isolated Node toolchain sealing and restoration evidence is complete within this scope. Full release and Production remain HOLD; Hong Kong installation and deployment were not performed.

## Independently verified execution

I independently fetched completed GitHub job status, build and restore original logs, and artifact metadata. Build job `103828637154` and independent-restore job `103828848934` both concluded success, including their artifact uploads. I did not rely solely on the coordinator's reported success.

Build ran 7 archive safety tests successfully, provisioned the original pinned official Node, and emitted both R3.1.7_NODE_TOOLCHAIN: PASS and R8.2_GATE_TOOLCHAIN: PASS. The source and overlay comparisons in the reviewed script completed before candidate and package publication. The separate Ubuntu 22.04 restore job downloaded the original build artifact, computed the same ZIP digest, verified the inner package and all source/overlay inventories, compared the overlay to the retained pinned upstream archive, and reran the original R8.2 gate. It did not call the provisioner or download a fresh Node binary.

## Binding identities

| Identity | Verified value |
| --- | --- |
| Fixed canonical source commit | `c6ea4dd670db36e71f3839fb31e656a5c8806858` |
| Tested builder head | `c6e6390477613d5006c61e2ff2154ccd5f3813fd` |
| Application Git tree | `995d0d83faf883bec980c896fe8a17b0f12360fa` |
| Complete source fingerprint SHA256 | `1c4d78c3c1bb5f448d0ebdb99d16a2d76419bbc663cc9ed8fae831e1d18c10c4` |
| Canonical source files | 1332 |
| node-seal.tar.gz SHA256 | `5d6121c4ad06083056cb5f0f5a95329d4684e6e3e66d1e408d65c27ad113c347` |
| Node version / platform | v22.22.0 / linux-x64 |
| Node tree SHA256 | `e744dfe9bddd2e2c63d92199ab97a428fd2c17203d8a84c120ea96a4bc76c469` |
| Original Node archive SHA256 | `9aa8e9d2298ab68c600bd6fb86a6c13bce11a4eca1ba9b39d79fa021755d7c37` |
| Maximum required GLIBC | 2.28, below contract ceiling 2.35 |

Build provision reports one scanned ELF (Node; no additional shared objects selected) and GLIBC maximum 2.28. Both build and restore integrity gates independently emit Node maximum GLIBC 2.28. The build candidate at 01:26:13 UTC and restore receipt at 01:27:13 UTC bind the same source, package and Node tree identities. The gate verifies the restored Node takes precedence in PATH and executes the sealed binary; its manifest tree hash matches the runtime tree. The wrapper additionally verifies exact file bytes, file modes, and symlink identities against the retained official archive.

This is a separate Node overlay. It does not change the previously accepted Python business image or add generated binaries to the 1332-file canonical source. The exact source archive is retained inside the seal package and fingerprinted; a standalone SHA of the inner source.tar.gz was not printed in the original job log and is not invented here. Its inventory is retained in the artifact.

## Artifact cross-check

| Artifact | ID | ZIP bytes | ZIP SHA256 |
| --- | --- | --- | --- |
| Build delivery | `10329044609` | 101401043 | `ec1f1ab6d029919b337ca59dabdd8c0e18d315cb178509842071f90f667c4b7c` |
| Restore evidence | `10329518738` | 1584 | `941d9d29f2cc0baa99d588858105184b25d906fb8de27c351530a5b483a63b47` |

The build ZIP SHA agrees across original upload, independent restore's computed downloaded digest, and GitHub artifacts API. These ZIP identities differ from the inner node-seal.tar.gz SHA and are not interchangeable. API metadata binds both artifacts to the tested head and gives expiry 2026-12-13. This review does not claim indefinite binary retention or a separate local ZIP download/recalculation; it relies on the independent CI runner's recorded verification and successful restoration.

## Original failure and reviewed workflow correction

The original source review remains unchanged as a historical review of workflow SHA `dbf93bbc14438bde064a10efe404a08c1bc0d4d7a6d68818212e91ffcfc92235`. First head `6010ac260b81560cf9cce8ba4092c1e42d6b148b`, run `34795685137`, build `103828208266`: 6 safety tests passed and the valid relative-link test errored under Ubuntu 22.04 system Python 3.10's tarfile data filter. The error was LinkOutsideDestinationError on node/bin/npm -> ../lib/npm.js. Provisioning was skipped, artifact upload failed for lack of files, and restore `103828314345` was skipped. This original FAIL/SKIP remains recorded and is not overwritten as PASS.

The subsequent delta only locks Python 3.12.14 with setup-python in both jobs and tees safety-test output into an uploaded log. The archive data filter and safety assertions remain intact. I reviewed this delta and compared its remote content at the successful tested head with local bytes: exact equality. Current workflow SHA256 is `a215ae49ecf8b7142a3d72a096803017faa0fac2321ffd0d1bd1a09388036d16`. The packaging script and canonical source were unchanged; their source review is inherited. Successful CI confirms all seven safety cases now pass, including legal relative-link restoration.

## Preserved original job logs

The complete decoded GitHub job-log responses were saved and compared byte-for-byte, including final newline. The hashes below apply to UTF-8 local files, not GitHub compressed log archives.

| File | Bytes | SHA256 |
| --- | --- | --- |
| c13-node-seal-first-build.log | 41964 | `7c5853ae3863bd813b27fa08512fe5a0abdfb4dc93384d4a6553b403f24f7913` |
| c13-node-seal-build.log | 48958 | `0791dc1ebe25b1bfd086f89daaf96c90e89266f562851e5b648bc715bb19a963` |
| c13-node-seal-restore.log | 27823 | `dabe2cdcf313f4c80e62f56718f6aeed64beadf63fdab160cd6010aa3be562cb` |

## Scope and release decision

No remaining must-fix issue was found within this sealing/restoration scope. Merge of reviewed PR #70 is supported after the coordinator's final unchanged-head/diff check. Existing successful business/runtime CI should be inherited; this acceptance did not rerun it.

The restore workflow is not network-disabled at the runner level. The supported statement is that it restores the retained Node and does not download/reprovision Node. Successful isolated toolchain sealing does not prove native application/device acceptance, completion of all business journeys, all four release gates, a signed deployment plan, a fresh CANARY/VERIFY receipt, or installation into Hong Kong. No Hong Kong operation or GitHub write was performed by this reviewer. Full release and Production remain HOLD; deployment remains NOT_RUN.
