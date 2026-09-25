# GO C13/C14 验收规则修订稿

日期：2026-09-25　状态：**Owner 已确定架构口径；本 PR 仅记录拟议规则，运行控制面尚未安装**

## 2026-09-25 Owner 更正：独立 AI 意见，不要求审核组签名

C13 是开发侧独立 AI 审核组；C14 是运行侧独立 AI 审核组。两组只需出具真实独立的审核意见，不要求真人审核者、审核组私钥、AI 数字签名或额外签字。此前将 C13 P-256 签名／审核组签名身份登记作为必备准入条件的规则在此撤销；已有真实独立意见无需补签名。

独立性依据实际 AI 执行记录及与实现者、另一审核组的分离核实，不以 GitHub 账号数量判断。意见记录原文或原文引用、候选 SHA、application tree、冻结范围、证据引用及 PASS_SCOPED／FAIL／BLOCKED；源码自测或绿色 CI 不得冒充独立意见。系统可自动保存结构化记录与摘要以便读回，这不是审核组签名或新的人工审批。

按 Owner 确定的项目责任安排，部署决定和责任由向指挥中心下达部署指令的真人承担；审核组只出意见。Task、香港 Evidence 和指挥中心 HSM 回执的机器签名仍用于来源核验和防篡改，不表示 AI 承担责任，也不替代真人部署指令。取消 AI 签名要求不取消真实测试、执行隔离和机器通道完整性检查。

源码入口：C13 使用无签名的 `GO_C13_INDEPENDENT_OPINION_V2`；C14 用 `c14_review.conclude()` 将无签名独立意见与已验证的实际 Task／Evidence／回执绑定。机器测试通过但缺少独立意见，不能报告 C14 PASS；AI 意见 FAIL/BLOCKED 同样不能被机器绿色结果覆盖。

## 一、职责与顺序

1. 开发 Cell 完成代码和必要的本地调试，提交固定 Candidate。开发者本地测试只供调试，不能签发正式验收结论。
2. **C13 负责开发侧首次正式测试和准入判定。**C13 在固定 Candidate SHA 与 `application/` 子树上执行约定测试，检查范围、缺口及原始证据，给出 `PASS_SCOPED` 或 `FAIL/BLOCKED`。绿色 CI 可作为 C13 的执行工具及证据，但不能由开发 Cell 的自测自动冒充 C13。C13 与该 Candidate 的实现者身份分离。
3. **指挥中心下达香港 C14 复测指令。**只有 C13 对固定 Candidate 首验通过后，Command Center 才能通过现有香港任务通道向指定隔离 Runner 派发独立的 C14 复测动作。指令固定 Candidate commit SHA、`application/` tree、C13 准入记录、冻结测试范围、任务身份及证据回传目标；任务不得被解释为香港部署指令。
4. **香港隔离 C14 负责独立复测并上传结果。**Runner 核对指令及候选身份，在与运行中的香港 Staging 业务服务及数据隔离的环境中重新检出并执行冻结测试。C14 执行者与开发 Cell、C13 首验执行者分离；通过受限回传通道上传结构化 PASS/FAIL/BLOCKED 结论、测试命令、原始输出、JUnit、环境信息、证据文件和逐项摘要，并关联任务 ID、Candidate SHA、`application/` tree 与 C13 准入记录。回传失败、材料不全或身份不符一律记为未完成，不得以口头结果代替。
5. **Command Center 负责直接接收结果与发布控制。**它从受限回传存储读回香港 Evidence 和三份原始工件，核对任务身份、同一 Candidate SHA/tree、冻结测试范围、C13 摘要、Runner 来源、Evidence 原文 SHA-256 与工件摘要；全部通过后，只有 Command Center 才能原子写入并读回签名的 `GO_C14_EVIDENCE_RECEIPT_V1`。回执以 task ID/nonce 为唯一键，记录 `EVIDENCE_VERIFIED`、`COMPLETE` 与实际 `PASS_SCOPED/FAIL/BLOCKED` verdict；其中 `COMPLETE` 只表示指挥中心已记录核验结论，不表示 C14 通过。香港 Runner 只能回传 Evidence/工件，不能写回执；回传缺失、篡改、读回不一致或绑定不符时没有回执、维持 HOLD，不得用人工转述替代。C14 AI 组还需对同一任务、证据及回执形成独立意见；技术回执自身不是 AI 审核意见。随后由真人下达部署指令，并依据现行发布门禁分别决定 TEST_PR、CANARY、VERIFY、DEPLOY 等动作。C13/C14 的 PASS、receipt 或签名均不能直接成为合并或部署许可。

简式流程：固定 Candidate → C13 首次正式验收 → Command Center 指令香港隔离 C14 → C14 独立复测并上传结果 → Command Center 读回核验并控制发布。

## 二、固定身份与拒绝条件

- C13 和 C14 都须绑定完整 Candidate commit SHA、`application/` 子树 Git tree、测试范围、测试/环境版本及可核查的证据摘要。根 tree 只能作为附加取证信息，不能替代 application tree。
- 候选代码、tree 或冻结测试范围发生变化，旧结论不得转用。C13 `FAIL/BLOCKED`、缺失或范围不符时，C14 派发须拒绝；C14 `FAIL/BLOCKED`、无原始证据或读回不一致时，发布准入须拒绝。
- 香港 C14 任务只能执行隔离验收；不得复用香港部署任务的 action ID、Runner 或权限，不得访问 Production、真实 OTA、真实支付或商户密钥。任务结果只回传验收证据，不得通过 C14 回传触发 CANARY、DEPLOY 或 Production。现有香港连接可承载独立受限动作，连接能力本身不表示动作已安装。
- 任务及结果的签名用于来源核验、完整性和审计，不赋予测试结论或发布权。Owner 授权的 Command Center 是发布治理 Trust Root；不要求另外建立 Owner 之外的第三方 Release Authority。

## 三、旧候选及迁移边界

- PR #229/#231 及 CCV1-137 R2–R5 以“**C14 receipt → C13 task admission**”为前提；该前提与本规则逆序。这些草稿及离线证据保留原始身份和历史价值，不得继续被解释为新流程已经验收或接通。
- PR #238/#239 的签名与公钥工作仅在与本规则相容的**任务/证据来源及防篡改**范围内评估；不得据此声称 `INDEPENDENT_AUTHORITY` 或用 receipt 签发替代 C13/C14 复测。
- 历史已签发的 C14/C13 结论只对原候选、原范围及原顺序有效；不得重贴标签为新顺序通过。历史材料不改写、不补造。
- 这份规则是待集成的变更说明。现有合同、验证入口、任务总线、隔离 Runner 与发布投影在完成相应代码和运行证据前，仍按已安装规则及 HOLD 状态处理；不得仅靠文档或离线目录替身宣称新链路可用。

## 四、可核验的设计完成条件

同一固定 Candidate 上，C13 与实现者分离并完成首验；Command Center 向香港隔离 Runner 下达受限 C14 指令；C14 与 C13/实现者分离并复测、上传原始结果；Command Center 读回并只接受两份匹配同一 SHA/tree 的原始证据且发布动作单独授权；所有不匹配、缺失、越权组合都拒绝并留审计。到此即为本架构的信任终点，不因追求更多 Authority、Signer 或审核层而继续扩展。

## 当前状态

本稿**不是**任务总线安装记录、香港 C14 执行证据、指挥中心回执路由安装记录或发布授权。R5 仍属离线目录替身测试；不得继续仅因缺少 AI 签名阻塞 C13/C14；缺少实际独立意见或真实运行证据仍须明确标记。HK/Final Release/Production 不因本次更正自动放行。没有触发 KMS 签名、真实任务派发、合并或部署。

