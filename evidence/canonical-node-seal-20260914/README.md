# Canonical Node supplement and release evidence

This record continues the accepted PR66 source and PR67 acceptance archive.
The complete application remains tree 995d0d83faf883bec980c896fe8a17b0f12360fa,
1332 files, source SHA256
1c4d78c3c1bb5f448d0ebdb99d16a2d76419bbc663cc9ed8fae831e1d18c10c4.

PR69 separately built and independently restored the canonical Python business
image. Its package SHA is b297f139a236681019fe894f4f1a94068636649e1235a20502a383a610f16f63;
image config ID is sha256:47bb66c429868689e922ecc1bee668e9c12bfa24e2cddca1717e16887f34115d.
The original runtime package remains unchanged. Its proof is archived in
../canonical-runtime-package-20260914/ and its binary artifact has finite
GitHub retention; no indefinite binary retention is claimed.

PR70 provisions a separately inventoried Node supplement from the fixed
official v22.22.0 linux-x64 archive and the unchanged canonical provisioner
and integrity gate. It is an overlay used for verification, not a silent
change to application/ or the previously built business image.

The first Node run 34795685137 failed in a legitimate relative-link safety
test under the Ubuntu22.04 system Python3.10 tarfile filter. Provision and
restore did not execute; the empty artifact upload also failed. Preserve
the original log. The workflow now selects the locally validated Python3.12.14
for extraction in both jobs and preserves safety-test output. The data filter
and all unsafe-path rejection rules remain enabled.

See C13_SOURCE_REVIEW.md for independently checked source and malicious-overlay
rejection evidence. Actual successful build/restore identities, if obtained,
are recorded separately in C13_ACCEPTANCE.md and BINDING.json; this narrative
does not manufacture their completion.

Existing source and regression PASS results are inherited at their original
scope. A toolchain Gate is not native device acceptance, worker liveness,
1000 active users in Hong Kong, complete UX or Final Release. Current runtime
dependencies were recorded at build time and differ from the earlier frozen
source CI environment; runtime-bound full-release evidence must address that
boundary. Registry RepoDigests is empty and is not invented from config ID.
The installed deployment contract's digest equality restriction, fresh signed
CANARY/VERIFY and approved signed plan remain separate deployment requirements.

Hong Kong was not accessed or changed. Production and Full Release remain HOLD.
No 14-Cell-wide 100% completion is claimed.
