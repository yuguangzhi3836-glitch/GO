# C13 developer-side first test, then isolated Hong Kong C14

The Owner's sequence is: freeze candidate SHA / `application/` tree / scope;
independent C13 runs the first formal tests **on the development side**;
Command Center verifies the C13 source-bound evidence; only then may it
issue a restricted Hong Kong isolated C14 retest for the exact same identity.
Neither test result authorizes release.

C13 requires a frozen development-side CI job and independent acceptance
review. It does **not** require installing a Hong Kong Runner, changing the
live Command Center task contract, or writing a `go-control-tasks` Task.
`acceptance_gate.c13_admission` is a source-only development-side check.

`house_bridge.py` handles **C14 only**. It explicitly rejects C13 on the
house task bus. Before C14 issuance, the host must independently re-read and
verify the C13 PASS evidence. A host with the existing Command Center trust
root must sign the house Task V1 envelope, publish exact bytes, and read them
back. The C14 result reader checks the independent Hong Kong Runner signature,
Task ID/nonce, source and scope, raw JUnit/stdout/manifest SHA-256, and test
counts. Only after every one of those checks may the Command Center — never
the Hong Kong Runner — atomically create and read back a signed
GO_C14_EVIDENCE_RECEIPT_V1 record. It binds the exact Evidence bytes, the
three raw artifact digests, candidate SHA/tree, C13 digest, Runner and verdict.
An exact repeat is idempotent; a missing, altered or mismatched receipt is
refused and remains HOLD. COMPLETE on that receipt means only that the Command
Center recorded the verified outcome; it is not a PASS or release permission.
The source-only tests use a memory host and synthetic signatures.

`task_v1.acceptance.proposed.json` and
`evidence_v1.acceptance.proposed.json` add only the isolated C14 action and
environment, preserving all six existing Hong Kong actions in `HK-STAGING-01`.
`receipt_v1.acceptance.proposed.json` defines the Command Center-only direct
return receipt; the Hong Kong Runner has no permission to write it.
The old `task_evidence.py` internal envelope was an abandoned prototype and
must not enter the real bus. It is removed from the Draft candidate.

Run source checks with:

```sh
python -m unittest discover -s control-plane/c13-c14-v2 -p 'test_*.py' -v
```

These contracts and the Hong Kong C14 executor are **not installed**. C13
can begin through development-side CI independently of them. C14 cannot be
claimed until the separate Hong Kong Runner, task/evidence bus, signing,
Command Center receipt route/readback and scope matching are shown by actual
execution. All PRs remain Draft, with merge and deployment on HOLD.

## 2026-09-24 source candidate added (still HOLD)

`c13_attestation.py` freezes #240 commit/tree/scope and GitHub Actions artifact 10805227694 (ZIP SHA-256 `44b1dca3444296ff4f9ad52c323c3bb325ca3d143efb022b6785ac07047ad777`). It checks all 71 payload digests, JUnit 61/61, isolated PostgreSQL 18.4 recovery 10/10, then requires a **registered independent reviewer** P-256 signature over an exact verdict record and an independently supplied public key. No project reviewer private key, signed C13 verdict or Command Center registration is present in this Draft. A synthetic test signature must never be published as a real verdict.

`c14_isolated_runner.py` is a source-bound runner core. Its host must provide a persistent single-use Task claim, verify the Command Center signature and Task readback, perform an offline checkout of the fixed source, run only the frozen suite inside a disposable PostgreSQL 18.4 sandbox with suppliers, payments, deployment, production and outbound network disabled, sign Evidence with the separately registered Hong Kong Runner key, and atomically publish raw artifacts then Evidence. The core alone is not an installed host adapter or sandbox. The installed Agent/Bridge allowlists and evidence storage must be extended through controlled installation and readback against the live versions including the #245 repair.

The C14 Command Center receipt contract now uses **HSM P-256 ECDSA SHA-256, base64 DER**. Its trusted public key and fingerprint are host configuration, never repository data. This does not change the existing Ed25519 Command Center Task / Hong Kong Evidence wire signatures.

Installation gates: independent C13 signer registration and signed verdict; Command Center C13 verifier registration; HK isolated Runner and disposable PostgreSQL sandbox; action/environment allowlists; Command Center-only receipt destination with HSM signing and readback; exact live artifact hash check and independent operator review. Do not submit an `HK_ISOLATED_C14_RETEST` Request or claim C14 PASS until each gate has live evidence. Existing `HK_STAGING_TEST_PR` is a separate source preflight.

## AI reviewer identity and persistent claims (development increment)

C13 is the **development-side independent AI review group**. C14 is the
**runtime-side independent AI review group**. Neither is a human review group.
GitHub account names do not establish independence. Controlled installation
is a separate operation, not an additional human C13/C14 reviewer role.

`ai_acceptance_host.AIAdmissionHost` implements the admission Host interface.
The installer supplies trusted `AIRegistration` snapshots, the implementation
principal, the exact artifact ZIP and an absolute host-owned verdict directory.
No Request/verdict/candidate file may supply these trust inputs. The host must
establish actual execution/credential separation and revocation; different
strings alone are not proof of independent AI groups. C13 binds a development
AI principal and P-256 SPKI fingerprint; C14 binds a different runtime AI
principal and Ed25519 evidence key. C13 qualification works without C14 being
registered. Nothing here creates a key, registers a real group or runs an AI.

C13 references have the exact form `sha256:<digest>`. The reader opens
`<digest>.json` from the host directory, rejects links/non-regular files and
digest changes, then invokes the existing artifact and P-256 verifier. The
digest covers canonical signed verdict bytes including the trailing LF, not
an unsigned body or a GitHub comment. Keep the directory and its parent chain
outside candidate workspaces and writable only by the trusted evidence writer.

`durable_claims.DurableClaims` implements `claim_task_once(task_id, nonce)`
using a local SQLite transaction with unique Task and nonce constraints and
FULL synchronization. A controlled installer explicitly provisions a new
store in a private (0700) persistent directory owned by the service UID. The
store is 0600 and bound to one Runner ID. Runtime opens existing state only;
missing/corrupt state fails closed. Bind this method into the installed Runner
host so the existing `execute()` checks authority/readback before claiming and
claims before sandbox work. A sandbox crash does not release a claim. Recovery
must never restore an older claims database or silently provision an empty one;
storage rollback requires reconciliation against the authoritative task ledger.
Use a local filesystem with SQLite/fsync guarantees, not ephemeral or network
storage. This does not yet implement Request-level deduplication at the CC.

Validation includes real local multiprocess contention, abrupt process exit,
reopened-state replay rejection, and synthetic-signature adapter tests. Those
tests are source checks, never formal C13/C14 acceptance. No live registration,
sandbox, HSM connector, bus wiring or installation is supplied by this increment.

Change classes: CONTROL_PLANE, TEST_ONLY, DOCUMENTATION. Development parent is
`8322a5c81200d2181998f472c89a5cc472cfaeba`; that immutable review baseline remains
valid historically. This increment is a new Draft candidate, not permission
to install a moving PR head. Freeze a complete installation commit and manifest
separately before any fetch/install/readback operation.

## Command Center HSM receipt implementation (not installed)

`kms_receipts.KmsReceiptSigner` implements the Google Cloud KMS signing and
verification methods used by `house_bridge`. The installed CC supplies an
authenticated official `google.cloud.kms_v1.KeyManagementServiceClient`, a
numeric CryptoKeyVersion resource and an independently registered SHA-256 SPKI
fingerprint. The library does not discover credentials, select a key, create
keys, change IAM or use a software signing fallback. The runtime SDK dependency
is `google-cloud-kms`; the offline contract tests do not require credentials or
that dependency. The installer must pin its reviewed dependency versions.
Local compatibility was also checked with official `google-cloud-kms==3.17.0`
request/response protobuf types and fake transport (no cloud calls).

Before signing, the adapter validates the exact canonical C14 receipt schema
and frozen source, reads the configured public key, verifies its version,
P-256 algorithm, HSM protection level, CRC32C and fingerprint. It sends SHA-256
with its CRC32C, checks the returned version/HSM/verified-digest/checksum, then
cryptographically verifies the DER signature before returning base64 DER.
Timeouts, denied access, changed fingerprints, wrong keys and integrity failures
remain HOLD. No real cloud signing call is performed by these source tests.

`control_receipt_route.ControlReceiptRoute` composes that signer with
`ReceiptStore`. Bind its four methods (`sign_control_receipt`,
`verify_control_receipt`, `publish_control_receipt`, `read_control_receipt`) into
the CC host used by `house_bridge.receive_evidence`. The receipt directory must
already exist on persistent local storage, mode 0700, under the CC service UID,
with a trusted ancestor chain; HK has no write access or KMS signing credential.
Receipt files are mode 0600. Publication fsyncs a temporary file, atomically
links without overwriting, fsyncs the directory, and reads back exact bytes.
An identical record is idempotent; a conflicting record is refused. A verified
existing receipt is reused without another signing request. A crash before
publication may leave a `.pending-*` file: it is never a receipt and must not be
promoted automatically. Reconcile it against verified evidence before cleanup.

These modules now provide actual adapter/storage implementations, but do not
wire or install the CC service. The installer still has to bind real workload
identity, key-version/fingerprint trust, CC-only storage and the house bus.
The AI groups, HK sandbox and controlled installation readback remain separate
prerequisites. Source tests use ephemeral test keys and fake KMS transport;
they cannot produce formal C13 or C14 PASS.

API references checked 2026-09-25:
- https://cloud.google.com/kms/docs/reference/rest/v1/projects.locations.keyRings.cryptoKeys.cryptoKeyVersions/getPublicKey
- https://cloud.google.com/kms/docs/reference/rest/v1/projects.locations.keyRings.cryptoKeys.cryptoKeyVersions/asymmetricSign
