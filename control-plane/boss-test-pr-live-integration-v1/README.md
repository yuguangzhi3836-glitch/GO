# Installable HK_STAGING_TEST_PR V1 integration candidate

This candidate extends the archived, hash-pinned Command Center Bridge and HK Agent transport while retaining existing VERIFY flow. It is an install artifact only: no script runs automatically and this candidate must not be installed without a separate approved change.

## Boundaries

- The Boss Request contract accepts only pr_number for HK_STAGING_TEST_PR.
- Command Center resolves the mutable PR ref once using only the dedicated PR resolver, then signs the immutable SHA with the existing task signer.
- HK verifies that signature with the existing task verifier, fetches only that SHA with its separate source-reader key, and uses a fixed root-owned builder profile.
- The builder and test container have no network, host mounts, capabilities, or writable root filesystem. It does not call Compose.
- Evidence remains on the existing Agent signer/publisher path and explicitly reports application_health_proven=false and deployment_performed=false.

## Installation artifacts

install/preflight.sh verifies exact observed live artifact hashes before installation. The two install scripts require a staged candidate directory and fail closed if expected source, key metadata, or current artifact hash differs. uninstall.sh restores only an operator-provided, hash-verified artifact backup; it never reconstructs unknown server state.

## Candidate integrity gate

SHA256SUMS is generated from the canonical staged Git blobs, not from a
Windows working tree. The candidate-local .gitattributes requires LF for all
candidate files. Before staging to Linux, run:

    tests/check_canonical_archive_manifest.sh <exact-commit-sha>

The check creates a Git archive from that immutable commit, rejects CR bytes in
the manifest, and requires every manifest entry to validate after extraction.

No private key, token, or runtime configuration value is included.

## CC V1-02 — failure closure (this revision)

Before this revision a Task that was picked up and failed touched only the
agent-local SQLite ledger, so the control bus could not tell "never picked up"
from "picked up and failed".

`hk-staging/hk_agent/transport.py` now publishes a signed failure record for an
authenticated Task whose claimed execution attempt fails, to the same
`evidence/<task_id>-<nonce>.json` path a success record uses, signed by the same
evidence identity and bound to the original `task_id`, `nonce`, `action_id` and
`environment`. Its closed semantics are in
`../command-center-state-v1/contracts/failure_evidence_v1.schema.json`.

Load-bearing rules:

* A Task rejected **before** its attempt was claimed publishes nothing. A Task
  whose own signature never verified must never be able to cause a write.
* A failure record authorizes nothing: `retry_permitted`, `replay_authorized` and
  `authorizes_any_action` are always false, and the one-attempt rule lives in the
  agent ledger.
* A failed publication of a failure record is reported as
  `EVIDENCE_NOT_PUBLISHED`; it is not a success and it does not release the
  attempt budget.
* One Task identity has at most one Evidence record. A second record for the same
  `task_id` and `nonce` is refused rather than overwritten.

### Superseded artifact hashes

This revision changes two files that are hash-pinned by `SHA256SUMS` and, for
`transport.py`, by `install/install-hk-agent.sh`:

```
hk-staging/hk_agent/transport.py        was 550eecc865c71896e3c26be4707d544b0bc25a30b6db7e11c21296e5c682db84
                                        now 6f329b2eae7bc627229002e998cf17ee9d95b2e1fb6fc7cb22a508b52ad5fbe0
tests/test_live_integration.py          was d0fd9e52aafd6041b3985ddc79217c5b3506b4c745265eb348d58d4c17bf3a1f
                                        now c4413d17f29d93f51166494e5ebd49b4482556c77ca6d91b8997b087502d87db
```

```
INSTALLATION_PERFORMED=NO
DEPLOYMENT_PERFORMED=NO
HONG_KONG_TOUCHED=NO
```

`install/preflight.sh` still pins the pre-PR50 live `transport.py` hash
(`4301a7e9…`) as its `preinstall` gate. That gate was written for the PR50
installation and is not re-pinned here: re-pinning it asserts a claim about the
live host that this revision cannot verify. It must be re-pinned, against
observed live state, by whichever separately approved change installs this
revision.
