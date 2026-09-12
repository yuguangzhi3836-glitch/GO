# 新父包构建

本次将统一候选封装为 **CP11_DEPTH41_UNIFIED_PARENT_V1_20260912**，完整源码与新镜像一并构建。固定输入、离线恢复和永久 Git 分卷归档方法见 [父包说明](../../packaging/depth41-unified-parent/README.md)。实际构建结论以本次提交的 Actions Run 和 PARENT_BUILD_REPORT 为准；不能继承下方历史结果。

# GO 唯一待验源码

当前唯一候选位于 **PR47 / fix/canonical-parent-retention-20260912 / application/**。
应用 Git tree：`a73b9b53a59c88ab995d0f9b123c9fb79e87e60d`。状态：**UNIQUE_CANDIDATE_PENDING_ACCEPTANCE**，尚未合并或部署。

已逐文件对齐 PR47 `3091d912a991cd78bc21f102d6e7a390a6caaf8a` 与 PR48 `c8d2b8021dce80388b8f548257db6a86d227c98a`：
1,264 个文件完全一致；PR47 独有的 27 个文件全部保留；9 个不同文件中，8 个保留 PR47 有效修订，1 个采用 PR48 的供应商经营中心修复。最终仍为 1,300 个文件，PR47 没有文件被删除，应用仅变更 frontend/shared/app.js。

- [完整逐文件选择表](PR47_PR48_FILES.csv) / [机器可核验清单](PR47_PR48_ALIGNMENT.json)
- [非应用目录的差异处理](PR47_PR48_NON_APPLICATION_DIFF.json)
- [历史证据及其版本绑定](EVIDENCE_INDEX.json)
- [剩余缺口及所需验收证据](REMAINING_GAPS.md)
- [PR48 原始日志和历史工具](../../evidence/canonical-alignment/pr48-c8d2b802/README.md)

PR48 保留为历史旅程记录；后续补齐与验收集中在 PR47。归档的旧旅程工具不会作为活动 workflow 启动，也不能直接用于新源码的来源校验。两个历史候选的 PASS 不合并、不转移。源代码身份与验收结果必须分别记录。

继续遵循 PR41：当前 main → 短期分支 → 提交/测试 → PR → 审查 → 明确授权后合并。完成统一候选的验收并获准合并后，才从 resulting main 的 application/ 开新功能分支。代码收敛不授予合并或部署权限；HK-STAGING 运行快照与本源码不同。

---

以下为 PR47 修复起点和历史修订说明，历史 pending/测试信息应结合上方证据索引阅读。

# GO unified source candidate — retention repair

Status: **ACCEPTANCE_PENDING / NOT_DEPLOYED / NOT_CANONICAL_YET**.

The development source under review is `application/` on this repair branch. It starts with all 1,271 application files from PR42, which match the application in the latest parent `CP11_DEPTH40_P03_COMPAT_V2_PARENT_20260912`. This source is not the archived HK-STAGING runtime under `hk-staging/`; no live runtime verification is claimed.

The immutable parent archive remains unchanged. Its SHA256 is `421b11f95d0400bdfc69d4053a6d3b54599fa791a0d6b43311b83094bcd51c6a`. The PR43 deployment compatibility source is preserved byte for byte under `control-plane/depth40-compat-v2/`, without installation or execution of deployment commands.

## Restoration and provenance

The original DEPTH40 parent build used the initial DEPTH36 source and omitted later corrections. This candidate restores the DEPTH36R2 supporting files, DEPTH36R3 corrected mobile contract test, and the DEPTH37/DEPTH37R2 mobile configuration, dependency lock, native-module checker, navigation/recovery and input-preflight support. The final corrected historical source reference is `da6897706793fafd73d09cb56013586089733f4d`; DEPTH36R3 is `7bd98db21ee950aeb91c12b296b1864b5a758c3f`.

`ci/retention/BASELINE.json` enumerates every inherited Git blob, each repaired file's SHA256, and every preserved compatibility blob. Verification rejects deletions, unexpected additions and changes to inherited files. This establishes byte retention, not proof of full behavior.

Initial deliberate safety corrections differ from the historical repair bytes: `CURRENT_CONTROL_VERSION.md` now identifies the candidate without inheriting old authority/runtime claims; the bring-up evidence template is `NOT_RUN`, with no invented PASS or execution time. Older release/governance manifests, staging templates, and `application/.github/workflows/` are historical support snapshots. They are not current release evidence, operational authority, or active root workflows.

## Regression corrections found in this candidate

The first full isolated run found four failures: a confirmed mobility checkout replay wrongly entered the unpaid deadline guard; the worker CLI test consumed the hardcoded LOCAL queue instead of the API fixture's TEST queue; a historical control-document test asserted obsolete authority; and the safe evidence template differed from the expected secret-prohibition wording.

The candidate now returns a confirmed mobility replay only after verifying the matching payer, supplier fulfillment and a single confirmed capture with the accepted amount/currency. It performs no new payment or supplier operation on that replay and leaves unpaid expiry guards unchanged. Negative tests reject uncertain capture evidence. Tests now bind worker/API environments consistently and assert source identity without inherited authority; the evidence template retains NOT_RUN and the expected secret-prohibition phrase. These intentional new corrections are separately enumerated in BASELINE.json and require new regression evidence.

Full-suite CI uses disposable SQLite databases, including historical schema round-trip tests on temporary files. It does not connect to HK-STAGING, RDS or Production, and does not apply operational migrations.

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
