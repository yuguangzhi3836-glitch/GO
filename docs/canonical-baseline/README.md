# GO unified source candidate — retention repair

Status: **ACCEPTANCE_PENDING / NOT_DEPLOYED / NOT_CANONICAL_YET**.

The development source under review is `application/` on this repair branch. It starts with all 1,271 application files from PR42, which match the application in the latest parent `CP11_DEPTH40_P03_COMPAT_V2_PARENT_20260912`. This source is not the archived HK-STAGING runtime under `hk-staging/`; no live runtime verification is claimed.

The immutable parent archive remains unchanged. Its SHA256 is `421b11f95d0400bdfc69d4053a6d3b54599fa791a0d6b43311b83094bcd51c6a`. The PR43 deployment compatibility source is preserved byte for byte under `control-plane/depth40-compat-v2/`, without installation or execution of deployment commands.

## Restoration and provenance

The original DEPTH40 parent build used the initial DEPTH36 source and omitted later corrections. This candidate restores the DEPTH36R2 supporting files, DEPTH36R3 corrected mobile contract test, and the DEPTH37/DEPTH37R2 mobile configuration, dependency lock, native-module checker, navigation/recovery and input-preflight support. The final corrected historical source reference is `da6897706793fafd73d09cb56013586089733f4d`; DEPTH36R3 is `7bd98db21ee950aeb91c12b296b1864b5a758c3f`.

`ci/retention/BASELINE.json` enumerates every inherited Git blob, each repaired file's SHA256, and every preserved compatibility blob. Verification rejects deletions, unexpected additions and changes to inherited files. This establishes byte retention, not proof of full behavior.

Two deliberate safety corrections differ from the historical repair bytes: `CURRENT_CONTROL_VERSION.md` now identifies the candidate without inheriting old authority/runtime claims; the bring-up evidence template is `NOT_RUN`, with no invented PASS or execution time. Older release/governance manifests, staging templates, and `application/.github/workflows/` are historical support snapshots. They are not current release evidence, operational authority, or active root workflows.

## Outstanding gates

- **Provider guard — HOLD_APPROVAL:** saving the corrected `scripts/p0_0101_named_provider_certification.py` was rejected by automatic approval because the enclosing script contains credential-backed external payment/provider operations. The proposed historical correction only adds input-preflight validation, but this candidate leaves the original parent script unchanged. Explicit user approval is needed to restore that source-only correction. No external certification is run.
- **Regression — pending CI:** the new workflow binds the exact PR head, verifies frozen dependencies, runs all Python test files across four shards, frontend tests, compatibility unit tests and disposable loopback HTTP checks. Artifacts, logs, failures and skips are evidence; workflow success alone does not certify all product journeys.
- **Cross-end journeys — pending:** HTTP checks cover consumer/admin/supplier session isolation, login, refresh, logout and exact served assets. They are not browser or native-device acceptance. Desktop/mobile browser interaction, supplier/admin business journeys and iOS/Android native acceptance require evidence on the exact candidate source before final approval. Do not inherit historical browser/native PASS labels.
- **PostgreSQL-specific coverage:** any skipped database tests remain explicit gaps. This task does not access RDS or execute migrations.

No merge, HK-STAGING connection, deployment, RDS change, migration or Production operation is included.

## One development starting point

This branch follows PR41's proposed `main -> short-lived branch -> tests -> PR -> review -> explicitly authorized merge` process. PR41 governance documents are incorporated as proposed rules; their presence does not enforce GitHub branch protection. Required checks and branch protections must be confirmed separately before relying on enforcement.

Finish the outstanding gates on this repair branch. After review and explicit merge authorization, the resulting main commit and its `application/` become the single canonical development baseline. Start subsequent feature branches from that main commit; record parent SHA, scope, tests and topology impact in each PR. Do not independently resume historical feature branches or build from old archives. Topology changes require the versioned topology process; merge approval is separate from deployment authorization.

CANONICAL_SOURCE_RECOMMENDATION=REJECT

This is a temporary rejection for final baseline adoption until the listed restoration and acceptance gates are complete, not a rejection of retaining the latest parent as the repair starting point.
