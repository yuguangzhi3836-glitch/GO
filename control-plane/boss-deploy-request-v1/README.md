# Boss 部署请求入口 V1（Bridge 1.7 候选）

本候选补齐 `HK_STAGING_DEPLOY` 的 Request → 指挥中心校验 → 签名 Task 入口，并增加一条**只读**的 `CONTROL_PLANE_HEALTH` 探活路径（见下节）。源码开发已获用户授权；本包默认关闭部署入口，尚未安装、启用或向香港发送任何任务。它不改变香港 Agent、执行器、应用候选或 Production。

**DEPLOY 请求只有五个公共字段。** 计划不再由任何人登记：指挥中心在收到合法 DEPLOY Request 时，从它自己已经持有的事实（候选 admission、root-only 的 live 基线、它自己签发的 TEST_PR / CANARY / 预检 VERIFY）派生出计划，先在内存里过一遍校验器，再原子登记、回读、签发 Task。聊天输入不能指定镜像、服务、命令、签名、审批或执行路径，**也不能指定计划名**。

## 提交部署请求

入口安装并获准启用后，在 `chenzhenxi1-sudo/go-control-tasks` 创建同仓库、目标 `main`、非 Draft 的 Request PR，仅新增 `requests/<request_id>.json` 一个文件。**发布 Request PR 会被持续轮询处理，不需要合并；只能在已授权的部署窗口创建。** 本仓库中的源码 Draft PR 不会触发香港。

```json
{
  "schema_version": "1",
  "request_id": "boss-deploy-request-EXAMPLE",
  "action_id": "HK_STAGING_DEPLOY",
  "environment": "HK-STAGING-01",
  "requested_at": "2026-09-17T00:00:00Z"
}
```

上例时间已固定为示例时间，不可用作正式请求；且**这份 Request 自己就是审批**：它的作者（GitHub 认证）是
`approved_by`，平台的 `created_at` 是 `approved_at`，它的 canonical 摘要是 `request_sha256`——所以它必须在
CANARY 与预检 VERIFY 之后才发布。实际请求时间使用当时 UTC；请求最多 4 KiB、有效 15 分钟。未知字段、重复 JSON 键、路径穿越、Production、关闭/Draft/跨仓库 PR、变化的 PR HEAD 均拒绝。正式入口还需完成 [安装交接](INSTALL_HANDOFF.md) 中的前置配置。

## 服务端处理

1. 按 PR 的真实共同祖先确认只新增一个 Request 文件，核对文件名、PR 状态、目标仓库、分支和固定 HEAD。
2. 检查部署开关；**派生**计划并原子登记到 `/etc/go-command-center/deployment-plans-v1/<plan_id>.json`，再从磁盘回读校验。计划、公钥、配置及其直接目录必须由 root 持有且不允许组/其他用户写入，拒绝符号链接；已存在且字节不同的计划文件拒绝覆盖。
3. 用既有指挥中心公钥核验审批和 CANARY/VERIFY Task，用既有香港公钥核验回执。源码提交、应用树、源码树 SHA256、部署包 SHA256、镜像 ID/digest、当前镜像、固定八服务均绑定在审批计划中。具体见 [计划合同](PLAN_CONTRACT.md)。
4. CANARY 必须针对同一候选且不超过 30 分钟；只读 VERIFY 必须针对预期当前镜像且不超过 5 分钟；发布任务的有效期受审批和只读核验窗口共同约束。此外必须有一份**本候选的签名 TEST_PR**：它证明部署将加载的产物就是这份源码封存出来的（源 commit、产物身份、封存包内容地址、封存已 proven 逐字段相等），且该证明**不设时效**——候选不可变，绑定是内容绑定。三端 UX / 六品类闭环 / Sealed Node / 最终发布四项**不再是本入口的阻断项**：它们是上游的产品发布结论，CC 不重新评判（见 `PLAN_CONTRACT.md` 与 `#103` Authority Boundary）。
5. 每个计划和每个审批只消费一次。先将原始签名 Task 和版本绑定以锁、原子替换和 fsync 持久化，再复核开关、PR HEAD、计划和时效，最后通过既有 Tasks writer 发布并逐字节回读。发送结果不明时只查询原 Task，绝不自动重签或重发。

保留既有 VERIFY 与 TEST_PR 请求格式、固定 TEST_PR 构建配置、签名和证据通道；兼容 v2/v3 配置。v4 配置的 action 合同自 **Bridge 修订 `1.6.0-canary-channel`** 起固定为五项：`HK_STAGING_VERIFY`、`HK_STAGING_TEST_PR`、`HK_STAGING_DEPLOY`、`HK_STAGING_CANARY`、`CONTROL_PLANE_HEALTH`，比较方式是**整份列表精确相等**而非成员判断，因此增删动作需要新的 Bridge 修订，不能靠改一个 root 文件蒙混。**不再有部署开关**：v4 配置只声明*如何*授权部署（`deployment_authorization`，本修订只实现 `request` 一种取值），而这个声明本身不授予任何权限——转成 `request` 什么也拿不到，因为一次部署仍必须由授权身份开的合法 Request、新鲜的 canary 与预检、以及精确的候选共同成立。取任何别的值只会拒绝 DEPLOY Request 而不影响只读探活，因此它仍是一个应急停止阀，而不是每次部署都要人工掰一次的前置开关。旧单次/预演模式仍限定 VERIFY，不能把 DEPLOY 降格为 VERIFY。

### DEPLOY 请求与派生计划（Bridge 1.8 新增）

- Request 只有五个公共字段；**没有 `plan_id`**。一个仍带 `plan_id` 的 Request 按字段集合不等拒绝（`schema_fields`）。
- 计划名是函数而不是选择：`hkstg-<source_commit 前 12 位>-<image 前 12 位>-<canary release_id 的 sha256 前 12 位>`。
  校验器重算它，因此一个"没按事实派生"的名字会被 `plan_id_not_derived` 拒绝。
- 派生的输入全部来自指挥中心已经持有的东西，没有任何一项来自 Request；`candidate` 块还必须与签名 TEST_PR 回执逐字段相等。
- 计划**先在内存里校验再写盘**，因此不会留下一个通不过自己那关的文件；已存在且字节不同则拒绝覆盖。
- 预检 VERIFY 是**现场**的：它只能在 DEPLOY Request 之前几分钟内跑，且审批（也就是 Request）必须晚于两份回执。

### CANARY 请求（Bridge 1.6 新增）

CANARY 与 VERIFY 同形：Request 只有五个公共字段，**没有任何调用者可控参数**——没有 image、没有 package、没有 service、没有 path、没有 env、没有 command、没有 plan_id、没有 pr_number。Task 的四个参数（`release_id`、`candidate_image_id`、`candidate_package_sha256`、`expected_current_image_id`）全部读自 root-only 权威文件 `/etc/go-command-center/boss-request-canary-baseline-v1.json`（`root:root 0600`，操作人员写入，Bridge 只读）。该文件缺失、不可读、JSON 非法、字段多余或缺失、镜像不是 `sha256:<64hex>`、包不是 64 位十六进制或环境不符，一律以 `invalid_canary_authority` **拒绝**（是拒绝，不是异常——轮询 tick 不会因此死掉）。

CANARY **不受部署授权约束**：它不触碰业务运行时（隔离容器、无网络、只读根、drop 全部能力），而且它正是部署计划必须先引用、再登记的那份证据——若用部署开关去拦它，计划就永远无法成立。CANARY 也不读取部署计划、不占用 approval / plan 预算、不能变成 VERIFY / TEST_PR / DEPLOY / ROLLBACK。`HK_STAGING_ROLLBACK` 仍然不可请求。

## 只读 liveness 探活（`CONTROL_PLANE_HEALTH`）

这条路径不是为了放宽权限，而是为了让 `hk_agent_online` 能由**签名证据**回答，而不是由「能不能连上 / HTTP 是不是 200 / 过去成功过」猜出来。

- Request 只允许五个公共字段，**没有任何调用者可控参数**：没有 image / service / path / env / command / plan_id / pr_number。Task 的 `parameters` 是模块常量 `{}`（复制而非推导）。
- 用既有 Task 身份签名：签的是**Task 身份**，不是 Human Approval。它不授权任何执行，不参与 DEPLOY armed / 审批计划 / 发布预算，不读写部署授权状态。
- 派发是**显式且 fail-closed** 的：`derive_formal_task` 只认四个具名动作，其余一律拒绝。此前未具名动作会落进 `derive()`，也就是**静默变成 VERIFY**——该 fallthrough 已消除，并有测试断言。
- 既有三个动作的语义、权限与 gate **一字未改**，并有回归断言。

```json
{
  "schema_version": "1",
  "request_id": "liveness-control-plane-health-EXAMPLE",
  "action_id": "CONTROL_PLANE_HEALTH",
  "environment": "HK-STAGING-01",
  "requested_at": "2026-09-15T12:00:00Z"
}
```

请求由 `control-plane/agent-liveness-producer-v1` 按 policy 生成（30 分钟一桶，桶内幂等），由运维接线脚本发布为 Request PR。它不能表达 VERIFY / TEST_PR / DEPLOY / ROLLBACK，也无法与它们互相转换。

## 测试与证据边界

```sh
python -m pip install cryptography==46.0.0
python control-plane/boss-deploy-request-v1/run_checks.py /tmp/go-deploy-entry-checks
```

35 项新检查 + 35 项原有 Bridge 回归：真实临时 Ed25519 签名、审批/版本/证据拒绝场景、原始香港适配器的 DEPLOY_RECORD_V2 格式、持久化重放、双进程去重、发送中断恢复、VERIFY/TEST_PR 兼容、主分支前进后的 Request 差异识别，以及只读 liveness 的负向断言（带参数的健康请求拒绝、错环境拒绝、未知动作拒绝、健康不能变成 VERIFY/TEST_PR/DEPLOY/ROLLBACK、健康不参与 DEPLOY armed、action 合同必须精确四项）。测试进程禁止网络、运行时密钥/状态路径和非本地 Git 子进程。CI 依赖安装和源码/产物传输由外围 GitHub Actions 完成，不宣称整个 runner 无网络。

香港执行使用 FakeExecutor；这些检查不能证明真实 Docker 切换、银行结算或业务发布通过。正式异镜像部署 E2E 继续 **NOT_PROVEN**。现有应用候选有任何 HOLD 时本入口拒绝签发部署。

## 文件与来源

- `go-boss-request-bridge`：从固定 TEST_PR 集成候选扩展的完整 Bridge；保留现有行为，补入 DEPLOY 与只读 `CONTROL_PLANE_HEALTH`。
- `go_deploy_request.py`：计划、审批、签名回执及固定合同校验；`--check-plan <id> --approval-identity <login> --request-sha256 <hex>` 只读复核一份已派生的计划，不签发 Task。两个附加参数从 Bridge ledger 取，不由计划自己提供。
- `plan_derivation.py`：把候选 admission、root-only 的 live 基线、签名 TEST_PR 与 Bridge 自己签发的 CANARY / 预检 VERIFY 连接成计划；只做抽取与连接，实质性判断全部留给校验器。
- `config.json`：v4 模板，action 合同**五项**，部署关闭。
- `tests/test_deploy_entry.py`、`run_checks.py`：隔离校验；使用仓库中原始香港适配器，未修改香港代码。
- `PROVENANCE.json`、`SHA256SUMS`：不可变来源及交付文件校验。
- `INSTALL_HANDOFF.md`、`PLAN_CONTRACT.md`：运维接入与计划登记要求。

`command-center/` 和 `hk-staging/` 的既有运行档案保持原样。候选源码身份与运行版本身份分开记录；本包存在不等于入口已接通。
