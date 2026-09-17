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

## B4-B1.2 — both `docker save` formats, and a refusal that is reported

The first real TEST_PR failed. `docker build` succeeded and every isolated check
ran — eleven seconds short of two minutes of real work — and then `seal` refused
the archive it had just produced:

```
artifact_store.py:355  config_digest = _config_digest(temporary)
artifact_store.py:248  raise Reject("SEALED_ARTIFACT_ARCHIVE_INVALID")
```

Two defects, both in the B4-B1 change above, and neither was visible from this
workstation or from CI.

**A. The parser knew one of the two formats.** HK-STAGING runs Docker 29.7.2 on
the containerd image store, so `docker save` writes an OCI image layout:
`oci-layout`, an `index.json` pointing at a *nested* index, that index pointing at
the image manifest, and every blob filed under `blobs/sha256/<digest>`. The
parser's only shape was the legacy docker-archive, whose `manifest.json` names a
flat config member — and every fixture in this suite wrote that legacy shape, so
the suite agreed with the parser and the host did not.

That line number is exact, and it corrects an earlier reading of it:
`manifest.json` *was* present, was a one-element list, and its `Config` was not a
bare digest — the hybrid Docker writes when both markers are present. The live
file on the host was byte-identical to the committed one, which is what makes the
line authoritative.

Both formats are now read by one grammar, on both sides of the contract:

* the OCI side is followed as a *descriptor graph* (index → nested index → image
  manifest), bounded in depth and in descriptor count, each digest followed once;
  the descriptor `index.json` itself names must be present as a regular member and
  hash to what named it, an index entry whose blob the archive did not export is
  skipped rather than refused (Docker catalogues every platform and ships one), and
  everything a manifest the walk actually follows names must be present and hash to
  the descriptor that named it;
* the legacy index is kept, and its reference may name either the flat member or
  `blobs/sha256/<digest>`; only those two canonical locations are ever read, and
  the digest comes from the reference's own last component, so no JSON value can
  name a path of its choosing;
* a media type outside the declared allowlists is never candidate authority, an
  attestation manifest is bound into the graph but is not an image, and two
  layouts in one archive must name the same image or the archive is refused
  rather than resolved by preference;
* whatever the layout, the decision is unchanged: the archive must prove an
  identity equal to the candidate image id, and the role that identity played is
  recorded rather than assumed (corrected in B4-B1.3 below). A descriptor digest,
  an index digest, a config digest and the package's own SHA256 are four identities
  and are never interchanged;
* the executor's reader applies the identical grammar, and a cross-side test runs
  both implementations over the same 32-archive corpus and fails if either side
  disagrees about any one of them.

**B. The store's refusal killed the whole pass.** `run_once` catches a closed set
of exception types and the store's `Reject` was not among them, so it escaped
`test_pr.execute`, killed the agent process, published **no** failure record, and
left the ledger attempt `claimed` with a `NULL` diagnostic: the executor really
ran, really failed, and the control plane saw nothing — the TD-J lesson again, in
a new place. `test_pr` now converts the refusal at its own boundary into a
TEST_PR rejection carrying stage `artifact_durability` and the closed reason code
`ARTIFACT_DURABILITY_REJECT`, with the store's own bounded code carried in the
diagnostic channel; `run_once` also lists the store's type as a belt to that
braces, so no refusal from it can ever kill a pass again. The failure is now a
business result: reported, signed, and the attempt closed.

The fixture rule this established: the archive builders live in
`tests/archive_fixtures.py` and every suite imports them, because a second private
copy of them is how the blind spot was built in the first place. A CI step also
parses a **real** `docker save` archive produced by the runner, records which
format it turned out to be, and asserts both sides agree — while the deterministic
OCI fixture remains the authority for a format the runner may not produce. On its
first real run that step answered `REAL_DOCKER_SAVE_FORMAT=OCI+LEGACY`: an
independent host, which has never seen Hong Kong, produces the hybrid shape that
the failing traceback pointed at.

### B4-B1.2 superseded hashes

```
hk-staging/hk_agent/artifact_store.py   was 5dddc742b7ca668033547cb56073e6d65ba492d747d271622c9ca2b3df4335a4
                                        now f22bc4ed45be6ff2b01f63c72abc8fafd6380ff1c2f09ab08d136a921ff686be
hk-staging/hk_agent/test_pr.py          was 5247882993a86fada07df256f256b74ad6aa42f2e9fc7b3427192bd3e4cad778
                                        now d1c454fc4b4c3066cbd6e8195b686de4ec676c2b6f67d4cf33d332ad4cedf1f0
hk-staging/hk_agent/transport.py        was b35ace2289d9b8e64805d584a893f0e3c5efb7c6050fbbdbfaaf492dee3d700d
                                        now 32ff16c18b6230d50a4d2feba2c56fc19cdef36f702b1b56d735335c77625270
tests/test_artifact_store.py            was 936c9c4928f1a31dc012ee9e51da9ae2f042d61b14e0bb6fe3a87e60b5ebff94
                                        now 6bbd584a09c652427ed9cc4e69b9673b80faa7a08969578b2301a8856490906e
tests/test_test_pr_durability.py        was 425ac614fef5208ea545579fba43d6e7ad86ddf9db28c20aebb0e19e69a3fb9f
                                        now 816cd180660d308d89dc9756d538a1f1a1b3be48cf36b1ef5eb00a4fc38c645d
tests/test_live_integration.py          was ff10e997abf8846ea9328e3f8074f6a3afcf2ea7faec9c44f7c7e1b354ac47bd
                                        now c0db89469f500ac47fe8ca6d4353efef794584d265676d1b3fe4d5a24dfcd8b3
tests/archive_fixtures.py               new 61768c9245548d804f73517c9d1ba6db76f1445a33b35b3bbbe7fa4959e1b335
```

The executor's reader and its pinned loader live outside this component and are
pinned by `hk-staging/SOURCE_SHA256SUMS.txt` and by `go-hk-deployctl` itself:

```
hk-staging/source/executor/runtime/artifact_runtime.py
              was 81f91c7cf8630ae57687676f3d6e9ec194b1c064488004a2593c1cd58cd76818
              now b32b2168ea85ffe43c0547257df04a36d883ba93b3bb1717a626f329479518f0
              _ARTIFACT_SHA256 in go-hk-deployctl was 81f91c7c… and is now b32b2168…
              the other four runtime pins are unchanged: no other runtime moved
hk-staging/source/executor/go-hk-deployctl
              was db9d1584e56781e9b73d3db50495ee4b7422c05deb6fdaa315b9a7033393b53e
              now d589743da6271a3da0c42a3a79f73ea2870bacc4172a92ee2f1a4335b260fed6
.github/workflows/hk-agent-failure-evidence-v1.yml
              was a8ed814dc26e4ab376b09b158260e79e4d88620724d5f24b6ececb0f7563e9f0
              now 885b22abc3f357062125e7436a066ec11f3385f7b563dd06062dbeb6072252a8
```

```
INSTALLATION_PERFORMED=NO
DEPLOYMENT_PERFORMED=NO
HONG_KONG_TOUCHED=NO
```

The live host still runs the B4-B1 revision of the agent modules and the executor
(`5dddc742…`, `52478829…`, `b35ace22…`, `81f91c7c…`). This revision is
repository-side only: nothing is installed by it, and a TEST_PR issued against the
live host today would still fail at the durability step.

## B4-B1.3 — which identity Docker actually reports

The install round for B4-B1.2 stopped **before it wrote anything**, because the host
was asked first. Every preflight hash matched the plan, the shadow tree exercised the
candidate as both production identities, and both sides agreed on every constant —
and then three **real** `docker save` archives were parsed, which is where B4-B1.2
died:

```
go-hotel:depth48-runtime-6d0fd905   docker .Id = sha256:1c9598d6…   archive config = 57beafa2…
redis:7.4-alpine (pulled)           docker .Id = sha256:ff02b58f…   archive config = 5509c009…
a local `docker build` probe        docker .Id = sha256:3906d4c8…   archive config = fb0191cd…
image_identity(tar, .Id)            -> Reject …CONFIG_MISMATCH, on both sides, in all three cases
```

**The identity the contract required and the identity Docker reports were never the
same value.** On a host using the containerd image store — HK-STAGING runs server
29.7.2 on `io.containerd.snapshotter.v1` — `docker image inspect --format '{{.Id}}'`
is the digest of the descriptor `index.json` names, which is an *index* digest; the
image's config digest is a different value. B4-B1's store required the config blob to
hash to the reported id, so `seal()` could not have succeeded on this host for **any**
image: installing B4-B1.2 would have changed nothing but the failure code.

Two further things were wrong for the same reason, and a third only became visible
once the corrected grammar could walk a real archive far enough to reach it:

* **Real archives carry descriptors whose blobs they did not export.**
  `docker save redis:7.4-alpine` names sixteen manifests and ships two — the platform
  that was pulled, and its attestation. A parser that requires every described blob to
  be present refuses every multi-platform archive.
* **The CI smoke could not have caught either.** It asserted
  `digest == image_id.split(':')[1]`, which passes on a GitHub runner because *that*
  runner's Docker reports the config digest. The assertion was about a coincidence of
  one runner's image store, not about the contract.
* **An attestation's config could stand as the candidate.** Docker writes an
  attestation manifest beside every image, and for a *pulled* reference it marks that
  manifest only in the descriptor that names it — no `artifactType` in the body — while
  its config blob is an ordinary-looking image config. Checking only the manifest body
  let that config digest into the set of identities that could name the candidate. Both
  signals are now checked, and the read-only probe against the host's own archives is
  what found it: the walk had never reached an attestation before.

What this revision changes:

* `archive_identity(archive)` returns three separate fields — `root` (the digest of
  the descriptor `index.json` names), `configs` (the image config digests the graph
  proves) and `legacy` (the config digest `manifest.json` names). `image_identity(
  archive, image_id)` proves the candidate in whichever role the archive can support,
  after hashing the bytes behind it, and reports `image_identity_role` along with both
  identities. Neither identity is ever compared with the other.
* An index is read as a *catalogue*: an entry whose blob the archive did not export is
  skipped. The root descriptor's own bytes are **not** optional, and a manifest the
  walk follows must have its config and every layer present and hashed.
* `seal()` records `image_identity_role`, `root_descriptor_digest` and
  `config_digests` in the sealed package the Evidence carries, and the agent refuses to
  publish a package claim that omits them or contradicts them — a claim naming only the
  build id cannot be audited against the archive it came from.
* The smoke now asserts **roles** instead of equality: that the reported id matches the
  role it claims, that the archive's config digest is recognised in its own role, that
  the two differ, and that an identity the archive cannot prove is refused. It also
  prints the daemon version and the role it observed, so a future divergence is visible
  rather than inferred.
* `tests/archive_fixtures.py` gained the multi-platform shape
  (`multiplatform_save`), and the cross-side corpus grew from 26 archives to 31.

```
control-plane/…/hk-staging/hk_agent/artifact_store.py
              was 5dddc742b7ca668033547cb56073e6d65ba492d747d271622c9ca2b3df4335a4
              now 61731061062883013c7f9eed8196485a6bd22bd96b9770613225a3ef9c408c92
control-plane/…/hk-staging/hk_agent/transport.py
              was b35ace2289d9b8e64805d584a893f0e3c5efb7c6050fbbdbfaaf492dee3d700d
              now af8261568fb7158f3bd6f620f3a405118b1ae77d3d662b764e62c3fe260e5fcb
hk-staging/source/executor/runtime/artifact_runtime.py
              was 81f91c7cf8630ae57687676f3d6e9ec194b1c064488004a2593c1cd58cd76818
              now 736b557167fd641aaf59ef66c4380d0d7902aa91b562aee2a5c3688918687e7b
              _ARTIFACT_SHA256 in go-hk-deployctl follows it; the other four pins do not move
hk-staging/source/executor/go-hk-deployctl
              was db9d1584e56781e9b73d3db50495ee4b7422c05deb6fdaa315b9a7033393b53e
              now 0cc03cac02940b4c9ee2ce3851156940a9b74386affa8348533b2257a99cbdbd
```

`test_pr.py` is deliberately unchanged: the identities it reports (`built_image_id`
from `docker image inspect`) were already correct, and it is the store, not the
builder, that had bound them to the wrong role.

```
INSTALLATION_PERFORMED=NO
DEPLOYMENT_PERFORMED=NO
HONG_KONG_TOUCHED=NO
```


## Task-scoped OCI diagnostics

A TEST_PR archive refused by the OCI parser remains a failure and never enters the
loadable `objects` namespace. The writer publishes a fixed parser subcode and retains
the exact tar as `failures/<sha256(task_id NUL nonce)>.tar`, mode 0600 beneath the
trusted-writer 0700 store. The existing failure Evidence diagnostic carries only that
identifier, the archive SHA256 and its byte count. The retained bytes grant no retry,
replay, load, migration or deployment authority.
