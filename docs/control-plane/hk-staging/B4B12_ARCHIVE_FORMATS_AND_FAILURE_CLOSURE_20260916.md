# B4-B1.2 — both `docker save` formats, and a TEST_PR failure that is reported

Date: 2026-09-16 (CST)
Authorization: Eason's standing instruction for this round — repository-side only,
no live access of any kind.
Branch: `cc/v1-finalization-20260914` (PR #109)

---

## 1. What happened, and what this round fixes

The first real fresh bounded TEST_PR (Request `boss-hk-testpr-20260916T1146Z-7091f9`,
Task `go-boss-test-pr-52-3249a0c8589a`) ran for 115 seconds, really built the image,
really ran the isolated checks, and then died at the durability step:

```
test_pr.py:157         artifact_store.seal(runner, image, image_id, root=ARTIFACT_STORE)
artifact_store.py:355  config_digest = _config_digest(temporary)
artifact_store.py:248  raise Reject("SEALED_ARTIFACT_ARCHIVE_INVALID")
→ uncaught → the whole agent pass exited 1
```

No success Evidence, no failure Evidence, and a ledger attempt left `claimed` with
a `NULL` diagnostic. Two defects, both introduced by B4-B1 itself, and neither
observable from the workstation or from CI.

## 2. Root cause A — the parser knew one of the two formats

The store's parser understood only the **legacy docker-archive**: `manifest.json`
is a list, `[0]["Config"]` is a bare 64-hex name, and the config blob is a member
of that name.

HK-STAGING runs Docker 29.7.2 on the containerd image store
(`driver-type io.containerd.snapshotter.v1`), so `docker save` produces an **OCI
image layout**: `oci-layout`, `index.json`, `blobs/sha256/*`, where the index may
point at a *nested* index before the image manifest.

The failure line is exact — the installed `artifact_store.py` was byte-identical to
the committed one (`5dddc742…`), so line 248 is the line that ran — and it reads
`index[0].get("Config")` followed by the bare-hex test. That corrects the first
reading of the failure: `manifest.json` **was** present, **was** a one-element
list, and its `Config` was **not** a bare digest. Reality is a *hybrid*: an OCI
layout with a legacy index beside it, whose reference is not the flat name. The
parser therefore failed at the digest-shape test, not at the member lookup.

**Why every test passed anyway.** Both fixtures
(`test_artifact_store.synthetic_save`, `test_test_pr_durability.save_archive`)
hand-built the legacy shape. A hand-made fixture proves a parser is self-consistent;
it cannot prove the parser recognises reality.

## 3. Root cause B — the store's refusal was not part of the failure path

```python
except (Reject, deployment_actions.Reject, test_pr.Reject) as exc:   # run_once
```

B4-B1 added the `artifact_store` module and did not add its `Reject` to that
tuple. The consequences are the TD-J lesson in a new place: the executor really
ran, really failed, and the control plane saw nothing at all.

## 4. The fix

### 4.1 One archive grammar, two layouts, both sides

`image_config_digest(archive, image_id)` is the single entry point on both sides of
`go.sealed-artifact.v1` (the agent's writer and the executor's reader).

* **OCI.** `index.json` is followed as a *descriptor graph* — index → nested index
  → image manifest — not as `manifests[0]`. Traversal is bounded
  (`MAX_DESCRIPTOR_DEPTH = 4`, `MAX_DESCRIPTOR_COUNT = 256`), each digest is
  followed once, a blob described as two different types is refused, and every
  blob read must exist at the derived path `blobs/sha256/<digest>` as a regular
  member whose bytes hash to that digest and match the declared size.
* **Media types.** Index, manifest and config types each have an explicit
  allowlist. A type outside them is never candidate authority. An attestation
  manifest (non-empty `artifactType`) is bound into the graph and hashed like
  everything else, but its config is not an image.
* **Legacy and hybrid.** `manifest.json` must be a list with exactly one entry; its
  `Config` may name either the flat member or `blobs/sha256/<digest>`, and only
  those two canonical locations are ever read, with the digest taken from the
  reference's own last component. An identity present at both locations is refused
  (`BLOB_AMBIGUOUS`), and a reference naming any other directory or a traversing
  path is refused (`MEMBER_UNSAFE`).
* **Two layouts in one archive** are acceptable only when they name the same
  image; otherwise `LAYOUT_AMBIGUOUS`.
* **Tar safety.** Member names are data: absolute, traversing and non-normalised
  names are refused; an *authoritative* name (the layout markers, any blob path)
  must be a single plain regular file, so a symlink, hard link, device or FIFO
  under such a name is refused rather than followed.
* **Three identities stay separate.** The image id is the SHA256 of the config
  blob's bytes; the package is addressed by the SHA256 of the archive; descriptors
  carry their own digests. Only the first decides which image an archive is, and
  a test asserts none of them is compared with another.

### 4.2 A refusal is a business result

`test_pr.durability_reject()` converts the store's refusal at the builder's own
boundary into a `test_pr.Reject` carrying `stage = "artifact_durability"` and the
closed reason `ARTIFACT_DURABILITY_REJECT`, keeping the store's own bounded code
in the diagnostic channel (`stderr`) so the published record names the real cause
without inventing a second error schema. `run_once` additionally lists
`artifact_store.Reject` in its `except` tuple as a belt to that braces: no refusal
from the store can kill a pass, whatever future code path raises it.

The published failure is the ordinary one: `kind = ARTIFACT_DURABILITY_FAILED`,
`stage = artifact_durability`, `executor_version = not_dispatched` (derived from
the stage, as every non-execution stage is), every validation gate `PASS`, the
attempt closed in the ledger with a diagnostic, and the record signed.

### 4.3 Fixtures are shared, and CI parses a real archive

`tests/archive_fixtures.py` now holds the builders and all three suites import
them, because a second private copy is exactly how the blind spot was built. A new
CI step builds a tiny image, runs a **real** `docker save`, parses it with *both*
halves, records which format the runner produced, and asserts they agree; the
deterministic OCI fixture remains the authority for a format the runner may not
produce.

## 5. Verification

```
SEALED_ARTIFACT_CROSS_UID_OWNERSHIP   unchanged (B4-B1.1, still live)
OCI_WRITER_SUPPORT                    PASS
OCI_READER_SUPPORT                    PASS
LEGACY_ARCHIVE_SUPPORT                PASS
NESTED_OCI_INDEX_SUPPORT              PASS  (1 level, 2, 3, and the legal maximum)
DESCRIPTOR_HASH_VALIDATION            PASS  (digest, size, absence, layers)
CONFIG_IDENTITY_BINDING               PASS
CROSS_SIDE_ARTIFACT_CONTRACT          PASS  (26-archive corpus, both implementations)
ARTIFACT_STORE_REJECT_CLOSED          PASS
FAILURE_EVIDENCE_ON_DURABILITY_FAILURE PASS
LEDGER_FAILURE_CLOSURE                PASS
AGENT_TICK_CRASH_ON_ARTIFACT_REJECT   NO
```

Test counts (this component): 96 → 143. `test_artifact_store` 53 → 92,
`test_test_pr_durability` 12 → 16, `test_live_integration` 33 → 35. On this
workstation the four bash rollback tests remain impossible, and the deploy-entry
suite still cannot import `fcntl`; both are identical, by name and by cause, at
`START_HEAD 554db619…`.

## 6. What the next round installs (NOT executed here)

Five files, all replacements, no new paths, no directory changes, no restart (the
agent is a oneshot started per tick; the executor is invoked per Task):

```
/opt/go-hk-agent-rebuilt/hk_agent/artifact_store.py
    live 5dddc742b7ca668033547cb56073e6d65ba492d747d271622c9ca2b3df4335a4
    next f22bc4ed45be6ff2b01f63c72abc8fafd6380ff1c2f09ab08d136a921ff686be
/opt/go-hk-agent-rebuilt/hk_agent/test_pr.py
    live 5247882993a86fada07df256f256b74ad6aa42f2e9fc7b3427192bd3e4cad778
    next d1c454fc4b4c3066cbd6e8195b686de4ec676c2b6f67d4cf33d332ad4cedf1f0
/opt/go-hk-agent-rebuilt/hk_agent/transport.py
    live b35ace2289d9b8e64805d584a893f0e3c5efb7c6050fbbdbfaaf492dee3d700d
    next 32ff16c18b6230d50a4d2feba2c56fc19cdef36f702b1b56d735335c77625270
/usr/local/libexec/go-hk-deployctl-runtime/artifact_runtime.py
    live 81f91c7cf8630ae57687676f3d6e9ec194b1c064488004a2593c1cd58cd76818
    next b32b2168ea85ffe43c0547257df04a36d883ba93b3bb1717a626f329479518f0
/usr/local/libexec/go-hk-deployctl
    live db9d1584e56781e9b73d3db50495ee4b7422c05deb6fdaa315b9a7033393b53e
    next d589743da6271a3da0c42a3a79f73ea2870bacc4172a92ee2f1a4335b260fed6
    (_ARTIFACT_SHA256 81f91c7c… -> b32b2168…; the other four runtime pins do not move)
```

Stale `__pycache__` for every replaced module, atomic rename in place, post-install
sha256 read-back, then one observed tick. The store is **not** touched: it holds
the only copy of any sealed candidate. Filenames are unchanged, so a rollback is
`cp -p` of five files plus the bytecode removal.

**Install and the next TEST_PR stay separate authorisations**, so a failure can be
attributed to installation or to artifact build/durability without ambiguity.

## 7. State after this round

```
B4_B1_2_REPO_READY            YES
LIVE_FIX_INSTALLED            NO
NEW_TEST_PR_EXECUTED          NO
DURABLE_ARTIFACT_EXISTS       NO
PACKAGE_BINDING               BLOCKED
DEPLOY_READY                  UNKNOWN
deployment_requests_enabled   false (untouched)
```

The failed Task `go-boss-test-pr-52-3249a0c8589a` is history and stays that way:
its single attempt is spent, its ledger row is untouched, and a retry requires a
**new Request, a new Task id and a new nonce**.

Still open and deliberately not touched: `B4_RELEASE_GATES`, `B4_CANARY_BASELINE`
(0114 → 0133), `B4_AUTONOMY`, `DOC_CONTRACT_DRIFT`.
