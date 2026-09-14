# C13 Node overlay source review

Date: 2026-09-14 UTC. Reviewer: independent C13 acceptance agent.

Result: SOURCE_REVIEW_PASS_SCOPED. No must-fix finding remains in the reviewed Node packaging scope. Actual CI build and independent restore have not yet been observed; they must not be counted PASS from this review.

## Reviewed identities

Fixed source c6ea4dd670db36e71f3839fb31e656a5c8806858; application tree 995d0d83faf883bec980c896fe8a17b0f12360fa; 1332-file SHA256 1c4d78c3c1bb5f448d0ebdb99d16a2d76419bbc663cc9ed8fae831e1d18c10c4.

| Path | SHA256 |
| --- | --- |
| packaging/canonical-node-seal/seal.py | 7cde7764ca149e19cbd0127e2673b02fe3e28fedc0913e599ed3fcaa7e24541c |
| packaging/canonical-node-seal/test_seal.py | d051c19580b0232c2bc9327c0d46f673ed34819e7bb99322c4484b921ee2ab69 |
| packaging/canonical-node-seal/README.md | 66a548ffdb52839a57ecda0646968edce5c668e00151363a1d61aaa63db6088b |
| .github/workflows/canonical-node-seal.yml | dbf93bbc14438bde064a10efe404a08c1bc0d4d7a6d68818212e91ffcfc92235 |

## Review findings

The builder extracts the fixed source and requires both fixed and builder application Git trees to equal the declared tree. Full 1332-file fingerprint is checked before provisioning. The unchanged original provisioner operates on a temporary source copy with an explicit temporary work directory. Original canonical file hashes are rechecked afterward; generated Node and manifest remain a separately packaged overlay. This does not modify the canonical application or previously tested business image.

The original NODE_SOURCE.json pins Node v22.22.0 linux-x64, official archive SHA256 9aa8e9d2298ab68c600bd6fb86a6c13bce11a4eca1ba9b39d79fa021755d7c37, and GLIBC ceiling 2.35. The original provisioner validates upstream SHA, version, architecture, and Node/shared-library GLIBC requirements. The original integrity gate independently checks PATH precedence, manifest/source agreement, executable version, complete tree hash, and Node GLIBC requirements.

The new wrapper's compare_official_overlay verifies every regular file's bytes and mode, every symlink identity, and the exact file/link set against a fresh extraction of the retained pinned official archive. This closes the possibility of relying on a self-consistent but substituted overlay and manifest. It is applied during build and restore before gate execution. Directory metadata is not part of this file/link inventory; no directory-metadata fidelity is claimed.

Archive extraction requires an empty destination and rejects traversal, normalized duplicate names, special files, hardlinks, non-directory parents, and links that escape or do not terminate at a regular archived file. Restore checks the outer package SHA and full bundle inventory, independently verifies complete source fingerprint, original archive SHA, official-overlay equality, and overlay inventory before copying. It does not invoke download or the provisioner. The original gate then runs with the restored sealed Node first in PATH, and receipt emission follows candidate node identity comparison.

The workflow uses separate ubuntu-22.04 jobs, checks out the exact PR head, has read-only repository permission and no persisted checkout credentials, passes the original artifact to restore, retains failure output, and preserves full-release/production HOLD. Restore avoids downloading or provisioning Node; it is not network-disabled at the runner level, and no network-isolation claim should be added.

## Independent targeted validation

I ran a temporary-file probe of the newly added official-overlay comparator, separate from the coordinator's seven reported safety tests. Exact official overlay was accepted; altered file bytes, altered executable mode, an extra file, and replacement of a symlink by a regular file with identical contents were each rejected. All five targeted outcomes matched expectations. No Node download, application regression, GitHub write, or Hong Kong operation was performed in this review.

## Remaining acceptance boundary

CI must show actual provision/gate PASS, an immutable node-seal package SHA, actual Node tree hash, and the independent restore receipt binding those same identities. Source review alone cannot establish Sealed Node completion. Even a successful separate Node overlay is not native/device acceptance, a complete release gate, deployment-plan approval, or proof of installation in Hong Kong. Full Release and Production remain HOLD; deployment remains NOT_RUN.
