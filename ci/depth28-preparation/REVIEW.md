# DEPTH28 acceptance preparation review

Candidate: `6c85c64fe77ce7637a001ddbd8050ffa24f639a3`.
Reviewed workflow: `3ca1a1ec49b051928e8cd3a6a95aef14e13b93ec`, `.github/workflows/depth28-v14-acceptance.yml`.

Directly inspected repository evidence:

- DEPTH27 recursive Git tree is complete (not truncated), with 689 entries and no root `src`, `frontend`, or `pyproject.toml`. It stores delivery archives. Checkout alone is not a restored source tree.
- Fetching root `pyproject.toml` on DEPTH28 returns 404. The 29 added root files are an overlay, not the full 1093-file source.
- The workflow passes raw DEPTH27 checkout to the restore script, which requires the exact materialized parent fingerprint. That preparation is incomplete.
- The workflow has a pull-request path filter that omits its own path. A workflow-only PR may not trigger this check. No CI failure is claimed: the workflow has not run.

Local verified preparation:

- `materialize.py` validates each DEPTH26 split archive hash and the joined archive SHA256 `7def8724d0bd5231fdd9b7ec8548951ed01a896d6b5d059d6d326d6bb252676a`.
- It extracts into a fresh temporary directory, rejecting unsafe archive paths and symlinks.
- It invokes the archived DEPTH27 and DEPTH28 restore scripts sequentially, then checks all 1093 final source fingerprints.
- This local execution passed. Final source tree SHA256: `3a8440e2d74e1dc4f86509686968683f98bec4b78c9f0ca0e43a02dedeac285f`.
- Existing local unit-test results remain scoped to their recorded runs. No unit suite was rerun for this review, and no browser, independent CI, HK deployment, or release approval is claimed.

Prepared correction, awaiting authorization to trigger CI:

1. Pin the candidate checkout SHA explicitly, materialize the archive chain, then run contracts from the restored directory.
2. Include the workflow and preparation-script paths in the PR trigger filter and bind acceptance outputs to the sealed source fingerprint.

The current remote workflow is still uncorrected and must not be described as ready. Its correction and CI execution remain separate from the immutable DEPTH28 candidate. No production operation is required for this preparation.
