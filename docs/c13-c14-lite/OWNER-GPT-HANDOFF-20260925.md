# Owner / GPT 交接说明：C13/C14 Lite 方向与职责已确认

## 状态

**本文件不是二次确认请求。**

2026-09-25，陈震曦已与 Owner 电话确认 C13/C14 Lite 的“独立”边界；随后 Owner 又补充了《GO 指挥、调度及 C01–C14 团队职责统一说明》。

当前最终口径为：

- **C13 = 独立质量验收**
- **C14 = 宪法、权限、法律、监管、合同及 AI 行为规则审查**
- C13/C14 都是 GO 的长期 AI 团队角色，不等于某台服务器。
- 香港是正式现场任务的执行环境，不改变 C01–C14 的责任归属。
- “Independent”表示 fresh AI execution/context 和独立审核判断，不表示独立公司、独立云账号、独立 ECS、HSM 或外部公证机构。

因此后续 C13/C14 改造以 #247 当前 **Lite V2** 方案为主导方向。

## 给 Owner GPT 的任务

读取本 PR 后，只需要向 Owner 用白话说明：

1. 之前为什么会把“独立”做成过重的基础设施；
2. WorkBuddy 现场摸底实际发现了什么；
3. 为什么现有两台 ECS + GitHub + 现有 AI API 已经足够；
4. Owner 最新职责基线如何重新划分 C13/C14：
   - C13 做质量验收、回归、安全、恢复、跨端旅程和发布资格；
   - C14 做宪法、权限、法律、监管、合同和 AI 行为规则审查；
5. 为什么 Docker/PostgreSQL 质量沙箱应归 C13，而不是 C14；
6. GitHub、CC、HK 各自需要改多少；
7. 哪些 HSM/KMS/WIF/独立 C14 ECS 设计退出硬路径。

### 不需要做的事情

Owner GPT **不需要**：

- 再次选择 A/B/C 方案；
- 再次确认是否采用 Lite；
- 重新设计 C13/C14；
- 把 C14 再解释成第二个质量测试员；
- 再创建新的“独立基础设施”要求；
- 再为 C13/C14 引入 HSM/KMS/WIF/独立 ECS；
- 自己修改本 PR；
- 自己创建实现 PR；
- 给陈震曦侧重新派发另一套施工任务。

## 实施责任

后续实际改造由陈震曦侧主导：

- GitHub workflow / contract / CI：陈震曦 + WorkBuddy
- Command Center：陈震曦 + WorkBuddy
- HK-STAGING：陈震曦 + WorkBuddy（不改变现有香港部署执行职责；Lite 如需只增加轻量 witness）
- Owner：保留 C01–C14 职责规则、项目最终决策、API 配额/账号级资源、必要 Settings 权限、最终 merge/deployment 决策

Owner GPT 的职责是：

> **读取事实和 Owner 最新职责定义，向 Owner 解释；不是重新成为 C13/C14 架构设计者或实施者。**

## 一句话

> **方向已确认：C13 用 GitHub 临时环境做独立质量验收；C14 用独立 AI execution 做宪法/权限/法务/监管/合同/AI 行为规则审查；两者均绑定明确候选与证据，再由现有 CC/HK 做完整性见证，不新增硬件或外部信任体系。**
