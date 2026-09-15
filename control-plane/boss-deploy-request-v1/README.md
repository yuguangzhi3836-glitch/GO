# Boss 部署请求入口 V1（Bridge 1.5 候选）

本候选补齐 `HK_STAGING_DEPLOY` 的 Request → 指挥中心校验 → 签名 Task 入口，并增加一条**只读**的 `CONTROL_PLANE_HEALTH` 探活路径（见下节）。源码开发已获用户授权；本包默认关闭部署入口，尚未安装、启用或向香港发送任何任务。它不改变香港 Agent、执行器、应用候选或 Production。

用户请求只携带 `plan_id`。指挥中心从固定的受保护目录读取经过人工审批、签名并绑定完整版本指纹的部署计划；聊天输入不能指定镜像、服务、命令、签名、审批或执行路径。

## 提交部署请求

入口安装并获准启用后，在 `chenzhenxi1-sudo/go-control-tasks` 创建同仓库、目标 `main`、非 Draft 的 Request PR，仅新增 `requests/<request_id>.json` 一个文件。**发布 Request PR 会被持续轮询处理，不需要合并；只能在已授权的部署窗口创建。** 本仓库中的源码 Draft PR 不会触发香港。

```json
{
  "schema_version": "1",
  "request_id": "boss-deploy-request-EXAMPLE",
  "action_id": "HK_STAGING_DEPLOY",
  "environment": "HK-STAGING-01",
  "requested_at": "2026-09-12T00:00:00Z",
  "plan_id": "reviewed-plan-EXAMPLE"
}
```

上例时间已固定为示例时间，无对应部署计划，不可用作正式请求。实际请求时间使用当时 UTC；请求最多 4 KiB、有效 15 分钟。未知字段、重复 JSON 键、路径穿越、Production、关闭/Draft/跨仓库 PR、变化的 PR HEAD 均拒绝。正式入口还需完成 [安装交接](INSTALL_HANDOFF.md) 中的前置配置。

## 服务端处理

1. 按 PR 的真实共同祖先确认只新增一个 Request 文件，核对文件名、PR 状态、目标仓库、分支和固定 HEAD。
2. 检查部署开关；从 `/etc/go-command-center/deployment-plans-v1/<plan_id>.json` 读取已审批计划。计划、公钥、配置及其直接目录必须由 root 持有且不允许组/其他用户写入，拒绝符号链接。
3. 用既有指挥中心公钥核验审批和 CANARY/VERIFY Task，用既有香港公钥核验回执。源码提交、应用树、源码树 SHA256、部署包 SHA256、镜像 ID/digest、当前镜像、固定八服务均绑定在审批计划中。具体见 [计划合同](PLAN_CONTRACT.md)。
4. CANARY 必须针对同一候选且不超过 30 分钟；只读 VERIFY 必须针对预期当前镜像且不超过 5 分钟；发布任务的有效期受审批和只读核验窗口共同约束。三端 UX、六品类闭环、Sealed Node、最终发布四项必须全部明确 PASS。
5. 每个计划和每个审批只消费一次。先将原始签名 Task 和版本绑定以锁、原子替换和 fsync 持久化，再复核开关、PR HEAD、计划和时效，最后通过既有 Tasks writer 发布并逐字节回读。发送结果不明时只查询原 Task，绝不自动重签或重发。

保留既有 VERIFY 与 TEST_PR 请求格式、固定 TEST_PR 构建配置、签名和证据通道；兼容 v2/v3 配置。v4 配置的 action 合同是固定的四项：`HK_STAGING_VERIFY`、`HK_STAGING_TEST_PR`、`HK_STAGING_DEPLOY`、`CONTROL_PLANE_HEALTH`，比较方式是**整份列表精确相等**而非成员判断，因此增删动作需要新的 Bridge 修订，不能靠改一个 root 文件蒙混。新部署动作仍只在 `deployment_requests_enabled=true` 时接受，该字段默认 false 且本次改动未触碰。旧单次/预演模式仍限定 VERIFY，不能把 DEPLOY 降格为 VERIFY。

## 只读 liveness 探活（`CONTROL_PLANE_HEALTH`）

这条路径不是为了放宽权限，而是为了让 `hk_agent_online` 能由**签名证据**回答，而不是由「能不能连上 / HTTP 是不是 200 / 过去成功过」猜出来。

- Request 只允许五个公共字段，**没有任何调用者可控参数**：没有 image / service / path / env / command / plan_id / pr_number。Task 的 `parameters` 是模块常量 `{}`（复制而非推导）。
- 用既有 Task 身份签名：签的是**Task 身份**，不是 Human Approval。它不授权任何执行，不参与 DEPLOY armed / 审批计划 / 发布预算，不读写 `deployment_requests_enabled`。
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
- `go_deploy_request.py`：计划、审批、签名回执及固定合同校验；`--check-plan <id>` 只读校验已登记计划，不签发 Task。
- `config.json`：v4 模板，action 合同四项，部署关闭。
- `tests/test_deploy_entry.py`、`run_checks.py`：隔离校验；使用仓库中原始香港适配器，未修改香港代码。
- `PROVENANCE.json`、`SHA256SUMS`：不可变来源及交付文件校验。
- `INSTALL_HANDOFF.md`、`PLAN_CONTRACT.md`：运维接入与计划登记要求。

`command-center/` 和 `hk-staging/` 的既有运行档案保持原样。候选源码身份与运行版本身份分开记录；本包存在不等于入口已接通。
