# GO Update Log

> GO 主项目的短时间线入口。只记录会改变项目理解或下一步动作的重大变化。
>
> **它不是 Execution Authority，也不替代 live GitHub / real runtime / Evidence。**
> 事实冲突时仍按：real environment / current Evidence > GitHub live state > current-state docs > historical records。
>
> 时间统一使用 **UTC+8**。历史事实不为“看起来一致”而重写；如发现错误，追加更正记录。

## Current snapshot — 2026-10-03 00:29 +08

- **main:** `05b108cc63b008aad4da732ac97c7e453cf59220`
- **OPEN PR:** 9 个 — #61, #292, #293, #294, #295, #297, #316, #320, #325
- **HK-STAGING active runtime:** 已部署 PR #320 head `eeafca1b15a4754ba36a0f138a27347cbbd12c73`
- **Running image:** `go-hk-test-pr:eeafca1b15a4754ba36a0f138a27347cbbd12c73`
- **Live DB revision:** `0145_source_latest_index`，564 tables
- **OpenAPI paths:** 1059
- **Important split:** PR #320 **已在 HK-STAGING 实跑并 VERIFY_OK，但仍是 OPEN / Draft / 未合并**；当前 main 与实际运行 Candidate 不是同一身份。
- **Runtime pointer:** [docs/canonical-baseline/CURRENT_HK_RUNTIME.json](../canonical-baseline/CURRENT_HK_RUNTIME.json)
- **Current-state warning:** `GO_CURRENT_STATE.md` / `CONTEXT_CHECKPOINT.json` 仍绑定 2026-09-14 快照，不能单独代表今天状态。

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

- **00:29 +08 · SNAPSHOT** — 建立本日志。live GitHub：main=`05b108cc`，OPEN PR=9；HK-STAGING 当前运行 PR #320 head `eeafca1b`。README 最近一次实际修改仍在 2026-09-15，因此 README 内 9/13–9/14 的硬编码 runtime 数值已属于历史快照。

### 2026-10-02

- **23:21 +08 · MAIN** — PR [#312](https://github.com/yuguangzhi3836-glitch/GO/pull/312) 与 [#309](https://github.com/yuguangzhi3836-glitch/GO/pull/309) 先后合并；main 最终推进到 `05b108cc63b008aad4da732ac97c7e453cf59220`。内容为 GO Forge Task Consumer/CC 兜底方案与常驻 AI Operator 路线冻结，属于部署辅助接口/方案记录，不等于 HK 新部署。
- **21:28 +08 · RUNTIME / MAIN** — PR [#328](https://github.com/yuguangzhi3836-glitch/GO/pull/328) 合并，把 canonical HK runtime pointer 对账到已经实跑的 PR #320：image `sha256:26c95472...`，DB `0145_source_latest_index`，1059 OpenAPI paths。该 merge **只校准指针，没有再次部署**。
- **21:13 +08 · MAIN** — PR [#329](https://github.com/yuguangzhi3836-glitch/GO/pull/329) 合并：最小 C01 GitHub Issue Consumer 进入 main，默认 disabled。
- **20:48 +08 · MAIN** — PR [#327](https://github.com/yuguangzhi3836-glitch/GO/pull/327) 合并：C01 Issue → `AI_TASK_V1` ingress 进入 main，默认 shadow/disabled。
- **16:49 +08 · RUNTIME** — GO Forge 将 admitted PR [#320](https://github.com/yuguangzhi3836-glitch/GO/pull/320) candidate 部署到 HK-STAGING；后续 formal deployctl VERIFY=`VERIFY_OK`。PR #320 本身截至本日志建立时仍为 OPEN / Draft / 未合并，因此这是典型的“runtime 已前进、source main 未包含该 candidate”状态。

### 2026-10-01

- **RUNTIME · HISTORICAL** — canonical runtime pointer 保存的上一运行版本为 PR [#298](https://github.com/yuguangzhi3836-glitch/GO/pull/298) head `e109af4dc4ae84f27f63d0104aa42c8d6b64b34d` 对应 image；它在 10/02 被 PR #320 runtime supersede。PR #298 当前为 CLOSED / 未合并。

---

## Maintenance rule

更新本文件时先重新读取 live state，不从旧聊天或本文件反推现状。若没有重大变化，**不要为了“每天有内容”而写日志**。
