# Non-DOT HK release: live baseline observation

Owner instruction: 除DOT外，其他全部部署香港. Authorization is retained; no repeat approval is requested.

Formal read-only Request: https://github.com/chenzhenxi1-sudo/go-control-tasks/pull/125

Command Center published Task commit `743b2bfbc68dea46196790fae463fc854ceb5705`, task ID `go-boss-request-verify-20261001T022954Z-680077d3dc33`.

Evidence commit: https://github.com/chenzhenxi1-sudo/go-control-evidence/commit/8163118103aeb219aae4e9c2e14fb73e9d3af920

Completed 2026-10-01 10:31:29 Asia/Shanghai. Returned status SUCCESS / VERIFY_OK; API health, worker liveness, current/candidate image, Compose/environment and Alembic checks report PASS. `application_health_proven=false` remains explicit. This session read the Task and Evidence from the formal repositories and compared their task ID/nonce/environment/image bindings; it did not independently perform cryptographic verification of the Evidence signature.

Both Task and Evidence bind image `sha256:3652b1d6392ee8eed816bfa484872bfc443a95abbd36bcbca887c96975915cdf`, the older PR202 image. The currently selected candidate has therefore not advanced to the requested combined non-DOT release. Sending DEPLOY now would not establish deployment of all requested work.

No DEPLOY was submitted. The source-retention, performance and final-candidate independent review gaps in coverage.json remain unresolved. That file's PENDING field is its creation-time observation; this document records the subsequent verification result. No product source, main branch, runtime, migration, registration setting, DOT/new-host installation or Production setting was changed.

## Evening refresh and new source integration

Request #126 produced task `go-boss-request-verify-20261001T120903Z-17d1570d252b`; Evidence at `evidence/go-boss-request-verify-20261001T120903Z-17d1570d252b-MldUYcyfiiVd6fCcmDe808fa2FFtWH9c.json` on go-control-evidence/permission-test reports SUCCESS / VERIFY_OK, completed 2026-10-01T12:11:29Z (20:11:29 Asia/Shanghai). Task ID, nonce, environment and both image IDs match the Task. This session has not independently verified the cryptographic signature. Both image IDs remain the earlier PR202 image `sha256:3652b1d6392ee8eed816bfa484872bfc443a95abbd36bcbca887c96975915cdf`; new source is not admitted/deployed by this check.

Source-integration Draft GO #298 now combines frozen #279 `40d59f85...` and the approved #296 brand assets: head `e109af4dc4ae84f27f63d0104aa42c8d6b64b34d`, root `c4f4faa0182e9cd1c200033cff57d82b3fd8c40f`. All non-brand parent tree paths are retained; three changed JS files have single header-only deltas, and all existing entrypoint script counts are retained. Local brand contract 5/5 and three JS syntax checks PASS. Source coverage findings for divergent earlier work and whole-business independent/performance acceptance remain unresolved. This is a partial integration, not the final globally accepted candidate.

Source-bound HK isolated TEST_PR requested through control-tasks #127 for GO #298. Five exact-head GitHub regression workflows are running. Neither a TEST_PR Request nor automatic CI establishes independent C14/C13 acceptance, final image admission, native app delivery or deployment. No CANARY/DEPLOY has been submitted for the old selected image.
