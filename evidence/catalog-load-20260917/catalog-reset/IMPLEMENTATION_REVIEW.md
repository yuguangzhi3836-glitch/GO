# Protected catalog scope candidate

Base: `edd3500575d2f2b81298cc9273025e0a3b734897`. Source bindings: SOURCE_BINDING.json.

No remote mutations were made. No claim of completed cleanup, deployment or 1000-user acceptance.

The candidate appends `CATALOG_SCOPE_ACTIVATED` to the existing immutable event table. Scope contains the fixed two protected IDs plus existing Aoluguya-named profiles, exact archived IDs, retired discovery jobs/regional runs, and a SHA256 derived from profile versions, queue identities/states and event identities. API accepts the reviewed SHA256 only, never arbitrary protected IDs. Activation refuses missing protected profiles, fingerprint drift and all RUNNING regional tasks. Postgres advisory transaction locking serializes activation with catalog ingest/compose/publication and queue admission/claim. Original profiles, pages, snapshots, events and queued rows remain intact. Old queued rows are excluded from claims while active; no counterfeit completion receipt is emitted.

The active scope hides nonprotected catalog profiles from factory lists/detail/counts, AutoPage, contacts, discovery and regional history. Replayed retired jobs and runs fail admission. Seed/start admission requires Aoluguya; ingest still requires a matched existing protected profile, preventing in-flight work from creating new identities. Old Harbin physical-reset endpoint is blocked. Graph projection/read changes are independently supplied by C12 in ../c12-catalog-visibility.

A separate explicit `release(expected_sha256, actor, reason)` service function appends the rollback event. Releasing restores visibility and queue eligibility and must be reviewed before use. It is not called by activation and has no implicit fallback.

Verification: ten SQLite tests pass against real models/queue (local-tests.log), including protection, retained data, direct read hiding, queue replay fencing, active claim rejection, fingerprint drift, idempotence and release. Exact models/session/durable fetched and blob-verified; other test runtime dependencies originate from a prior local source tree. Therefore this is NOT full exact-candidate or PostgreSQL acceptance. Root/C13 must independently review the full integrated candidate, Postgres concurrency, permissions and UI projections before deployment or activation.

After deployment: stop/rule out active catalog writers, call preview, review protected identity closure and precise 112-row expected scope, activate exact returned SHA256, read back factory/discovery/regional/graph/mobile views. Aoluguya facts/media restoration and room completeness remain separate acceptance; empty media is not 100%.
