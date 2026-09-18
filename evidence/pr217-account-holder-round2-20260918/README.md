# PR217 second-round recovery and verification

The local second-round work was recovered onto the exact PR217 parent 1d1b6b45a5e6e3507bda8c4f3d9ca7b7c8e7175c. Older local copies were not uploaded wholesale. Existing flight recovery, read-only authentication, GO AI execution and hosted-money models, and historical migration checks were preserved.

Changes: durable supplier import authorization and atomic idempotency; consumer authorization state expiry/consumption and explicit preview; scoped connector administration; fresh same-basis member quote validation; account-scoped external-order projection and provider servicing links; media rights checks; supplier registration through the existing terms-aware BFF; migration 0138_supplier_library_import follows 0137_hosted_unknown_episode and refuses to erase populated import history.

Review found and fixed missing keyword forwarding in the external-order HTTP wrapper, unsafe comparison links, and a property-creation media gate gap. Synthetic HTTP roundtrips cover user imports, connector projection/replay, tenant isolation and BFF registration.

Validation: 129 tests passed with no skips or failures; compileall, one Alembic head and mobile contract checks passed. SOURCE_BINDING.json identifies the exact application tree and original logs. These are new local results, not the screenshot's historical 73+11 claims.

Limits: SQLite is the database used here. PostgreSQL execution, real OTA adapters/member prices, physical-device/browser interaction, independent C14/C13 and hosted isolated CI remain unverified. The work updates a Draft PR only; no merge, HK deployment or Production operation is included.
