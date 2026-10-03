# GO Update Log

> GO 主项目的短时间线入口。只记录会改变项目理解或下一步动作的重大变化。
>
> **它不是 Execution Authority，也不替代 live GitHub / real runtime / Evidence。**
> 事实冲突时仍按：real environment / current Evidence > GitHub live state > current-state docs > historical records。
>
> 时间统一使用 **UTC+8**。历史事实不为“看起来一致”而重写；如发现错误，追加更正记录。

## Current snapshot — 2026-10-03 19:43 +08

- **main:** `7e7aedd556eac986210f1a5474c7b31e04d37a29`
- **OPEN PR:** 27 个。当前需要优先理解的是 #376（HK 实跑候选）、#377（#376 Candidate Admission 记录）、#368（本日志/README 导航）；其余 OPEN PR 仍应逐案判断，不能仅按编号推断有效性。
- **HK-STAGING active runtime:** 已部署 PR #376 head `9f889acfcd36a82c7565b723261ee046c2615314`
- **Running image:** `sha256:01632507d0d3b60054c1d9e56c5338b51085a69094b9beb4773e330c21191754`
- **Live DB revision:** `0145_source_latest_index`；本次 PR #376 部署 **未执行 migration**
- **Business services:** 8 个目标业务服务均已切到同一 PR #376 image；API `/health` 正常，`/openapi.json` 返回 200，API RestartCount=0
- **Rollback:** 上一已知可用 PR #320 image `sha256:26c95472d494100dc5365b031335670b57570b86ac50fb1b4ebd161d7933530b` 仍保留在 HK，可按记录路径回滚
- **Important split:** PR #376 **已在 HK-STAGING 实跑并 VERIFY_OK，但仍是 OPEN / Draft / 未合并**；当前 `main` 与实际运行 Candidate 不是同一身份
- **Runtime pointer warning:** [docs/canonical-baseline/CURRENT_HK_RUNTIME.json](../canonical-baseline/CURRENT_HK_RUNTIME.json) 目前仍指向 2026-10-02 的 PR #320 runtime，已经落后于 2026-10-03 的 PR #376 实跑状态；执行判断应以 real runtime / current Forge Evidence 为准，等待后续 reconciliation
- **Current-state warning:** `GO_CURRENT_STATE.md` / `CONTEXT_CHECKPOINT.json` 仍绑定 2026-09-14 快照，不能单独代表今天状态
- **Acceptance boundary:** 本次事实证明的是 delivery correctness（指定 PR #376 Candidate 已安装并通过运行时 VERIFY）；它不自动等于全部产品/业务验收完成

## What belongs here

记录：

- `MAIN`：会改变当前源码/架构理解的重要 merge；
- `PR`：重要候选的 opened / superseded / closed / merged 等状态变化；
- `RUNTIME`：HK-STAGING 实际 deploy / rollback / image / migration / runtime pointer 变化；
- `CANDIDATE`：部署候选身份或 lineage 发生实质变化；
- `DECISION`：会改变后续工程路线的明确决定。

不记录：普通 CI 重跑、评论、review 往返、仅格式/措辞调整、临时分支和没有改变项目事实的噪音。

单条尽量控制在 1–3 行，并附 PR / commit / canonical pointer，方便从这里跳回证据。

## Timeline

### 2026-10-03

- **19:43 +08 · SNAPSHOT** — live GitHub：main=`7e7aedd5`，OPEN PR=27；HK-STAGING 当前实际运行 PR #376 head `9f889acf` / image `sha256:01632507...`。仓库 `CURRENT_HK_RUNTIME.json` 仍停在 PR #320，形成新的 runtime-pointer drift。
- **16:55 +08 · RUNTIME** — GO Forge 完成 PR [#376](https://github.com/yuguangzhi3836-glitch/GO/pull/376) 的实际 HK-STAGING 部署。8 个业务服务切到 image `sha256:01632507...`；sealed VERIFY 返回 `VERIFY_OK`，API healthy，DB 仍为 `0145_source_latest_index`，本次无 migration；caddy / redis 未变，Production 未触碰。上一 PR #320 image `sha256:26c95472...` 保留为 recovery point。
- **16:12 +08 · CANDIDATE** — PR [#377](https://github.com/yuguangzhi3836-glitch/GO/pull/377) 建立，用于保存 PR #376 的 Candidate Admission / 零迁移候选事实。它本身仍是 OPEN / Draft / 未合并，不等于部署动作。
- **14:14 +08 · PR** — PR [#376](https://github.com/yuguangzhi3836-glitch/GO/pull/376) 建立：以 PR #320 为直接 base，保留 #365 修复并整合 C/B 注册分阶段门禁；候选保持 DB head `0145_source_latest_index`，声明零 schema migration。
- **12:37 +08 · MAIN** — PR [#374](https://github.com/yuguangzhi3836-glitch/GO/pull/374) 合并；B 端账号注册、主体审核与合同门禁拆分进入 main。main 推进到当前 `7e7aedd5...`。
- **12:30 +08 · MAIN** — PR [#375](https://github.com/yuguangzhi3836-glitch/GO/pull/375) 合并；C 端 GO ID 创建与 Personal Travel Vault 后置授权边界进入 main。
- **00:29 +08 · SNAPSHOT** — 建立本日志。彼时 live GitHub：main=`05b108cc`，OPEN PR=9；HK-STAGING 运行 PR #320 head `eeafca1b`。该记录保留为当时真实快照，已被上面的 19:43 snapshot supersede。

### 2026-10-02

- **23:21 +08 · MAIN** — PR [#312](https://github.com/yuguangzhi3836-glitch/GO/pull/312) 与 [#309](https://github.com/yuguangzhi3836-glitch/GO/pull/309) 先后合并；main 最终推进到 `05b108cc63b008aad4da732ac97c7e453cf59220`。内容为 GO Forge Task Consumer/CC 兜底方案与常驻 AI Operator 路线冻结，属于部署辅助接口/方案记录，不等于 HK 新部署。
- **21:28 +08 · RUNTIME / MAIN** — PR [#328](https://github.com/yuguangzhi3836-glitch/GO/pull/328) 合并，把 canonical HK runtime pointer 对账到当时已实跑的 PR #320：image `sha256:26c95472...`，DB `0145_source_latest_index`，1059 OpenAPI paths。该 merge **只校准指针，没有再次部署**；该指针随后被 10/03 PR #376 的真实部署 supersede，但仓库文件尚未再次 reconciliation。
- **21:13 +08 · MAIN** — PR [#329](https://github.com/yuguangzhi3836-glitch/GO/pull/329) 合并：最小 C01 GitHub Issue Consumer 进入 main，默认 disabled。
- **20:48 +08 · MAIN** — PR [#327](https://github.com/yuguangzhi3836-glitch/GO/pull/327) 合并：C01 Issue → `AI_TASK_V1` ingress 进入 main，默认 shadow/disabled。
- **16:49 +08 · RUNTIME** — GO Forge 将 admitted PR [#320](https://github.com/yuguangzhi3836-glitch/GO/pull/320) candidate 部署到 HK-STAGING；后续 formal deployctl VERIFY=`VERIFY_OK`。该 runtime 在 10/03 16:55 被 PR #376 supersede。

### 2026-10-01

- **RUNTIME · HISTORICAL** — canonical runtime pointer 保存的上一运行版本为 PR [#298](https://github.com/yuguangzhi3836-glitch/GO/pull/298) head `e109af4dc4ae84f27f63d0104aa42c8d6b64b34d` 对应 image；它在 10/02 被 PR #320 runtime supersede。PR #298 当前为 CLOSED / 未合并。

---

## Maintenance rule

更新本文件时先重新读取 live state，不从旧聊天或本文件反推现状。若没有重大变化，**不要为了“每天有内容”而写日志**。
