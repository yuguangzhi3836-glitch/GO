# Issue 103: candidate-bound forward migration

This shared repair extends the installed PR179 control chain and retains the
PR185 TEST_PR compatibility/failure fixes. PR183 product bytes are unchanged.
It is a source candidate; CI success does not install or deploy anything.

The Boss Request remains its existing five fields. A root-owned, independently
verified admission record selects a content-addressed candidate contract. CC
joins its source, application tree/fingerprint, original TEST_PR Evidence,
sealed image/package, PostgreSQL rehearsal and fresh current-image proofs.
The signed CANARY/DEPLOY/VERIFY Task adds only `candidate_contract_sha256`.
No Request may supply an image, revision, SQL, work directory or command.

CANARY verifies the sealed candidate's migration source and single target head
under `/workspace`, without networking. DEPLOY records previous state, persists
an exclusive migration intent, checks the actual DB prestate, runs only the
same candidate's Alembic forward path, re-reads the target head and cuts over
the fixed eight services. Both in-action and automatic independent VERIFY use
that same contract's `/workspace` and target head. Legacy image-only actions
keep `/app` and their original fixed head.

A failed, interrupted or uncertain migration leaves an environment-wide fence.
A new Task/nonce cannot bypass it. No automatic retry, downgrade or reset is
implemented. The fence is retired only after the entire cutover/VERIFY succeeds;
the immutable intent and result remain. Rollback of a migrated deployment is
refused until old-image/new-schema compatibility has its own proof. Protected
`caddy`/`redis` services and the fixed deployment topology are unchanged.

The candidate contract is a set of verified facts, not approval. DEPLOY still
requires the authenticated one-use Request, fresh CANARY/VERIFY and Signed Task.
The operator admission artifact cannot change channel policy, services or SQL.
Normal deployment plans remain CC-derived; none are manually written.

Before installation, independent C14 then C13 must review the exact repair SHA,
the CI artifact/source binding, manifests and migration failure behavior. A
controlled installation must compare fresh installed hashes, back up exact
bytes, wait for idle services, install atomically and restore timers. It must
retain PR185 on HK and PR179 post-action VERIFY on CC. No old installer with
superseded hashes may be used. The currently selected product candidate remains
PR183 `edd3500575d2f2b81298cc9273025e0a3b734897`.

The user has authorized conditional HK-STAGING deployment once these conditions
are proven. This source change grants no Production, Final Release, real supplier
certification/connection or merge permission. External connections remain off.

Validation: the focused workflow uses disposable PostgreSQL 18.4 and an isolated
container built from exact PR183 source with inherited frozen dependencies. It
executes the actual fixed migration program, checks retained data and indexes,
and rejects both a repeat from the wrong prestate and substituted lineage.
It does not rerun the accepted Cell suites or contact the live database.
