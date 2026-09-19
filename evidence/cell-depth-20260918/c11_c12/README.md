# C11 / C12 scoped development evidence

This candidate closes six existing-contract gaps in payment request authority, callback replay binding, external identity ownership, and refresh-token single use. It creates no new money source of truth, schema, live PSP integration or infrastructure.

- Source commit: `5b8d2b82ac02cafdb4146d8ea033103ba984096d` (five explicit source/test paths).
- Reproduction: 28 tests, 27 failures and 1 pass on the unchanged local source baseline.
- Focused post-fix run: 28 passes.
- Final verification: 119 passes, zero failures/errors/skips. Includes 29 new cases and existing payment, real HTTP booking/payment, flight-recovery, refresh-end-scope and GET-zero-write contracts.
- Existing server-created obligations and existing provider/subject SSO bindings remain supported. Local-account linking based only on a mutable upstream username is rejected.

`verification.log` and `verification.xml` are the final raw local-run evidence. `reproduction.*` preserves the failure run; any displayed authentication tokens are ephemeral synthetic local-test outputs, never real IdP or production credentials. The final concurrency assertion was adjusted to avoid rendering such token values. Test timestamps include the runner timezone as emitted by pytest.

The local ancestor contains a parent-identified media-cache artifact; that artifact is not included in the five-file change. Parent integration is responsible for the clean application tree and independent source binding. This evidence does not transfer a scoped verdict to that later tree.

PostgreSQL concurrency, real configured IdP/PSP proof, durable issuer identity migration, independent C14/C13, and remote publication remain unfinished. No GitHub write, merge, deployment or live-money operation was attempted. `STATUS.json` records next tasks and exact file digests.
