# DEPTH36R3 mobile release contract correction

Run 34451882079 exposed an assertion previously masked by missing historical release files. The old Sprint 2B test searched client.ts for NETWORK_OFFLINE_RETRY_REQUIRED and Idempotency-Key. Current client.ts delegates to shared transport.ts, which rejects offline requests with NETWORK_OFFLINE and owns idempotency headers.

This revision changes only the existing mobile release test. It verifies the adapter delegates to the shared implementation, executes that implementation with injected dependencies, proves an offline financial mutation never reaches fetch, checks reconnecting does not replay it, and verifies caller-supplied and generated idempotency keys plus request body preservation. It keeps the release-file and real-device checklist assertions. No test is deleted or skipped, and no business/runtime source is changed.

The local targeted check passed with Node 24.19.0. This is development evidence only; authoritative isolated CI must re-run the complete candidate with the established Node 22.22.0 and Python 3.13.5 contract. All 19 inherited support files and their provenance remain unchanged in the DEPTH36R2 parent package. Full release remains HOLD.
