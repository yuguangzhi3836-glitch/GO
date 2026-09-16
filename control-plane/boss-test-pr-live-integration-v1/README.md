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

This revision adds `hk-staging/hk_agent/artifact_store.py`, makes `test_pr.py`
seal the image it built, and re-contracts the candidate delivery identity
(`candidate_repo_digest` → `candidate_package_sha256`). Files hash-pinned by
`SHA256SUMS`, and for the agent tree by `install/install-hk-agent.sh`:

```
hk-staging/hk_agent/transport.py        was 340da98f95acdb0c212aa116681da8d8344c6da306e44dfcf332c67ee1957de8
                                        now b35ace2289d9b8e64805d584a893f0e3c5efb7c6050fbbdbfaaf492dee3d700d
hk-staging/hk_agent/test_pr.py          was 654403023d599b78ec2a61776ab133ec0dc46d069e61fd7b3717d400eaedc2ac
                                        now 5247882993a86fada07df256f256b74ad6aa42f2e9fc7b3427192bd3e4cad778
hk-staging/hk_agent/artifact_store.py   new d5b182b693d2f6be469a2f2dbb9ced7299db00074f1b3d1c64ee4cc9515e8c76
tests/test_live_integration.py          was d80ea8ce98afdf1cd9bc302d3d611b6e84d56ff07ca79f0f56b853e1730e07d1
                                        now 67af7de8f26e214ab1d05575e8564f0a504b647b6252f988f38f8f232683826c
tests/test_artifact_store.py            new c684bd5298012823d3047e3ad524a8537df1072953b22790cd1bfaf4b0cb5c29
tests/test_test_pr_durability.py        new c16a057421cc17f88e834e7ad586f6cb4da19412e1c04a9e0d33bf0291ae51cb
install/install-hk-agent.sh             was 1a5779b3619ff004204abf22fefd7c98368accf3ef563a1248dacf6bf5419f33
                                        now a70c797e5a8cc3436e06681b0368959cae05b5f7f51152b3bef1861605fae245
install/uninstall.sh                    was 0754ea416521670ee3316169d785f4e9c0c31c767451f9d0f2036d40e4b59d7d
                                        now 0d06812e8fc115a707bf12a10fb7bc4947f8aecb0b888665d86b7b2b9ef42268
```

The previous revision recorded `c4413d17…` for `tests/test_live_integration.py`
and `550eecc8…` for `test_pr.py`; the values actually committed were `f5962641…`
and `65440302…`. Each `was` above is the committed value.

### B4-B1.1 superseded hashes — the store's ownership contract across two uids

The store has exactly one trusted author, and it is not the reader. The agent
writes it (systemd `User=go-hk-agent` / `Group=go-hk-agent`) while root only reads
it, through `sudo -n /usr/local/libexec/go-hk-deployctl`. Both halves used to
compare an object's owner with the reading process's own effective uid, so a
package written by `go-hk-agent` could never be read by root and a package root
owned looked legitimate; the install contract then created the store `root:root`,
which the writer refuses outright. The anchor is now the account name
`go-hk-agent`, resolved per check, and `seal()` re-verifies the final object
through the same primitive `resolve()` uses before reporting it sealed.

```
hk-staging/hk_agent/artifact_store.py   was d5b182b693d2f6be469a2f2dbb9ced7299db00074f1b3d1c64ee4cc9515e8c76
                                        now 5dddc742b7ca668033547cb56073e6d65ba492d747d271622c9ca2b3df4335a4
tests/test_artifact_store.py            was c684bd5298012823d3047e3ad524a8537df1072953b22790cd1bfaf4b0cb5c29
                                        now cbff46199b16affdeca4b268da760192839851b306f3f15235f6e6ec2f438ed7
tests/test_live_integration.py          was 67af7de8f26e214ab1d05575e8564f0a504b647b6252f988f38f8f232683826c
                                        now ff10e997abf8846ea9328e3f8074f6a3afcf2ea7faec9c44f7c7e1b354ac47bd
tests/test_test_pr_durability.py        was c16a057421cc17f88e834e7ad586f6cb4da19412e1c04a9e0d33bf0291ae51cb
                                        now c9f216ca49c4d3464edf1afc90afc0e2c707082c0ab2d605dcfd9549763d186d
install/install-hk-agent.sh             was a70c797e5a8cc3436e06681b0368959cae05b5f7f51152b3bef1861605fae245
                                        now c3469382e111c4994018ba2e29de2651667dc0c8c37254f9a60e26fee4033be9
install/preflight.sh                    was aac9d5f34c45b82a7cfa70015b1b1dfa94e6b372e6232d02c41c4ba2abdfceb6
                                        now 52300c0416fb0da51cb6cced249c6be4b9e91e59d88565fa23e39c34a14b11a3
```

In the executor tree (tracked by `hk-staging/SOURCE_SHA256SUMS.txt`, and for the
first two by `go-hk-deployctl`'s own runtime pins):

```
hk-staging/source/executor/runtime/artifact_runtime.py   91f93f7f… → 81f91c7c…
hk-staging/source/executor/go-hk-deployctl               a47ea608… → db9d1584…
```

`_CANARY_SHA256` and `_DEPLOY_SHA256` had been computed over a CRLF working tree,
so they never matched the bytes this repository ships and no `_load_*` could
succeed. Every runtime pin is now taken from the committed bytes, and each one is
verified by loading the runtime in an installed layout.

```
INSTALLATION_PERFORMED=NO
DEPLOYMENT_PERFORMED=NO
HONG_KONG_TOUCHED=NO
```

## B4-B1 — the built image is sealed, and the artifact identity is re-contracted

`test_pr.py` V2 built an image, reported `built_image_id` in signed Evidence, and
then removed the image in its `finally` block. Every TEST_PR check passed and no
copy of those bytes existed anywhere, so nothing could CANARY or DEPLOY the
artifact the Evidence named. V3 seals the exact built image into a fixed,
content-addressed local store **after** every gate has passed, records the package
identity in the Evidence, and still removes the temporary tag.

Sealing rather than pushing is deliberate: a registry digest only exists after a
push, it is not equal to an image config ID in general, and the previous contract
required a digest whose suffix equalled the image id — a condition no real
candidate could satisfy. The delivery identity is now the sealed package's own
SHA256 (`contract go.sealed-artifact.v1`), and `candidate_repo_digest` is gone from
the plan, the Task parameters, the HK agent and both executors. See
`docs/control-plane/hk-staging/B4B1_DURABLE_ARTIFACT_20260916.md`.

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
