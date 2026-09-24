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
