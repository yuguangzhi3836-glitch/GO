# Supplier-neutral durable controls candidate

This is a stacked candidate over PR #181 at
`cff423cf1a35b0e61081dc4f2f1cae54777c77da`. It does not move canonical main.

## Development acceptance

- SQL webhook replay claims use a compound provider/account scope + digest key
  and a single conditional upsert. Claims commit before success, and survive
  process recreation. Concurrent contenders cannot all accept one event.
- AES-256-GCM encrypts the entire raw attempt, including headers, URLs and bodies,
  before database insertion. Unique evidence IDs and random 96-bit nonces bind
  each ciphertext to its scope, record identity and key ID through authenticated
  additional data. No inline or derived default encryption key exists.
- Raw retrieval is an internal verifier API. Ordinary runtime receipts expose
  only an opaque reference and hashes, never the decrypted raw document.
- BOOK and CANCEL persist a mutation claim before sending. Completed attempts
  replay the prior safe result. PENDING claims never expire or auto-reclaim:
  crashes, storage failure and unknown outcomes require reconciliation.
- Changed payload or contract under one mutation key is rejected.
- HTTP 2xx must satisfy explicit response rules before business success. Rules
  are supplied from the provider's signed documentation, not inferred by GO.
- Single BOOK, a contract's webhook section, or a single QUERY never prove
  supplier idempotency, observed callbacks or reconciliation.
- Failed prerequisites stop the execution suite before subsequent HTTP calls.
- Endpoint and credential reference must equal the bound provider contract.

## Storage provisioning and authority

`supplier_runtime_controls.metadata` declares three isolated controls tables.
Constructors perform no DDL. The CI fixture provisions those tables explicitly in
a fresh isolated database. No global business models, Alembic history, live
database, cloud account or deployment service is changed.

Runtime adapters accept an explicitly supplied SQLAlchemy engine for PostgreSQL
or file-backed SQLite. In-memory SQLite is rejected. The reviewed deployment
integration must provision the tables and a dedicated account with DML privileges
only on the necessary tables; DDL privileges are not required at runtime. The
database must retain durable commit settings. Schema provisioning in a live
environment remains HOLD.

Account scope must include the tenant/provider/account/environment identity.
All workers for an account must use the same database and scope. UTC clocks must
be synchronized. Restore of old control databases could resurrect prior replay
windows or mutation state and requires operational review.

Encryption keys are 32-byte random values supplied through an approved secret
resolver; key IDs are public identifiers. Rotation supports an active write key
and prior decrypt-only keys. Retention, restricted verifier authorization,
backup encryption, external KMS access and key retirement require deployment
configuration and separate operational verification. Do not publish raw evidence
or keys in CI artifacts, logs or PRs. CI uses synthetic data and test-only keys.

No automatic mutation retry or reconciliation action may be inferred from a
PENDING record. This journal proves GO request deduplication, not supplier-side
idempotency, and cannot atomically commit across GO and a supplier.

## Acceptance boundary

The focused gate verifies SQLite and isolated PostgreSQL, multi-process
contention, restart, ciphertext tamper rejection, cross-account isolation, key
rotation, commit failure, crash/unknown deduplication, response rejection and
truthful suite results. Full source fingerprint and changed-file allowlist bind
the exact candidate while preserving unchanged PR #181 application bytes.

The old `ci/retention`, `ci/cell-closure`, and `ci/next-depth` manifests remain
historical bindings for their original candidates. This candidate uses
`ci/supplier-controls/CANDIDATE.json` plus its exact-head Evidence artifact;
historical PASS is not relabeled as a new full regression PASS.

Real supplier signing semantics, OAuth/mTLS transport integration, request
mapping, response rules, inventory authority and external end-to-end evidence
remain external contract work. Existing injection boundaries remain fail-closed.
This candidate is not a claim of all-module 100%, provider certification or
production readiness.

PRs remain Draft/unmerged. Hong Kong Staging, Final Release, Production, merge
and deployment remain HOLD.

