# Exact-byte repository archive

The user requested that the already generated DEPTH40 compatibility V2 parent be stored in the GO repository. The 187,168,614-byte accepted ZIP exceeds GitHub's single-file limit, so this operation divides its existing bytes into nine parts of at most 20 MiB. It does not rebuild or recompress the parent.

Fixed input: GO Actions Artifact `10281491262`, successful Run `34644569516`, source commit `4c9d24ee37cef02cfef026c41db3dfb38d09b9f0`.

- Outer artifact SHA256: `3a727c72cfe7d0894936bb066a71abf522a14a6a05943c8f4dc62b4f45cbcfe8`.
- Inner parent ZIP SHA256: `421b11f95d0400bdfc69d4053a6d3b54599fa791a0d6b43311b83094bcd51c6a`.
- Only destination branch: `archive/depth40-p03-compat-v2-parent-34644569516`.
- New parent files: `deliverables/CP11_DEPTH40_P03_COMPAT_V2_PARENT_20260912/`.
- Original inspection records: `evidence/depth40-parent-compat-v2/34644569516/`.

The script checks the source run, fixed hashes and file set, creates the parts and validates local reconstruction, then uploads blobs. It reads the actual stored Git blobs back, reconstructs the exact ZIP again and compares its full SHA256 before creating one new branch. The receipt records the blob IDs and actual result. New branch creation fails if the destination already exists; there is no force push, PATCH branch update, merge or delete operation.

This workflow needs `contents:write` only to create the archive blobs/tree/commit and its one new ref. This is the user's requested repository storage operation, not deployment authority. It uses no deployment credentials, does not create tasks or environments, does not build/load images or rerun application tests, and does not contact Hong Kong. PR #42/#43/#44 and main are unchanged. Production stays HOLD.

The original parent source commit is the archive commit's parent, so its packaging code stays reachable. The accepted package bytes, manifests, original CI output and reconstruction tool are stored directly in Git and do not expire with Actions Artifact retention. The archive receipt's own checksum is represented by its committed Git blob ID; root SHA256SUMS covers the payload prepared before that receipt.
