> **HISTORY / BREAK-GLASS REFERENCE**
>
> This document is not the normal current operating path.
>
> Normal deployment and inspection are defined by [`/AGENTS.md`](../../AGENTS.md) and use GO Forge.
>
> Do not issue `HK_STAGING_*` requests unless the Owner explicitly authorizes Old Command Center fallback mode.

---

# PR51 香港部署请求能力结案记录

日期：2026-09-13（UTC+8）

## 1. 结论

```text
ORIGINAL_PR=51
ORIGINAL_PR_HEAD=a7e18cf33c0d2342a7b090fc7c61dc3290eb1d43
CAPABILITY=HK_STAGING_DEPLOY Boss Request capability
CAPABILITY_ACCEPTANCE=PASS
COMMAND_CENTER_INSTALL_STATUS=INSTALLED
DEPLOYMENT_REQUESTS_ENABLED=FALSE
VERIFY_REGRESSION=PASS
TEST_PR_REGRESSION=PASS
FORMAL_DEPLOY_REQUEST_CREATED=NO
FORMAL_DEPLOY_TASK_CREATED=NO
HK_DEPLOYMENT_EXECUTED=NO
PRODUCTION_ACTION=NO
```

PR51 的能力范围已经完成独立审查、受控安装和安装后回归验证。自本结案 PR 起，PR51 只保留为历史设计与固定源码来源，不再承载后续 DEPTH、迁移、候选镜像、发布门或真实部署准备工作。

本记录不把“部署通道能力已经具备”解释成“当前业务候选已经允许部署”。

## 2. 固定源码身份

PR51 固定来源：

```text
repository=yuguangzhi3836-glitch/GO
source_pr=51
source_commit=a7e18cf33c0d2342a7b090fc7c61dc3290eb1d43
```

本结案 PR 从当时最新 `main` 重新落地主线，不继续向原 `feature/boss-deploy-request-v1-20260912` 分支追加实现。

PR51 固定源码清单的关键 SHA256：

```text
go-boss-request-bridge=edcac357074d4600ed249322589f70504a4e5981f4cd247b8e8ba066a6d80178
go_deploy_request.py=640f6defad9f29ffc8cb581c3c9ee798e6dc2192c9252bf59eeaf6fbbba5f69d
config.json=c73c02a6465e4427f618821f928a4aa74286a02400d7f422368bae72368186c3
run_checks.py=6b88ea440ce24f175ef119aaea399b67f2ef6392b12cfc9bb610e39d8de0cffd
tests/test_deploy_entry.py=205331b69cd7db1811b027b4585f7c7a95b86ffa6b83ce2872ee7ea128532ac3
```

## 3. 独立审查与第一次 fail-closed

PR51 首轮独立审查时，代码和隔离测试本身通过，但 Command Center 缺少读取 Tasks 仓库 PR 元数据所需的只读凭据：

```text
/etc/go-command-center/keys/github-requests-reader.token
```

因此当轮按任务硬门禁停止：

```text
GITHUB_PR_METADATA_READER_OK=NO
INSTALL_ELIGIBLE=NO
INSTALL_EXECUTED=NO
```

没有临时扩权，也没有绕过该门禁安装。

## 4. 凭据补齐后的 SAFE INSTALL

Owner 后续自行提供 fine-grained、只读的 GitHub PR metadata credential 后，重新验证最小权限与目标仓库访问范围，再重跑 preflight / drift gate。

验证通过后，只安装 PR51 请求入口能力：

```text
/usr/local/libexec/go-boss-request-bridge
/usr/local/libexec/go_deploy_request.py
/etc/go-command-center/boss-request-bridge-v1.json
```

安装后配置保持：

```text
deployment_requests_enabled=false
```

同时未创建 `/etc/go-command-center/deployment-plans-v1`，因此 DEPLOY 入口继续保持双重 fail-closed：开关关闭 + 无正式部署计划目录。

## 5. 安装后行为验证

安装后已验证：

- v4 channel config 能正常加载；
- 既有 VERIFY 路径保持可用；
- TEST_PR 路径保持可用；
- 合成 DEPLOY 请求在开关关闭时被明确拒绝；
- 拒绝路径没有调用 signer；
- 拒绝路径没有调用 publisher；
- Bridge timer 恢复后持续运行；
- ledger 无 claiming / prepared / publishing 在途状态；
- 未产生正式 `go-boss-deploy-*` Task；
- HK business runtime 前后指纹一致。

结论：

```text
PR51_DEPLOY_CAPABILITY_PRESENT=YES
DEPLOYMENT_REQUESTS_ENABLED=FALSE
COMMAND_CENTER_BRIDGE_HEALTH=PASS
VERIFY_REGRESSION=PASS
TEST_PR_REGRESSION=PASS
HK_BUSINESS_RUNTIME_CHANGED=NO
```

## 6. PR51 能力边界

PR51 结案所证明的是以下受控能力存在：

```text
Boss Request
  -> plan_id only
  -> Command Center 读取已审批计划
  -> 固定 source/package/image identity
  -> approval / CANARY / recent VERIFY / release gates
  -> anti-replay + one-time consumption
  -> signed HK_STAGING_DEPLOY Task capability
```

聊天调用面不能直接提供镜像、命令、服务列表、签名材料或审批参数。

PR51 继续默认关闭；只有未来独立发布流程满足合同并获得明确授权后，才可能进入正式 DEPLOY。

## 7. 明确排除的后续工作

以下项目不属于 PR51 未完成项，也不得重新挂回 PR51：

- DEPTH45 / DEPTH46 / DEPTH48 业务候选演进；
- candidate image / deployment package / build contract；
- live RDS migration 与 schema readiness；
- different-image 正式 HK E2E；
- media / supplier / bank settlement；
- three-end UX / physical iOS / physical Android；
- Sealed Node；
- Final Release；
- Production。

因此：

```text
HK_STAGING_DEPLOYMENT_READY=OUT_OF_SCOPE
LIVE_MIGRATION_AUTHORIZED=OUT_OF_SCOPE
DIFFERENT_IMAGE_E2E_PROVEN=OUT_OF_SCOPE
FINAL_RELEASE_PASS=OUT_OF_SCOPE
PRODUCTION_READY=OUT_OF_SCOPE
```

## 8. 原 PR #51 的处置

本 PR 是 PR51 capability 的正式 mainline / closeout 载体。

原 PR #51：

- 保留为历史设计和固定源码来源；
- 不再追加实现 commit；
- 不再承担结案记录；
- 本 PR 合并后应关闭并标记为 superseded。

建议原 #51 仅保留最小留痕：

> Superseded by the PR51 capability mainline/closeout PR; capability acceptance and closure are recorded there.

## 9. 最终状态

本文件记录的“结案”含义是能力验收闭合，不是部署授权。

```text
PR51_CAPABILITY_CLOSED=YES
CAPABILITY_ACCEPTANCE=PASS
CAPABILITY_MAINLINE_TARGET=THIS_PR
DEPLOYMENT_REQUESTS_ENABLED=FALSE
SERVER_REINSTALL_REQUIRED=NO
FORMAL_DEPLOY_REQUEST_CREATED=NO
FORMAL_DEPLOY_TASK_CREATED=NO
HK_DEPLOYMENT_EXECUTED=NO
PRODUCTION_ACTION=NO
DEPLOYMENT_READINESS=OUT_OF_SCOPE
```

本 PR 合并后，PR51 能力主线与结案记录进入 `main`；后续 release/deployment readiness 必须使用独立任务与独立 PR。