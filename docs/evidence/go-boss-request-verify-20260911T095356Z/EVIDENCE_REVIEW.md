# 过期 VERIFY 取证归档与镜像时间线

- 目标任务：`go-boss-request-verify-20260911T095356Z`
- 环境：`HK-STAGING-01`
- 整理日期：2026-09-12（北京时间）
- 核对的 GO main：`1d8bebac37fcc6f0360b17891aa49eb6e70b5f96`
- 状态：`PARTIAL_ARCHIVE / RAW_TASK_EVIDENCE_NOT_OBTAINED / ROOT_CAUSE_UNKNOWN`
- 本文件是来源索引、静态核对和缺口记录；不是香港运行回执、签名 Evidence 或现场取证完成证明。

## 本轮已完成的工作与检索范围

只读取了用户选定的 GO 仓库及 GO Command Center 对话材料。已核对 main 完整文件树（907 项，GitHub 标记未截断）、107 个分支引用、相关公开于本私有仓库的 PR 元数据、固定提交中的配置/Agent/Bridge 源码及运行说明。精确任务 ID 的默认分支搜索未返回结果；Personal Context 未找到匹配的项目对话。搜索索引和分支名称不能证明所有历史提交均无记录，本轮不作此绝对断言。

main 快照未提供目标任务的 Agent ledger 行、接收/拒绝/执行/上传原始日志或签名 Evidence。本轮没有取得香港或指挥中心服务器上的原始导出。外部任务/证据仓库链接仅作为用户已提供陈述的定位信息保留，未扩大当前来源范围去访问它们。

已取得的原始仓库文件在本分支父提交中完整保留，见下方精确提交链接与本轮按所取 UTF-8 字节计算的 SHA256。没有重复生成、修改或替代任何运行证据。

## 镜像时间线：已核验与陈述分开

| 时间（北京时间） | 材料 / 身份 | 证据级别与限制 |
|---|---|---|
| 2026-09-11 14:25:10 | 用户提供的香港只读补证称八服务仍运行 R3.1.5，Image ID 为 `sha256:66c540878ff5dd8d2d089059288c3d9f0c45f880514f7b053bd50defb9e8c324` | REPORTED CLAIM。未取得这次容器检查的完整原始输出，不代表当前实时状态。 |
| 2026-09-11 15:16:13 | 项目对话称最近成功 VERIFY 对应任务 `go-boss02-post-rollback-verify-20260911T071429Z`，镜像为 `66c540…c324` | REPORTED CLAIM。签名 Evidence 原件未在本轮取得，未独立验签。GO 归档配置明确引用同一 Evidence commit/path，见下文。 |
| 2026-09-11 17:53:56–18:08:56 | 项目对话称目标任务在此有效窗口内，预期镜像为 `3a109…`；任务提交 `d336cf07f7ec2a3a06074c00a2bd4e74ada0b962` | REPORTED CLAIM。未取得原始签名 Task、完整旧镜像 ID 或创建时配置，不能计算其完整 SHA256 或断定拒绝原因。 |
| 2026-09-11 18:17 | 对话称未发现目标任务签名回执，且有效期已过 | REPORTED CLAIM。未收到回执不能推出未接收、未执行或执行失败。 |
| 2026-09-11 23:10:08 | GO 提交 `d5158fbdbad59abe471aceee71e107f95c056b4e` 归档指挥中心配置/源码 | VERIFIED REPOSITORY EVIDENCE。[提交](https://github.com/yuguangzhi3836-glitch/GO/commit/d5158fbdbad59abe471aceee71e107f95c056b4e)的提交时间已读取；归档 VERIFY 基线明确为完整 `66c540…c324`。提交时间不是该配置安装/启用时间。 |
| 2026-09-12 00:12:40 | GO 提交 `1d8bebac37fcc6f0360b17891aa49eb6e70b5f96` 归档香港源码与配置 | VERIFIED REPOSITORY EVIDENCE。[提交](https://github.com/yuguangzhi3836-glitch/GO/commit/1d8bebac37fcc6f0360b17891aa49eb6e70b5f96)的提交时间已读取；清单记录镜像 `66c540…c324`、Agent 0.5.7-rebuilt、Executor 0.4.3-rollback-runtime。现场采集和安装状态仍是归档者陈述。 |

归档的 [VERIFY 基线配置](https://github.com/yuguangzhi3836-glitch/GO/blob/1d8bebac37fcc6f0360b17891aa49eb6e70b5f96/command-center/config/boss-request-verify-baseline-v1.json) 包含：

- `image_id=sha256:66c540878ff5dd8d2d089059288c3d9f0c45f880514f7b053bd50defb9e8c324`
- `evidence_task_id=go-boss02-post-rollback-verify-20260911T071429Z`
- `evidence_commit=2dbbdefaf7996e5f9222669929eee79eefabae56`
- `evidence_path=evidence/go-boss02-post-rollback-verify-20260911T071429Z-VXHLNF5J-y95xwF89A_tuEfg9tVulKt1.json`

静态核对：归档 Bridge 的 `derive()` 将基线的 `image_id` 同时写入 Task 的 `candidate_image_id` 和 `expected_current_image_id`。这证明当前归档代码的参数来源；不能反推 17:53:56 实际运行的 Bridge 字节或配置。旧 `3a109…` 基线与后续 `66c540…` 归档的差异保留为待核对项，实际配置变更时间、批准依据和本次未回传原因均为 UNKNOWN。

用户提供但本轮未访问的原件定位：
- [目标 Task 定位](https://github.com/chenzhenxi1-sudo/go-control-tasks/blob/d336cf07f7ec2a3a06074c00a2bd4e74ada0b962/tasks/go-boss-request-verify-20260911T095356Z.json)
- [历史 VERIFY Evidence 定位](https://github.com/chenzhenxi1-sudo/go-control-evidence/blob/2dbbdefaf7996e5f9222669929eee79eefabae56/evidence/go-boss02-post-rollback-verify-20260911T071429Z-VXHLNF5J-y95xwF89A_tuEfg9tVulKt1.json)

## 已直接检查的源码事实及取证限制

以下结论只针对固定归档源码，未运行 Agent、Bridge、Executor 或其自测。

1. Agent 默认 ledger 路径为 `/var/lib/go-hk-agent/ledger/agent.sqlite3`，归档 systemd ExecStart 未覆盖 `--ledger`。相关表为 `attempts` 与 `processed`。
2. `validate()` 在 `claim_attempt()` 之前执行。校验阶段抛出的拒绝在循环内仅增加 `rejected` 汇总计数；只有已经 claim 的任务才调用 `fail_attempt()` 写诊断。因此，缺少目标 ledger 行不证明 Agent 未读取任务；汇总拒绝计数也不能归因于本任务。
3. 签名 Evidence 经上传成功后才写入 `processed`。没有 completed 行不证明执行器未运行。应联合检查目标 `attempts` 行中的 `status/claimed_at/diagnostic` 与已有原始输出。
4. `push_evidence()` 把文件写入 `TemporaryDirectory(prefix="go-hk-agent-")` 下的 `evidence/evidence/<task_id>-<nonce>.json`。正常退出该上下文时临时目录会清理；不保证上传失败后留有本地原件。不得补造或重新签名缺失 Evidence。
5. Git 失败在当前归档封装中转为 `GITHUB_TRANSPORT_REJECT`，未保留底层 Git stderr。若只剩该诊断，不能据此区分网络、认证或远端拒绝。诊断中的 stdout/stderr hash 针对脱敏且最多截取 8192 字符后的内容，不是完整原始命令输出的哈希。
6. Bridge 默认 ledger 为 `/var/lib/go-command-center/boss-request-bridge-v1/ledger.json`；归档 service 未覆盖 `--ledger-root`。目标 request 对应记录内可能包含派生 Task 和发布状态/commit，须取已有记录核对，不能调用 `--once` 重新处理。

## 尚缺的原始材料

| 材料 | 当前状态 | 需要保留的关联信息 |
|---|---|---|
| 目标 Task 原始签名对象 | NOT_OBTAINED | 完整旧镜像 ID、nonce、issued_at/expires_at、参数、签名、原始文件 SHA256 |
| Agent `attempts/processed` 目标行 | NOT_OBTAINED | task_id、nonce、attempt_number、status、claimed_at/processed_at、diagnostic、evidence_ref；读取时间与来源 |
| 香港 service/timer 接收、拒绝、执行、上传已有日志 | NOT_OBTAINED | 2026-09-11 17:53:56–18:08:56；必要时两侧各扩展五分钟；原时间戳、退出码、已有输出 |
| 已生成 Evidence 或已有上传 commit | NOT_OBTAINED | 原始字节、完整 SHA256、签名验证材料、目标分支及上传结果；没有原件保持 UNKNOWN |
| Bridge 目标请求 ledger 与创建时配置/运行指纹 | NOT_OBTAINED | 派生/发布状态、完整 Task、task_commit、配置生效时间，解释 `3a109… → 66c540…` 的时间线 |

NOT_OBTAINED 表示本次未取得，不是服务器不存在。不得以当前容器状态重建历史结果。若只能取得脱敏副本，应同时保留原件来源/原件哈希、脱敏说明与副本哈希；不能把修改后的 JSON 称为可验签原件。不得上传密码、Token、私钥、完整环境文件或带凭据 URL。

## 唯一下一允许动作

由指挥中心在已有获批只读取证范围内，汇集上述目标任务的已有记录及可用 Evidence 原件，连同完整 SHA256 和采集时间归档到 GO，然后核对镜像基线时间线。本报告没有发出新任务，也没有扩大服务器或外部仓库访问授权；缺少既有入口/材料时记录 ACCESS_UNAVAILABLE 或 NOT_OBTAINED。

## 边界及门禁

- 原任务不修改、不延长、不重签、不重发；不手动启动 Agent/Executor，不重跑 VERIFY。
- 不启动 TEST_PR，不安装新处理器/构建配置，不添加 Deploy Key，不构建香港镜像。
- PR #42 仍为 Draft，`MERGE=NO`、`DEPLOYMENT=NO`；本归档不修改候选、PR #42 或 main。
- 不执行 CI、合并、部署、迁移、回滚或 Production 操作。
- DEPTH40 运行包镜像 `9ec6eb…5057b` 与香港历史归档 `66c540…c324` 分开记录。
- 控制通道目标任务结果/根因 UNKNOWN；三端真实 UX/登录、六品类真实闭环、Sealed Node、最终发布不因本次归档转为 PASS。已有源码、测试与历史证据保持原样。

## 本轮读取的原始仓库文件与 SHA256

下表哈希由本轮对 GitHub 返回的完整 UTF-8 文件内容计算。原文件已经保存在本分支父提交，不复制为伪装现场新证据。Bridge 与 Agent transport 计算值分别与已有清单声明一致；这仅证明归档文件字节身份，未验证现场安装绑定。



| 原始文件（固定提交） | SHA256 | 字节数 |
|---|---|---:|
| [command-center/config/boss-request-verify-baseline-v1.json](https://github.com/yuguangzhi3836-glitch/GO/blob/1d8bebac37fcc6f0360b17891aa49eb6e70b5f96/command-center/config/boss-request-verify-baseline-v1.json) | `52cb3f9935634dd94205734df6769f8a892a88c7b551137f581bbb34f607be18` | 372 |
| [command-center/source/bridge/go-boss-request-bridge](https://github.com/yuguangzhi3836-glitch/GO/blob/1d8bebac37fcc6f0360b17891aa49eb6e70b5f96/command-center/source/bridge/go-boss-request-bridge) | `3a23d4fb5ab7946fc6dcca15fb3450d14f6f896f6c2289ad3a0aa0e8bf0fc129` | 28977 |
| [command-center/systemd/go-boss-request-bridge.service](https://github.com/yuguangzhi3836-glitch/GO/blob/1d8bebac37fcc6f0360b17891aa49eb6e70b5f96/command-center/systemd/go-boss-request-bridge.service) | `937c8a2588a0b3d82a2b3b55a8ca453811adcbaa55f1b5a01e88add545e4e459` | 519 |
| [hk-staging/source/agent/hk_agent/transport.py](https://github.com/yuguangzhi3836-glitch/GO/blob/1d8bebac37fcc6f0360b17891aa49eb6e70b5f96/hk-staging/source/agent/hk_agent/transport.py) | `4301a7e920fc25d98ea8403ac00ebbdb6a864bcb092d33caf343ad28603ff490` | 19183 |
| [hk-staging/source/agent/hk_agent/deployment_actions.py](https://github.com/yuguangzhi3836-glitch/GO/blob/1d8bebac37fcc6f0360b17891aa49eb6e70b5f96/hk-staging/source/agent/hk_agent/deployment_actions.py) | `7400ef03caf9473db73eccca5206233c81707ae742547489f0ed93728e5b323e` | 14089 |
| [hk-staging/systemd/go-hk-agent.service.txt](https://github.com/yuguangzhi3836-glitch/GO/blob/1d8bebac37fcc6f0360b17891aa49eb6e70b5f96/hk-staging/systemd/go-hk-agent.service.txt) | `0dde86002a0a953734d6dd2e1a10123a23180aac6c5e2ce493695f296168ce23` | 691 |
| [hk-staging/systemd/go-hk-agent.timer.txt](https://github.com/yuguangzhi3836-glitch/GO/blob/1d8bebac37fcc6f0360b17891aa49eb6e70b5f96/hk-staging/systemd/go-hk-agent.timer.txt) | `54de6177776f0be138eea70e4a6a87a59321775f53c051979fbf45be93ca5c82` | 225 |
| [hk-staging/BASELINE_MANIFEST.md](https://github.com/yuguangzhi3836-glitch/GO/blob/1d8bebac37fcc6f0360b17891aa49eb6e70b5f96/hk-staging/BASELINE_MANIFEST.md) | `e3b6d6be8b9a4eb0720092c32b402f04b59ed2e5a11cea7390aa4ed40ae8bfb7` | 1675 |
| [hk-staging/audit/20260911/COLLECTION_SUMMARY.md](https://github.com/yuguangzhi3836-glitch/GO/blob/1d8bebac37fcc6f0360b17891aa49eb6e70b5f96/hk-staging/audit/20260911/COLLECTION_SUMMARY.md) | `041410ec6553b25d4a6cd6feb270a12070e4f220a3d14b59fef2f5f314e19ad5` | 756 |
