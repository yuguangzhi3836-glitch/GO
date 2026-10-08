> **HISTORY / BREAK-GLASS REFERENCE**
>
> This document is not the normal current operating path.
>
> Normal deployment and inspection are defined by [`/AGENTS.md`](../../../AGENTS.md) and use GO Forge.
>
> Do not issue `HK_STAGING_*` requests unless the Owner explicitly authorizes Old Command Center fallback mode.

---

# B4-B1.3 — the identity Docker actually reports

Date: 2026-09-16
Branch: `cc/v1-finalization-20260914` (PR #109)
Scope: repository-side only. No installation, no HK or Command Center access, no
Task, Evidence, TEST_PR, CANARY, DEPLOY or ROLLBACK.

## Why this exists

The install round for B4-B1.2 stopped before it wrote a single byte. Every preflight
hash matched the plan, the shadow tree exercised the candidate as both production
identities, and both sides agreed on every shared constant — and then three **real**
`docker save` archives were parsed on the host:

```
go-hotel:depth48-runtime-6d0fd905   docker .Id = sha256:1c9598d6…   archive config digest = 57beafa2…
redis:7.4-alpine (pulled)           docker .Id = sha256:ff02b58f…   archive config digest = 5509c009…
a throwaway `docker build` probe    docker .Id = sha256:3906d4c8…   archive config digest = fb0191cd…
image_identity(tar, .Id)            -> Reject …CONFIG_MISMATCH — both sides, all three archives
```

B4-B1 defined the sealed artifact's `image_id` as the archive's **config digest**.
The host reports the digest of the descriptor `index.json` names, which is an *index*
digest — a different value. HK-STAGING runs Docker 29.7.2 on
`io.containerd.snapshotter.v1`, so this is the normal case there, not an edge case:
installing B4-B1.2 would have changed the failure code and nothing else, because
`seal()` could not succeed on that host for any image.

A second defect was found in the same pass. `docker save redis:7.4-alpine` names
**sixteen** manifests in its index and ships **two** blobs — the platform that was
pulled, and its attestation. Everything else is simply absent. The B4-B1.2 reader
required every described blob to be present, so it refused every multi-platform
archive as well.

A third was found once the corrected grammar could walk a real archive far enough to
reach it. Docker writes an attestation manifest beside every image, and for a *pulled*
reference that manifest is marked **only** in the descriptor that names it
(`vnd.docker.reference.type: attestation-manifest`) — there is no `artifactType` in the
manifest body — and its config blob is an ordinary-looking
`application/vnd.oci.image.config.v1+json`. A reader that checked only the manifest body
therefore admitted the attestation's config digest into the set of identities that could
name the candidate. Both signals are now checked.

Neither defect could have been seen from this workstation or from CI: the smoke step
asserted `digest == image_id.split(':')[1]`, which is true on a GitHub runner because
*that* runner's Docker reports the config digest. The assertion was about a property
of one runner's image store, not about the contract.

## The correction

Identity is now three named roles that are never compared with one another:

| role | where it comes from | what it is for |
|---|---|---|
| `root` | the digest of the descriptor `index.json` names | the id Docker reports on a containerd image store; the archive's own target |
| `configs` | the image config digest(s) the graph proves | proving the archive really is an image |
| `legacy` | the config digest `manifest.json` names | the id Docker reports on a legacy image store |

* `archive_identity(archive)` returns those three fields.
* `image_identity(archive, image_id)` proves the candidate in whichever role the
  archive can support — after hashing the bytes behind it — and returns
  `image_identity_role` plus both identities. An archive that proves no identity equal
  to the candidate is refused with the renamed code `IMAGE_IDENTITY_MISMATCH`
  (previously `CONFIG_MISMATCH`, which named the wrong thing).
* An index is read as a **catalogue**: an entry whose blob the archive did not export
  is skipped, and skipping cannot promote anything because a descriptor only becomes
  authority once its bytes have been hashed in place. The root descriptor's own bytes
  are not optional, and a manifest the walk actually follows must have its config and
  every one of its layers present and hashed. A graph that ends up proving no image at
  all is `OCI_INVALID`.
* A root list with more than one entry is refused: several roots would make "the
  identity Docker reports" a choice, and this contract does not choose.

## What the Evidence carries

`seal()` now records `image_identity_role`, `root_descriptor_digest` and
`config_digests` alongside `image_id`, `package_sha256` and `package_bytes`, and the
agent's `evidence()` refuses to publish a package claim that omits them, names a role
that does not exist, or carries an empty or malformed config digest list. A claim that
names only the build id cannot be audited against the archive it came from.

## Verification

* Component suite: 150 → **152** tests (the four `bash`/POSIX-only rollback errors
  here are the same four that fail at the previous revision on Windows; they are
  environment, not code).
* New coverage: the multi-platform catalogue shape on both sides, sealing under the
  root-descriptor role and under the config role on both sides, an absent root
  descriptor, an index naming two images, an attestation's config digest refused as a
  candidate, the two identities recorded separately, and the agent refusing an Evidence
  package that does not say which role it bound.
* The cross-side corpus grew from 26 archives to **32**, and an accepted archive must
  now report the candidate id, a role that exists, and its own config digest.
* The smoke step's assertions were rehearsed on this workstation against fixture
  archives of all four shapes (multi-platform by root, multi-platform by config, OCI
  by config, legacy by config) before pushing, since the runner's Docker is not
  available here; the step itself cannot be executed locally.
* The read-only probe was then run **on the host with the corrected code**, against
  freshly written real archives, before anything was installed:

  ```
  pulled multi-platform   .Id ff02b58f…  role root_descriptor  configs [5509c009…]
  locally built image     .Id 1c9598d6…  role root_descriptor  configs [57beafa2…]
  writer == reader        True, both archives
  config digest as id     accepted, in the config role
  an identity the archive does not prove   refused, …IMAGE_IDENTITY_MISMATCH
  a pulled archive that used to be BLOB_MISSING   now parsed
  ```

  The first run of that probe reported two config digests for the pulled archive
  (`5509c009…` and the attestation's `a58a9ba4…`), which is how the third defect above
  was found.

## Install delta for the next round

Four files change; `test_pr.py` deliberately does not, because the identities it
reports were already correct and it is the store, not the builder, that bound them to
the wrong role. The pins in `go-hk-deployctl` and the manifests are regenerated in the
same change. Hashes are quoted in the component README.

## Boundaries

```
INSTALLATION_PERFORMED=NO
DEPLOYMENT_PERFORMED=NO
HONG_KONG_TOUCHED=NO
TRIGGERED_ENABLED=false / unchanged
B4_RELEASE_GATES / B4_CANARY_BASELINE / B4_AUTONOMY = untouched
```
