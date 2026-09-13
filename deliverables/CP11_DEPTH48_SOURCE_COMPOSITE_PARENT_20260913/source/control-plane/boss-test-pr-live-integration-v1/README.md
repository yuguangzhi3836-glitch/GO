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
