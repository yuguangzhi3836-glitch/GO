# DEPTH40 upgrade and recovery supplement

This supplement validates the already sealed eight-service image on PostgreSQL
18.4. It does not rebuild an image, change candidate source, or authorize any
Hong Kong operation. Its fixture databases, media bytes and backups are synthetic.
Existing PG16 fresh-install evidence remains preserved with its original scope.

## Fixed inputs and evidence

`identity.py` fixes the parent artifact, full source archive, source tree, runtime
artifact 10186084217 from run 34565938702, image archive and config Image ID.
The download is checked against the previously sealed SHA256SUMS digest before
executing the pinned integrity verifier. The existing image is loaded only on
the disposable GitHub runner. No Registry push or image rebuild occurs.

The workflow records the actual PostgreSQL 18.4 fixture image digest and server
version. It uses the candidate's unmodified Alembic history to create an 0114
test database. This is not a live schema clone: an Alembic head alone cannot
prove equivalence to a database with historical operational changes.

Checks cover synthetic legacy rail/refund/outbox records, every original table's
row content, column definitions, indexes, constraints, triggers, functions and
sequence state. The experiment injects a lock timeout and terminates the
migration connection while the final width alteration is blocked. Each failure
must leave the complete fixture at its original 0114 state. A successful upgrade
must preserve existing column values, widen the critical fields, and make a
second upgrade a no-op. An unsafe 0132 downgrade must refuse to truncate data.

The backup uses PostgreSQL 18 `pg_dump -Fc`; recovery uses `pg_restore
--exit-on-error --single-transaction` into a separately created empty fixture
database. The upgraded database must remain intact. A successful synthetic
restore is not evidence that a live backup or old runtime has been restored.

## Proposed operational database sequence — execution HOLD

1. Bind a fresh schema inventory, database identity, extensions, roles/grants,
   exact 0114 head, table/column definitions and migration file hashes. Compare
   the actual schema to the candidate migration requirements; reject unresolved
   drift. Never use `stamp` or a direct Alembic marker update as a repair.
2. Before a write window, prepare a recoverable backup and demonstrate a restore
   on an approved separate target with the necessary extension and role mapping.
   Database size is not a measurement of dump size or temporary peak disk use.
   A single-database dump does not contain cluster-level roles/tablespaces.
3. Obtain explicit scope for a write fence covering all API, worker, callback,
   scheduled and other writers to the affected database/media. The fence must
   be enforceable through approved operations. Stop if shared external writers
   cannot be controlled. Keep Redis and Caddy configuration unchanged.
4. Under that fence, create the final consistent database/media/config snapshot,
   record complete SHA256 values, actual sizes, timing, image identity and prior
   state. Retain the previous media container layer until its data is recovered.
   No runtime credentials, backups or personal records are uploaded to GitHub.
5. Only an explicitly approved migration action may execute the fixed sequence
   0115 through 0132. The CI uses session lock_timeout=2000ms and
   statement_timeout=60000ms. Live thresholds must be selected using the approved
   clone rehearsal and write-window budget; never set server-wide defaults or
   silently increase a timeout after failure. Any error ends the attempt.
6. After a failure, independently read the head/schema/data before deciding the
   recovery route. Do not assume transactional rollback from an exit code alone.
   If old state is intact, validate the old runtime before lifting the fence.
   If not intact, use the verified backup restore procedure and authorized
   target mapping; never restore over a running/shared database.
7. After migration success, validate 0132, required columns, widths, preserved
   records and permissions before application start. Keep test traffic free of
   production payments and suppliers. Bind image → container → runtime only
   after actual execution. The config Image ID is distinct from RepoDigest.
8. If runtime checks fail after migration, keep writers fenced. Reverting only
   the image is not a proven rollback. Use a tested schema-compatible previous
   runtime or the coordinated database/media restore. An unsafe downgrade is
   forbidden; post-snapshot writes require reconciliation, not silent loss.

## Media conservation and mapping — execution HOLD

The candidate `MediaIndex` can import version-1 `index.json` exactly once,
record its SHA256, and preserve the JSON file. The delivered startup preflight
requires an existing schema-1 SQLite index. Therefore conversion must be a
separate approved preparation action on a copy, before starting the candidate.

Inventory the real legacy directory and every referenced file, including orphan
files. Preserve original bytes, ownership and permissions in a stable backup.
Do not infer an empty library from a short directory listing or directory inode
size. Malformed indexes, missing files, hash mismatches, special files, symlinks
or paths escaping the media directory must stop preparation. An intentionally
empty inventory requires a specific content decision and is not media completion.

Import only a verified copy to a new, explicitly named durable volume. Preserve
rights history without promoting publication status. Compare source and copied
file SHA256 values and imported asset IDs/records. Run SQLite integrity_check,
record schema and legacy digest, repeat-open without duplicate import, and test
SQLite backup plus file recovery. Prepare only the new copy for UID/GID 10001;
do not recursively change the legacy source or unrelated paths. The application
mapping is GO_MEDIA_CACHE_DIR=/state/media with the bound volume mounted at
/state. GO_VERIFIED_MEDIA_VOLUME is an executor/Compose input, not an app secret.

`media_exercise.py` demonstrates these checks using synthetic CI media only.
It is intentionally guarded and is not an operational media conversion tool.

## Configuration, capacity and executor requirements

Keep existing credential values in the approved secret store; record names only.
Bind DATABASE_URL and REDIS_URL to the reviewed targets. COOKIE_SECURE must stay
true for HTTPS. Confirm the administrator MFA policy and account enrollment
before changing MFA_REQUIRED_FOR_ADMIN. CI values are not Staging policy.

During the proposed maintenance window, both reservation-expiry switches must
be explicitly off while writers are fenced. Their subsequent operating values
and activation time need separate review, including background tasks inside the
API process. Do not assume that disabling the seven worker containers covers
all writers. Regional building remains locked. Confirm the review Compose
non-root/read-only-rootfs, PID, memory, volume and network contract with the actual
executor; merely hashing a review file does not bind it to a running container.

Capacity must account for already resident bytes and each operation's additional
peak: retained/downloaded ZIPs and parts, recombined archive, expanded image
layers, old rollback image, database/media backup copies, restore scratch or
replica storage, imported media/index, log caps and free-space reserve. Do not
count data twice as both resident and incremental, or use an optimistic compression
ratio. RAM review must include old/new overlap, restore clients, API, workers,
Redis, Caddy and OS. Never reclaim existing Staging data to satisfy the estimate.

Two image transport designs are possible, neither currently implemented by this
supplement: push the exact sealed image to an approved Registry and bind its
actual RepoDigest plus config ID, or approve a dedicated offline executor contract
binding archive SHA256 and config ID. Do not fake RepoDigest, override a required
digest check, or invoke shell/sudo to bypass the signed execution path.

The current documented deployment contract excludes migration and automatic
rollback. A combined upgrade therefore requires separately reviewed operations,
an installed and verified executor, fresh signed tasks with unique nonces,
durable previous-state records, and signed execution evidence. This supplement
contains no signing key, signature, active task or asserted live executor path.

## Remaining live gates

Actual schema-clone rehearsal; real media snapshot/import; configuration and
policy binding; measured full backup and successful restore; peak capacity;
Registry/offline executor agreement; installed execution route; fresh approved
migration/deployment/recovery tasks; runtime and HTTPS evidence all remain HOLD
until their respective evidence exists. Three-end real browser and six-vertical
E2E remain NOT_RUN. Physical iPhone and final Production release remain HOLD.

Reference contracts:
- [PostgreSQL 18 pg_dump](https://www.postgresql.org/docs/18/app-pgdump.html)
- [PostgreSQL 18 pg_restore](https://www.postgresql.org/docs/18/app-pgrestore.html)
- [PostgreSQL 18 session timeout settings](https://www.postgresql.org/docs/18/runtime-config-client.html)
- [Existing HK runbook](../../docs/control-plane/hk-staging/HK_STAGING_DEPLOY_RUNBOOK.md)
