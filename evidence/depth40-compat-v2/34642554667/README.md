# DEPTH40 COMPAT V2 — inspected independent CI evidence

Tested source: `d49465a56a7768bc4e657858272a597c5d1f05d6`, [PR #43](https://github.com/yuguangzhi3836-glitch/GO/pull/43).

[Run 34642554667 / job 103405533919](https://github.com/yuguangzhi3836-glitch/GO/actions/runs/34642554667/job/103405533919) completed SUCCESS on 2026-09-12 at approximately 04:10 Beijing time.

- 04:08:06: 34 regression cases passed on the independent runner. Executor Docker operations are simulated, with real Python, temporary durable records and test Ed25519 signatures.
- 04:09:54: exact fixed parent archive verified; new child image built without build network access; 1271-file source check and exported image reload completed. New config ID: `sha256:cba95a5ac6f061b8196f953f181952fdad94ab520a12cbeb0e7ee49d9a6de150`.
- New image archive SHA256: `edca0c20cac07950b79814ef2e5ec56d3551430a02ff6943532a9009538395a5` (175057507 bytes).
- 04:10:09: actual isolated PostgreSQL 18.4 accepted valid widths/unbounded text and rejected NULL-width integer and narrow varchar. This is a dedicated schema-guard fixture, not the Hong Kong database or full migration acceptance.
- 04:10:15: [artifact 10280363223](https://github.com/yuguangzhi3836-glitch/GO/actions/runs/34642554667/artifacts/10280363223) uploaded; ZIP SHA256 reported by GitHub `6608de4ca772e0617b3d02103ed893df9389ddaa2c5878635594219c32bcb600`, 174312027 bytes.

The reviewer inspected original job output and code and extracted the two JSON primary outputs here. The artifact download connector returned a file reference, but local materialization failed with HTTP 502; the ZIP and its members were **not independently rehashed locally**. Image verification above is actual CI output, not a claim of an extra local Docker run. `CI_JOB.redacted.log` retains the fetched output, with query-string redaction if present; this run contained no URL queries requiring redaction.

The image/ZIP IDs belong to this new child, not the frozen base. The executor package is still site-UNBOUND and has not been installed. Registry RepoDigest remains absent. The signed recovery-preparation requirement and actual site backup/restore readiness are not waived. No Hong Kong task, installation, schema change, TEST_PR, merge or Production operation occurred.

This evidence branch adds only evidence files to the exact tested commit. It does not update PR #43's source head or trigger another CI run. Prior passed results and original artifacts remain preserved.
