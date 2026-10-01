# Non-DOT HK release: live baseline observation

Owner instruction: 除DOT外，其他全部部署香港. Authorization is retained; no repeat approval is requested.

Formal read-only Request: https://github.com/chenzhenxi1-sudo/go-control-tasks/pull/125

Command Center published Task commit `743b2bfbc68dea46196790fae463fc854ceb5705`, task ID `go-boss-request-verify-20261001T022954Z-680077d3dc33`.

Evidence commit: https://github.com/chenzhenxi1-sudo/go-control-evidence/commit/8163118103aeb219aae4e9c2e14fb73e9d3af920

Completed 2026-10-01 10:31:29 Asia/Shanghai. Returned status SUCCESS / VERIFY_OK; API health, worker liveness, current/candidate image, Compose/environment and Alembic checks report PASS. `application_health_proven=false` remains explicit. This session read the Task and Evidence from the formal repositories and compared their task ID/nonce/environment/image bindings; it did not independently perform cryptographic verification of the Evidence signature.

Both Task and Evidence bind image `sha256:3652b1d6392ee8eed816bfa484872bfc443a95abbd36bcbca887c96975915cdf`, the older PR202 image. The currently selected candidate has therefore not advanced to the requested combined non-DOT release. Sending DEPLOY now would not establish deployment of all requested work.

No DEPLOY was submitted. The source-retention, performance and final-candidate independent review gaps in coverage.json remain unresolved. That file's PENDING field is its creation-time observation; this document records the subsequent verification result. No product source, main branch, runtime, migration, registration setting, DOT/new-host installation or Production setting was changed.
