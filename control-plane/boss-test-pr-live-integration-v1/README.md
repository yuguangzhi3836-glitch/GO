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
hk-staging/hk_agent/transport.py        was 6f329b2eae7bc627229002e998cf17ee9d95b2e1fb6fc7cb22a508b52ad5fbe0
                                        now 340da98f95acdb0c212aa116681da8d8344c6da306e44dfcf332c67ee1957de8
tests/test_live_integration.py          was f59626419ba5d8da2b8430e1e1b3293d197cf19cc8d704a1fe842c982100e2fd
                                        now d80ea8ce98afdf1cd9bc302d3d611b6e84d56ff07ca79f0f56b853e1730e07d1
```

The previous revision recorded `c4413d17…` for `tests/test_live_integration.py`;
the value actually committed was `f5962641…`. The `was` value above is the
committed one.

## TD-J — one clone workspace per publication (this revision)

`run_once` publishes every Task it claims inside one pass and one temporary work
root, and every publication used to clone into a fixed `work/<dirname>`. `git
clone` refuses a destination that already holds a work tree, so the **second**
publication of a pass failed and was reported as `GITHUB_TRANSPORT_REJECT` at
stage `evidence_publish` — although its Task had in fact executed and succeeded.

On 2026-09-16 a fresh, successful VERIFY lost its Evidence exactly that way:
`go-boss-health-…` sorts before `go-boss-request-verify-…`, so the liveness record
of the same pass was published first and the VERIFY record had nowhere to land.
`push_evidence` now publishes from a workspace derived from the record's own
identity, so one pass can publish any number of records.

Load-bearing rules:

* What is published is unchanged: the repository, the branch, the
  `evidence/<task_id>-<nonce>.json` durable identity, the payload, the signature,
  the signer, the Task ordering, the ledger and the one-attempt rule.
* The workspace name is a hash of the record identity, so no Task-supplied string
  becomes a path component.
* Success and failure records each get their own workspace, so a failure record
  can still be published in a pass that also published successes.

```
INSTALLATION_PERFORMED=NO
DEPLOYMENT_PERFORMED=NO
HONG_KONG_TOUCHED=NO
```

The live host still runs `6f329b2e…`, the hash pinned above as `was`.

`install/preflight.sh` still pins the pre-PR50 live `transport.py` hash
(`4301a7e9…`) as its `preinstall` gate. That gate was written for the PR50
installation and is not re-pinned here: re-pinning it asserts a claim about the
live host that this revision cannot verify. It must be re-pinned, against
observed live state, by whichever separately approved change installs this
revision.
