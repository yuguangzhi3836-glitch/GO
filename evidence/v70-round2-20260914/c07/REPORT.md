# C07 Round 2 execution evidence

- Source anchor: `main fef9c748adb77d37ba5d4dc4fa4662eb668303a1`.
- Executor task: clear the durable-preference P0 placeholder without inventing C09 judgment truth.
- Executor result: `EVIDENCE_READY` (4/6: gap → task → test → Evidence complete; C14 and C13 await independent review and acceptance). This is not DONE-SCOPED, whole-Cell 100%, a release PASS, a PostgreSQL PASS, a merge or deployment result.
- Frozen changed-file manifest SHA256: `d76f0fc3af0e2e8270f045be32a3d161d12979c50f859036bc0564045d9246fb` (canonical JSON encoding of the `files` list in `source-manifest.json`).

## Gap → implementation

The internal preference route returned `P0_EMPTY_PURPOSE_BOUND`; the graph always returned an empty `durable_preferences` list and released identity/session context for any nonempty purpose. The former could not retain an explicitly chosen preference. The latter checked a purpose string without checking a corresponding grant.

The new preference mixin reuses existing encrypted `ProfileFactRow`, `ProfileConsentRow` and `ProfileAccessAuditRow` tables. It does not change database models, migrations, dependencies, service topology or C09 code.

Only the authenticated owner of an ACTIVE SELF traveler may save a preference, with EDIT permission and strict explicit confirmation. Reads require VIEW permission. A finite, currently active `EXPLICIT_TRAVEL_PREFERENCE` consent must match owner, traveler, exact purpose and the exact `TRAVEL_PREFERENCE:<key>` scope. Missing expiry, future start, expiry, revocation timestamp, revoked status, wildcard scope, wrong owner, wrong traveler, wrong type or wrong scope cannot authorize a preference. The consent is checked on every read and write. A later grant cannot revive a fact bound to a revoked earlier consent.

Preference keys are limited to HOTEL_ROOM, FLIGHT_SEAT, RAIL_SEAT, DIETARY, ACCESSIBILITY, TRAVEL_PACE and RENTAL_VEHICLE. GO scores, verdicts and commercial boosts are not accepted preference keys. Values are encrypted at rest and never copied to audit metadata. Session intents and behavior never write a durable preference.

Saving the same preference/consent/value is idempotent. A changed value requires `expected_preference_id`; competing first writes produce one revision and one conflict in the tested SQLite runtime. Deletion targets one immutable preference ID and cannot withdraw a subsequent revision. Explicit withdrawal marks that record REVOKED and erases its reusable ciphertext. Existing vault consent withdrawal immediately excludes the preference from both preference and graph projections.

Graph identity/intents/behavior require their own finite `TRAVELER_CONTEXT` consent with TRAVELER_IDENTITY, TRAVEL_INTENTS or TRAVEL_BEHAVIOR scope respectively. Intents must additionally include the requested purpose in their consent scope; events must carry that purpose. Missing authorization returns empty corresponding projections. Previously passed C07→C09 evidence-only and judgment-denial behavior is retained.

## API ownership and contract

These paths are in the existing C07 `travel_intelligence` router under the central integration assignment; they do not grant C07 authority over another Cell's public API or truth.

| Method and route | Principal and behavior |
| --- | --- |
| PUT `/v1/consumer/travelers/{traveler_id}/preferences/{preference_key}` | Consumer owner only. Body: value, purpose, consent_id, confirmed=true, optional expected_preference_id. |
| GET `/v1/consumer/travelers/{traveler_id}/preferences?purpose=…` | Consumer owner only; current purpose-bound projection. |
| DELETE `/v1/consumer/travelers/{traveler_id}/preferences/{preference_id}` | Consumer owner only; immutable ID selects the revision to withdraw. |
| GET `/internal/v1/travelers/{traveler_id}/preferences?purpose=…` | Existing GO_ADMIN read entry; administrator status does not bypass current consent or VIEW. |
| GET `/internal/v1/travelers/{traveler_id}/graph?purpose=…` | Existing GO_ADMIN read entry; independent context scopes plus the same preference filter. |

All five endpoints send `Cache-Control: no-store, private` and `Pragma: no-cache`. The existing owner-only `/v1/consumer/profile/consents` creates and withdraws grants; its broad sensitive-data release logic is not reused for these preferences.

## Test → evidence

`commands.json` records exact commands, isolated database paths and process exit results; `source-manifest.json` records file hashes and interpreter/library versions.

1. The original interpreter path was unavailable: exit 127, preserved in `red-environment-failure.log`. This is an environment failure, not a product test.
2. Baseline red: 19 failures, exit 1, preserved in `red.log`. Missing preference service methods and HTTP route 404 exposed the original gap. The suite was then expanded; later cases were not retrospectively claimed as baseline red.
3. First green: 30 passed, exit 0, preserved in `green-attempt1.log`.
4. Final green: **51 passed, 0 failed, 0 skipped**, exit 0, 7.60 seconds, preserved in `green-final.log`. It includes explicit persistence after engine reopen, encrypted storage, exact purpose, ten live consent invalidation cases, session non-promotion, independent graph scopes, retry/update/stale deletion, vault consent withdrawal, strict confirmation, owner/SELF/EDIT/VIEW boundaries, parallel writes, C09 key rejection, invalid payload/audit exclusion, authenticated HTTP grant/save/read/admin-read/revoke, rejected admin writes, no-store headers and prior vault/C07/C09/hotel-infrastructure regressions.

There are two pre-existing framework deprecation warnings concerning TestClient/httpx and AnyIO; they are retained in raw output. Dependencies were not changed.

## Gate boundary and next depth task

C07 does not self-sign C14 or C13. Independent review/acceptance must bind these frozen changed files and raw evidence. The root integrator must bind the combined candidate separately.

All runtime evidence here is local isolated SQLite with synthetic identities. Engine reopen demonstrates persistence across connections, not a separate operating-system process or server restart. No live provider, Hong Kong, PostgreSQL or browser session was used. HTTP evidence is authenticated FastAPI TestClient execution, not a rendered browser journey.

Next task: bind the integrated candidate to an isolated PostgreSQL runtime and verify preference update versus consent withdrawal concurrency, two writers, restart persistence and no post-withdrawal release. Preserve this scoped PASS evidence. PostgreSQL execution remains an open runtime scope until the central dispatcher provides an executable isolated environment; no theoretical SQL locking claim is counted as a PostgreSQL PASS.
