# CC V1 CURRENT HANDOFF · 2026-09-16

> 面向**下一次全新 WorkBuddy 会话**的唯一入口文件。所有身份值均于 2026-09-16 01:20–01:35 CST
> **从实况重新读取**（未从旧会话复制）。本文件不含任何 private key / token / password / AK。
>
> 读取顺序建议：本文件 → `docs/project/CC_V1_SCOPE_20260916.md`（范围权威）→ 才动手。

> **2026-09-16 修订说明（TD-J 安装 / B3 与 B3-R 清掉 / B4-B1 与 B4-B1.1 封存产物并已安装 / B4-B1.2 双归档格式与失败闭环 / NEXT_ACTION 替换；§4 §6 §9 §11 已就地更新）**：本文件 01:26 CST 的读数之后，以下事实已被
> 后续工作取代；读时以更晚的权威件为准，**不要按本文的旧描述行动**：
>
> * **B4-B1（本轮，仓库侧）**：TEST_PR 构建产物此前是**临时**的（V2 在 finally 里删镜像），
>   签名 Evidence 的 `built_image_id` 只是构建身份、不是可交付物。现在 V3 在全部门 PASS 后
>   把同一镜像封存进固定 store（契约 `go.sealed-artifact.v1`），Evidence 记录
>   `artifact_durability` + `artifact_package`；`candidate_repo_digest` 这条**不可能满足**的
>   假规则（digest 后缀 == image_id）已从 plan / Task / HK agent / executor / 投影中删除，
>   改为 `image_id` + `package_sha256`。admission 现在分开报告构建身份与产物可用性；
>   当前 canonical candidate = `NOT_PROVEN` / not deployable。**live 未安装。**
>   记录：`docs/control-plane/hk-staging/B4B1_DURABLE_ARTIFACT_20260916.md`
>
> * B2（没有 RELEASE_CANDIDATE_V1 准入 Gate）**已落地** ——
>   `control-plane/command-center-candidate-admission-v1/`，契约 `go.release-candidate.v1`，
>   写进 `docs/canonical-baseline/CURRENT_CANDIDATE.json` 的 `release_candidate_v1` 块；
>   readiness 的 `APPROVED_CANDIDATE` / `SOURCE_BINDING` / `PACKAGE_BINDING` 三个**既有**门改读该契约
>   （未新增 gate）。
> * §12 的「三个 workflow 为 failure」**已修复**（`76f3ae1` / `82920c7` 及后续提交），CI 现为全绿。
> * VERIFY 授权基线已从退役的 R3.1.5 运行时迁到 DEPTH48（collector `0133_flight_change_plan`、
>   deployctl `b9aea31e…`、CC baseline `76bab571…`）——
>   `docs/control-plane/hk-staging/VERIFY_BASELINE_MIGRATION_INSTALLED_20260916.md`。
> * TD-J：**仓库修复已进 PR #109，且已于 2026-09-16T07:07:18Z 单文件安装到 HK-STAGING-01**
>   （live `transport.py` = `340da98f…`，备份 `/var/backups/HK-CHANGE-20260916T070702Z-tdj-evidence-workspace/`）；
>   随后一张 fresh bounded VERIFY（Request PR #28 / Task `go-boss-request-verify-20260916T073128Z-adaf1e8b9da4`）
>   的签名 SUCCESS Evidence **真的发布成功**（commit `abf71502…`）——TD-J 的 live 证明。
> * **B3 CLEARED**；同时暴露并修掉 B3-R（`CURRENT_HK_RUNTIME.json` 的 `image.image_config_id`
>   曾指向一个主机上不存在的镜像 `57beafa2…`，已纠正为 live 镜像身份 `1c9598d6…`）。
> * readiness 现为 `DEPLOY_READY=UNKNOWN`（无 mandatory FAIL，九门因缺 plan bundle 为 UNKNOWN）——
>   **不是 YES，也不是旧的 NO**。
>   本轮全部事实：`docs/control-plane/hk-staging/TDJ_B3R_AND_FRESH_VERIFY_20260916.md`
>   （TD-J 的安装方案原文：`docs/control-plane/hk-staging/TDJ_EVIDENCE_WORKSPACE_FIX_20260916.md`）

---

## 1. 项目目标

```text
Boss / ChatGPT
  → GitHub（bounded Request）
  → Command Center（校验确切候选、签 bounded Task）
  → HK Agent（受控 Executor）
  → DEPLOY / ROLLBACK
  → Evidence（签名）
  → VERIFY
  → result 回到 ChatGPT
```

```text
Boss 不依赖 Eason / Codex / WorkBuddy，不需要 SSH，不需要手工签名或手工密钥。
做到这一点 = COMMAND_CENTER_V1=DELIVERED。
```

## 2. 当前正式 Scope Reset（已冻结，权威 = `docs/project/CC_V1_SCOPE_20260916.md`）

```text
GitHub authenticated identity = Human Approval identity
NO dedicated Human Approval private key
Task signer != Evidence signer
CC defines what is deployable
Boss GPT 的 PR 不符合规范 → REJECT，让上游自己修
不为历史 PR 做特殊兼容
Production out of scope

DELIVERY > THEORETICAL PERFECTION
SIMPLICITY > EXTRA SECURITY LAYERS
PROVEN E2E > MORE ARCHITECTURE
```

已取消的旧 blocker（**不要复活，不要创建任何新的 Human Approval 私钥**）：
`DEDICATED_HUMAN_APPROVAL_PRIVATE_KEY`、`APPROVAL_SIGNER_ROTATION`、
`APPROVAL_SIGNER_FINGERPRINT_LIFECYCLE`、`HUMAN_APPROVAL_SIGNER != TASK_SIGNER`、
`HUMAN_MANUAL_CRYPTOGRAPHIC_SIGNATURE`。

保留边界（一字未降）：bounded action allowlist、固定 HK-STAGING 环境、不可变 GitHub 源码绑定、
候选 commit/PR 绑定、无任意 shell / argv / image / path / service / environment、Task identity、
nonce / replay、重复执行保护、Signed Evidence（含失败）、rollback 到已知good、post-deploy VERIFY、
fail closed、Production 排除。

## 3. GitHub 当前身份（实况重读 2026-09-16 01:22 CST）

```text
repository            yuguangzhi3836-glitch/GO        （private）
default branch        main
canonical main SHA    dcb68a652429aa01e8428ce9f582e4bab6a6175e
PR #109 state         open / Draft=true / merged=false / merged_at=null
PR #109 base          main @ 8610a4dbfd58cbe595f3d161c049de37dd81d3cc
                      ⚠ base 落后于 main 尖（dcb68a65）—— 分支未与 main 对齐
PR #109 head          cc/v1-finalization-20260914 @ eef48f884ce1349af842f8cbbb4db0852ee5da02
PR #109 mergeable     True / unstable
current working branch cc/v1-finalization-20260914
CURRENT_ISSUE         #103
```

## 4. Issue 状态（只列状态 / 仓库实现 / live 安装 / live 证明 / 剩余缺口）

```text
#96  CLOSED  信任链
     impl: identity/VERIFIER_IDENTITIES_V1.json 发布两把公钥与双向绑定
     live: 已发布；fingerprint 与主机一致
     proof: 两把身份 fingerprint 两端一致
     gap: 无

#97  CLOSED  失败闭环
     impl: contracts/failure_evidence_v1.schema.json + transport.py 失败路径 + 投影 EXECUTION_FAILED
     live: hk_agent/transport.py 340da98f95acdb0c212aa116681da8d8344c6da306e44dfcf332c67ee1957de8
           （TD-J 修复，2026-09-16T07:07:18Z 单文件安装；上一版 6f329b2e… 已备份）
     proof: REAL — TEST_PR 受控失败 → 签名 FAILED Evidence → 投影 EXECUTION_FAILED / retry_permitted=false
            + 2026-09-16 该程序在同一趟 pass 内成功发布 VERIFY 的 SUCCESS Evidence（此前会失败）
     gap: 无

#98  CLOSED  HK Agent liveness
     impl: producer（outbox，绝不发总线）+ liveness-request-transport-v1（有界 relay）
     live: go-liveness-producer.timer + go-liveness-request-transport.timer 均 active/enabled
     proof: REAL — 多个 bucket 全自动接力，hk_agent_online=PROVEN 持续
     gap: 无（CONTINUITY=PROVEN 已登记）

#99  CLOSED  状态发布
     impl: go-command-center-state-cycle（900s）发布到 runs/<stamp>/，CURRENT.json 指针
     live: timer active/enabled
     proof: REAL — CURRENT run = runs/20260915T165627Z_fd64b95f9eb4
     gap: runs/ retention 策略未定（TECHNICAL_DEBT_V2）

#100 CLOSED  Bridge ledger → Control Bus 事实
     impl: go-request-fact-export + 投影消费；semantic identity 去重已上生产
     live: go-request-fact-cycle.timer（300s）active/enabled
     proof: REAL — 探活 Request 现以 REQUEST_VALIDATED / BECAME_A_TASK 出现
     gap: 无

#101 CLOSED  只读 Deploy Readiness Evaluator
     impl: 13 门全 mandatory；投影器已同步 13 门（跨组件测试从 evaluator 源码钉）
     live: 评估器**不在 CC 上**，是仓库侧组件，离线运行
     proof: REAL（离线）— 已能读真实 evaluator 产物
     gap: HUMAN_APPROVAL 门仍按**已取消的要求**判定（见 §9 blocker 1）

#102 CLOSED  DEPLOY dry-run 与拒绝路径
     impl: command-center-deploy-dry-run-v1
     live: 未安装到 CC（离线组件）
     proof: SYNTHETIC（组件门禁）
     gap: 无

#103 OPEN    部署实接 ← CURRENT_ISSUE
     impl: Bridge 1.5.0 + deploy gate + readiness（部分）
     live: Bridge 已装且四项 action；deployment_requests_enabled=false
     proof: 部分 REAL（TEST_PR 成功/失败闭环、liveness）；DEPLOY 本身 NOT_YET_PROVEN
     gap: readiness HUMAN_APPROVAL 门；新鲜 VERIFY；合规候选准入 Gate 不存在（§9）

#104 OPEN    回滚判定
     impl: 最小 Rollback Eligibility（current / previous known-good / target binding / ROLLBACK_READY）
     live: 无
     proof: NOT_YET_PROVEN
     gap: 未实现

#105 OPEN    回滚实接
     impl: bounded ROLLBACK Request 全链（另需当次人类批准）
     live: 无
     proof: NOT_YET_PROVEN
     gap: 未实现

#106 OPEN    恢复安全
     impl: 只防 duplicate execution / nonce replay / blind retry / Evidence missing 导致重执行 /
           restart 导致重复 task
     live: 部分已有（Task identity + nonce + ledger attempts/processed）
     proof: SYNTHETIC（QueueTests 覆盖 prepared/published/ambiguous/reconcile 路径）
     gap: 未做端到端验收

#107 OPEN    对话合同冻结
     impl: 冻结五种 intent：status / verify / test_pr / deploy / rollback，不再增加
     live: 当前 state/status 已发布十问 + request_channel
     proof: SYNTHETIC
     gap: 未冻结

#108 OPEN    最终交付
     impl: 全链 E2E 验收 + 文档收口，禁止新增功能
     live: n/a
     proof: NOT_YET_PROVEN
     gap: 未开始
```

## 5. Live Command Center 状态（实况重读）

```text
Bridge version        1.5.0-control-plane-health
Bridge revision       persistent-verify-test-pr-health-channel-r1
Bridge source commit  4c3391a1edff30c3f57ef316c6210b24780d6682（branch cc/v1-finalization-20260914）
Bridge artifact sha   503355dbd67d937a3d54721b33a00ad007460626df6dab57ad6121a79e0bf737
channel config        /etc/go-command-center/boss-request-bridge-v1.json（root:root 0600）
  version 4 · mode PERSISTENT · publish_enabled true
  allowed_actions    HK_STAGING_VERIFY, HK_STAGING_TEST_PR, HK_STAGING_DEPLOY, CONTROL_PLANE_HEALTH
  allowed_environment HK-STAGING-01
  deployment_requests_enabled  false          ← 必须保持 false 直到人类批准真实 DEPLOY
Task signer           /etc/go-command-center/keys/task-manifest-signing.pem
                      pub fingerprint SHA256:bkwH368MFv+n+18Pca6MB1jV4jZtBbsn8yjC1bf/hns
                      （与 HK /etc/go-hk-agent/keys/task-verify.pub 同一身份，双向绑定）
verify baseline       /etc/go-command-center/boss-request-verify-baseline-v1.json
                      image_id sha256:66c54087…（= 旧 TEST_PR builder 镜像 id）
                      evidence_task_id go-boss02-post-rollback-verify-20260911T071429Z

timers / services（读时）
  go-request-fact-cycle.timer              active/enabled   300s
  go-command-center-state-cycle.timer      active/enabled   900s
  go-liveness-producer.timer               active/enabled   300s tick（1800s 一桶）
  go-liveness-request-transport.timer      active/enabled   300s
  go-boss-request-bridge.service           oneshot，读时 inactive/static（两次运行之间）

request visibility    go-request-fact-cycle → facts/ → 发布 request-facts/live
state publication     /var/lib/go-command-center/state-publication-v1/target/CURRENT.json
                      CURRENT = runs/20260915T165627Z_fd64b95f9eb4
                      answers.hk_agent_online = PROVEN
                      answers.request_fate.accepted = 19
liveness relay        最近 PUBLISHED = liveness-control-plane-health-994162（head 55f46913…）
                      archive_files = 3（已被顶替的 3 个探针均先入 request/liveness-archive）
live directories
  /opt/go-command-center/{liveness-producer-v1,liveness-request-transport-v1,
                          request-visibility-v1,state-publication-v1}/
  /var/lib/go-command-center/{boss-request-bridge-v1,request-visibility-v1,
                              state-publication-v1,liveness-producer-v1,
                              liveness-request-transport-v1,approvals,project-memory,
                              test-pr-install-backup,evidence-r4-readback,
                              deploy-task-issue-r3,deploy-task-issue-r4}/
rollback procedure    每次变更一个目录：/var/backups/CC-CHANGE-<UTCstamp>-<label>/
                        内含 *.before 与 installed.tsv（变更前后 sha256）
                      现存最近四个：144827Z-liveness-answer / 150835Z-unsettled-request /
                                    153449Z-liveness-transport / 161324Z-fact-action-registry
                      通用回滚 = 停对应 timer → cp -p *.before 回原位 → 若投影器变更还需同步
                      installed.json 的 projector_sha256 → 恢复 timer
                      ⛔ 回滚【不得删除】request/liveness-archive（删了就破坏 fact→Request 关联）
                      ⛔ 绝不运行随包的 install/install-command-center.sh
                        （会把 CC 从 Bridge 1.5.0 + 四项 action 回退成 {VERIFY,TEST_PR} + v3）
```

## 6. Live HK-STAGING 状态（实况重读）

```text
host                  hk-staging（47.239.57.40），实例 i-j6ccs8t04f1p4d8pe69z
Agent version         0.5.7-rebuilt
Agent units           go-hk-agent.timer active/enabled；service oneshot，读时 inactive/static
                      每 tick 一个全新 --run-once 进程 ⇒ 替换文件可零窗口（原子 rename）
Evidence signer       /etc/go-hk-agent/keys/evidence-signing.pem
                      pub fingerprint SHA256:WZ2gG4WHnO5zmijyK8TSOHFpY+EBkk8TWbSbfbRjFNw
installed agent files hk_agent/test_pr.py   654403023d599b78ec2a61776ab133ec0dc46d069e61fd7b3717d400eaedc2ac
                          （= Builder V2：executor_version test-pr-v2）
                      hk_agent/transport.py 340da98f95acdb0c212aa116681da8d8344c6da306e44dfcf332c67ee1957de8
                          （= #97 失败闭环 + TD-J 单工作区发布修复：2026-09-16T07:07:18Z 安装）
builder dockerfile    /usr/local/libexec/go-hk-test-pr/Dockerfile.go-application-python-v2
                      v1 文件仍在原处但已无引用
business containers   8 × go-822-staging-{api,recovery-worker,outbox-worker,
                          mobile-push-receipt-worker,reconciliation-worker,
                          mobile-push-worker,mobile-engagement-worker,judgment-worker}-1
                      image 全部 = go-hotel:depth48-runtime-6d0fd905（api healthy，Up 2 days）
                      + go-822-staging-redis-1 (redis:7.4-alpine) + go-822-staging-caddy-1 (caddy:2.8-alpine)
runtime image identity go-hotel:depth48-runtime-6d0fd905
                      id sha256:1c9598d699c21620f4a3b489662f7b11be07acb46440516b74452dd2b6065132
DB migration revision 0133_flight_change_plan (head)   ← 读时现场 `alembic current` 读出
CONTROL_PLANE_HEALTH  可真实执行；已多次端到端跑通（见 §7）
Task pickup / Evidence publication：已证明（agent ledger 的 processed 表有 completed + evidence_ref）
agent ledger          /var/lib/go-command-center? 否 —— /var/lib/go-hk-agent/ledger/agent.sqlite3
                      表：attempts / processed / nonce_ledger / rejections
```

## 7. 已经真正跑通过的 E2E

```text
[REAL] CONTROL_PLANE_HEALTH 全链
  producer outbox → liveness-request-transport（单一分支 force-update + 归档）
  → GitHub PR → Bridge 认领并签只读 Task（parameters {}，parameters 为模块常量）
  → HK Agent 认领执行 → 签名 Evidence → 投影 hk_agent_online=PROVEN
  实测：994159 / 994160 / 994162 等多桶连续自动接力；open PR 数不随桶增长；archive 单调增长

[REAL] TEST_PR 成功（项目历史首张）
  Request boss-hk-test-pr52-builderv2-20260915T161616Z（PR go-control-tasks#24，恰 1 个新增文件）
  → Bridge 自行解析 refs/pull/52/head = bd25d7ac → 签 go-boss-test-pr-52-83b0e20f3980
  → HK Agent 16:18:33Z 认领、16:20:28Z 发布签名 Evidence 39d11b5e102e
      executor_version=test-pr-v2 · executor_result=TEST_PR_OK
      source_commit_sha=bd25d7acca1b5f54a7fb555008ed60b76ee45f21
      built_image_id=sha256:bed9eddeb94b4fe93cd41fa4a071a3700ef0a93343432a4c77e1e11fb7aae984
      gate_results={offline_build:PASS, isolated_runtime_checks:PASS, source_commit:PASS}
      application_health_proven=false · deployment_performed=false

[REAL] TEST_PR 受控失败闭环
  go-boss-test-pr-52-9b2e2fd1d565 → 失败在 docker image inspect（未创建容器）
  → 签名 FAILED Evidence → 投影 EXECUTION_FAILED / retry_permitted=false / ATTEMPT_ROWS=1

[REAL] Request fact 语义去重
  78 observations → 22 semantic facts，折叠 56 条纯时间重述；重复轮全 UNCHANGED

[REAL] 就绪度读取真实 evaluator 产物
  13 门同序、全 mandatory；TEST_PR 门在 TEST_PR 成功后由 FAIL 转为不阻断

[SYNTHETIC] 组件级：failure_evidence / deploy dry-run / queue replay / mid-flight /
            transport 有界性（真实 git 30 项）/ readiness 契约漂移守卫

[NOT_YET_PROVEN] fresh VERIFY（最近一次真实 VERIFY 已过期）
[NOT_YET_PROVEN] CANARY（从未执行）
[NOT_YET_PROVEN] DEPLOY（从未执行；deployment_requests_enabled=false）
[NOT_YET_PROVEN] ROLLBACK（从未执行）
```

## 8. 已完成、**不要再重做**（DO_NOT_REOPEN / DO_NOT_REDESIGN）

```text
Request fact semantic dedup（先聚合后铸造；identity 排除时间字段；fact_id_collision 拒绝）
REQUEST_CREATED 可铸造 + fate 拆出 NOT_SETTLED_BY_BRIDGE
readiness 13 门契约同步（投影器 13 门全 mandatory；跨组件测试从 evaluator 源码钉）
HEALTH 在 Bridge 的通道动作 + derive_formal_task 显式 fail-closed 派发
导出器 ACTION_IDS = Bridge 通道契约四项（曾漏 CONTROL_PLANE_HEALTH ⇒ 探活无 fact）
liveness freshness 2400 = interval 1800 + transport grace 600（48/24h 预算不变）
liveness 单一 transport 分支 + 每桶 force-update + request/liveness-archive 归档
  （旧 install/liveness_request_wiring.py 已删除，不要恢复「每桶新建 PR」）
历史 projection 不可变：evidence/PROJECTION_2026091{4,5} 只加标识，JSON 零字节改动
请求开关已恢复到 false 并有 change record
candidate canonicalization = PR52 head bd25d7ac（旧 8a22a4fc 作废）
Builder V2：只换构建环境（Dockerfile …-v2 + 底座按 tag+id 双钉 + executor_version=test-pr-v2），
  profile 名 go-application-python-v1 不变 ⇒ Bridge/投影/契约零改动
Human Approval = authenticated GitHub identity（APPROVAL_IDENTITIES 两人）
  ⇒ 第三个 Human Approval 密钥方案【已取消】，不要重建；install/go-approval-sign 已删除
CONTROL_PLANE_HEALTH 只读、parameters={}、不参与 DEPLOY armed / 计划 / 预算
```

## 9. 当前真正的 blocker（只列会直接阻断 Boss → ChatGPT → CC → HK → DEPLOY/ROLLBACK 的）

```text
B1  readiness 的 HUMAN_APPROVAL 门仍按【已取消的要求】判定
    它要求「已发布的独立 Human Approval 公钥 + approval 上的签名」
    ⇒ 该门永远 FAIL ⇒ DEPLOY_READY 不可能为 YES
    修法：改成以【已认证 GitHub 身份】为准（不新增 gate，只改该门的权威来源）
    这是到 DEPLOY_READY=YES 之间唯一剩下的改动

B2  没有 RELEASE_CANDIDATE_V1 准入 Gate
    当前无任何东西定义「什么是一个合规候选」，也没有在准入处拒绝不合规的 Boss GPT PR
    ⇒ 与 Scope Reset 的「CC defines what is deployable / 不合规范就 REJECT」直接冲突
    见 §10

B3  **CLEARED**（2026-09-16）
    先前：readiness 的 VERIFY 门 FAIL —— 最近一次真实 VERIFY 超出 86400s 窗口，
    且 2026-09-16T05:02:20Z 那张 fresh VERIFY 的成功 Evidence 被 TD-J 撞掉（EVIDENCE_PUBLISH_FAILED /
    stage=evidence_publish / GITHUB_TRANSPORT_REJECT）
    现在：TD-J 修复已装到 live，随后一张 fresh VERIFY 的签名 SUCCESS Evidence 真的发布成功
    （Task `go-boss-request-verify-20260916T073128Z-adaf1e8b9da4`，Evidence commit `abf71502…`，
    status SUCCESS / executor VERIFY_OK / 签名与镜像绑定均验证通过）
    robustness：同批暴露的 B3-R（指针声明 runtime ≠ 已证明 runtime）已修，见下

B3-R **CLEARED**（2026-09-16，B3 的孪生阻塞，先前被 freshness 掩盖）
    `docs/canonical-baseline/CURRENT_HK_RUNTIME.json` 的 `image.image_config_id` 曾写
    `sha256:57beafa2…`：该镜像在主机上不存在（`docker image inspect` → No such image），
    在 go-control-evidence / go-control-tasks 里零命中，而同一个 block 的 `image_id_short`
    与签名 VERIFY Evidence 都指向 live 镜像 `sha256:1c9598d6…`
    ⇒ 已把该字段纠正为 `1c9598d6…`（并同步 `docs/project/GO_CURRENT_STATE.md`）；
    **没有**降低 VERIFY gate、没有改比较口径、没有删 drift 检测
    证据：离线投影 `runtime_verification_state=MATCH` / `image_relation=MATCH`；
    readiness `VERIFY=PASS`；负向测试 `test_drift_when_declared_and_proven_images_disagree` 仍 PASS
    历史投影 `PROJECTION_2026091{4,5}` 里当时记录的 DIFFER **保持原样**（当时确实不一致）

B4  没有可用的部署计划 bundle（plan + approval + canary/preflight task+evidence）
    ⇒ PACKAGE_BINDING / DEPLOYMENT_PLAN / HUMAN_APPROVAL / CURRENT_RUNTIME /
      LIVE_SWITCH / LIVE_SWITCH_PROVENANCE / CANARY / RELEASE_GATES /
      BRIDGE_ACCEPTANCE **九门 UNKNOWN**，无法到 DEPLOY_READY=YES
    （CANARY 在现存 live executor 要求它时必须 PASS；不要新增 gate）

    **2026-09-16 / B4-B1 细分（仓库侧已完成，未安装）**：
    · `EPHEMERAL_ARTIFACT_BUG` = CONFIRMED。test-pr-v2 构建后 `docker image rm --force`
      删掉了镜像，所以签名 Evidence 里的 `built_image_id` 只是**构建身份**，
      不是可交付物；`BUILD_IDENTITY_PROVEN` 被当成了 `ARTIFACT_DURABILITY_PROVEN`。
      `sha256:fe0d2c36…` **不可恢复**，未来可部署产物只能来自一次新的 TEST_PR。
    · 选 local sealed store（Option B）而非私registry：无新密钥、无新外部服务、
      无新网络依赖，且复用仓内已有的 `docker save` / 内容寻址 / 校验式 `docker load` 能力。
      契约 `go.sealed-artifact.v1`，store `/var/lib/go-hk-artifacts/objects/<package_sha256>.tar`。
    · TEST_PR Builder V3：全部门 PASS **之后**才封存同一个 built_image_id，
      临时 tag 仍删除；Evidence 记录 `artifact_durability` + `artifact_package`。
      新失败阶段 `artifact_durability` → `ARTIFACT_DURABILITY_FAILED`。
    · 假规则已删除：`candidate.repo_digest` 后缀 == image_id 不再存在；
      改为 `image_id`（构建身份）+ `package_sha256`（交付身份）。
      `candidate_repo_digest` 已从 plan / Task / HK agent / 两个 executor / 投影中消失。
    · 投影把旧参数形状显式命名为 `SUPERSEDED`（精确、封闭、非通配）：
      真实总线里 6 条历史 CANARY/DEPLOY Task 仍可读且保留 Evidence。
    · admission：新增可选 `artifact_package`，分开报告 `artifact_durability` /
      `deployability`；当前 canonical candidate = `durability NOT_PROVEN` /
      `deployable false`（事实如此），`admission` 仍 ACCEPT（身份完整，未被改写）。
      `PACKAGE_BINDING` 现在要求 durability=PROVEN 且 package 与 plan 一致。
    · **仍未清**：`B4_RELEASE_GATES`（无 exact-bound PASS）、
      `B4_CANARY_BASELINE`（canary_runtime 仍 pin `0114_ext_truth_incident_hard`，
      而候选声明 `0133_flight_change_plan`；CANARY 通道化必须同时做 A 通道 + B 基线迁移）、
      `B4_AUTONOMY`（注册 plan / 开开关 / 写 provenance 仍需 CC 主机人工操作）。
    记录：`docs/control-plane/hk-staging/B4B1_DURABLE_ARTIFACT_20260916.md`

    **2026-09-16 / B4-B1.1 修订（仓库侧，仍未安装）**：
    · `SEALED_ARTIFACT_CROSS_UID_OWNERSHIP` = **CONFIRMED 并已修**。writer 是
      `go-hk-agent`（systemd `User=`/`Group=`），reader 是 root（agent 用
      `sudo -n /usr/local/libexec/go-hk-deployctl` 调执行器）；两侧却都拿
      **读进程自己的 euid** 去比对象 owner ⇒ 同一个操作的两个要求互斥，
      而安装合同还把 store 建成 `root:root 0700`，writer 第一次就必然拒绝。
    · 现在信任锚是**账户名** `go-hk-agent`/`go-hk-agent`，每次从账户库解析；
      解析不到就拒绝（`*_ACCOUNT_UNAVAILABLE`），uid 解析为 0 也拒绝；
      **不写死任何数字 uid**，也不回退到当前进程 / root / 文件自身 owner。
    · writer 额外要求自身 euid == 该账户（`SEALED_ARTIFACT_WRITER_IDENTITY`）；
      reader **故意没有**这条：root 是 privileged consumer，读者**完全不读自身身份**。
      目录 `0700` / 对象 `0600` / `go-hk-agent:go-hk-agent`，其余校验全部保留。
    · `seal()` 在报告 PROVEN **之前**用与 `resolve()` 同一个 primitive 复核最终对象，
      并以原子 no-overwrite 硬链接发布：已有内容地址只校验、永不重写。
    · 安装合同：store 建成 `go-hk-agent:go-hk-agent 0700`；已存在而 owner/mode 不符
      ⇒ `STORE_OWNER_MISMATCH` / `STORE_MODE_MISMATCH`，**operator review，不递归 chown**
      （那是这台机器上每个候选的唯一副本）。install 与 preflight 都做 post-install readback。
    · 同一次提交顺带修正 pin 错位：`go-hk-deployctl` 的 `_CANARY_SHA256` / `_DEPLOY_SHA256`
      原先按**工作树 CRLF 字节**计算，与仓库实际发布的字节不符 ⇒ 任何 `_load_*` 都不可能成功。
      现在全部 pin 取自 committed bytes，并在模拟安装布局里逐个装载验证。
    · 本轮**无 live 变更**；`LIVE_INSTALL=NO`、`NEW_TEST_PR=NO`、`DURABLE_ARTIFACT_EXISTS=NO`、
      `PACKAGE_BINDING=BLOCKED`、`DEPLOY_READY=UNKNOWN` 均未变。

    **2026-09-16 / B4-B1.2 修订（仓库侧；B4-B1 与 B4-B1.1 已装在 live，本轮未安装）**：
    · 第一张真实 fresh TEST_PR（Task `go-boss-test-pr-52-3249a0c8589a`）**执行器跑通、封存失败**：
      `SEALED_ARTIFACT_ARCHIVE_INVALID`。两个缺陷都在 B4-B1 自己的改动里，且本机与 CI 都测不出。
    · **根因 A = 解析器只认识两种归档格式中的一种**。HK 是 Docker 29.7.2 + containerd image store
      （`io.containerd.snapshotter.v1`）⇒ `docker save` 写的是 **OCI image layout**
      （`oci-layout` / `index.json` / `blobs/sha256/*`，index 还可能指向嵌套 index）；
      而解析器只会读 legacy docker-archive，且**全部夹具都是 legacy 手搓的** ⇒ 夹具与解析器自洽、
      与真机不符。traceback 行号是精确的（live 文件与仓库字节相同）：line 248 落在
      `Config` 的裸 hex 判定上 ⇒ 真机是**混合形态**（OCI layout + legacy index，且其引用不是裸名）。
    · 现在两种格式由**同一套语法**在**两侧**解析：OCI 按**有界 descriptor graph**遍历
      （深度 ≤ 4、数量 ≤ 256、每个 digest 只跟一次），每个 blob 必须在
      `blobs/sha256/<digest>` 以 regular 成员存在、字节哈希等于描述它的 digest、size 一致；
      media type 走显式 allowlist（未知类型**永不**成为候选权威，attestation 只入图不成像）；
      legacy/hybrid 的引用只允许两种规范位置，digest 取自引用最后一节；两种布局必须指向同一镜像。
    · **三个身份继续严格分离**：image_id（config 字节哈希）、package_sha256（归档内容地址）、
      descriptor digest。只有第一个决定"这是哪个镜像"，并有测试断言三者不被互换。
    · **根因 B = store 的拒绝不在失败路径里**。`run_once` 的 except 元组没有 `artifact_store.Reject`
      ⇒ 异常冒到 main ⇒ 整趟 tick exit 1、**failure evidence 未发布**、attempt 停在
      `status=claimed` 且 `diagnostic=NULL`（TD-J 教训的翻版：执行器真的跑了、真的失败了，
      控制面什么都看不到）。现在 `test_pr` 在**自己的边界**把拒绝转成 stage=`artifact_durability`、
      reason=`ARTIFACT_DURABILITY_REJECT` 的 TEST_PR 拒绝（store 自己的有界码走 diagnostic 通道，
      **不新增第三套错误 schema**）；`run_once` 另外把 store 的异常类型加进 except 作为兜底。
    · 夹具改为**单一来源** `tests/archive_fixtures.py`（三套件共用），CI 新增一步用 runner 真实
      `docker save` 出来的归档跑两侧解析并记录实际格式；确定性 OCI 夹具仍是 OCI 格式的权威。
    · 本轮**无 live 变更**：`LIVE_FIX_INSTALLED=NO`、`NEW_TEST_PR_EXECUTED=NO`、
      `DURABLE_ARTIFACT_EXISTS=NO`、`PACKAGE_BINDING=BLOCKED`、`DEPLOY_READY=UNKNOWN`。
    · 下一次安装只需 **5 个文件**（无新路径、无目录变更、不重启）；旧失败 Task 的
      attempt 已耗尽，**不得重发**，重试必须用新 Request / 新 Task / 新 nonce。

    **2026-09-16 / B4-B1.5 对账（repository-side only，已完成并推送）**：
    · canonical candidate 已**成套**切到真实的 fresh v3 产物：`artifact_digest`
      `fe0d2c36…` → `6b92050e…`；`build_definition.executor_version` `test-pr-v2` → `test-pr-v3`
      （其余 5 个 build 字段不动，事实未变）；`test_result_identity` → Task
      `go-boss-test-pr-52-0342850d8822` / `evidence_id` `1865b17d…`（**commit**，不是 blob
      `0500b1a0…`，后者只作审计信息）/ `artifact_digest` 同新；`artifact_package`
      `NOT_PROVEN` → `PROVEN` + `e70238c7…`。**paired move**：产物、产生它的结果、
      产生它的 builder、证明它可交付的 package，四者一起移。
    · 历史**未被改写**：旧 reconciliation block 逐字保存在
      `release_candidate_reconciliation_history[0]`（旧 request / task / evidence /
      old-new artifact / reason / 时间全在），`release_candidate_reconciliation` 记本轮最新事件。
      v2 Evidence 与其"为何不 durable"的解释一起留在历史里。
    · `source_commit` / `application_tree` / `source_fingerprint` / `migration_head` /
      `migration_required` / `required_services` / `rollback_relation` **未变**；
      本轮**不重新发 TEST_PR**（source 没变，重跑只会得到第三个互不相干的新产物）。
    · admission 实测 **ACCEPT**（所有 check PASS、`artifact_durability=PROVEN`、
      `deployable_artifact_established=true`、`is_a_deploy_approval=false`）；
      B4-B1.4 的 builder 绑定在真实产物上通过，反向 mutation（候选改回 `test-pr-v2`，
      证据仍 v3）→ `candidate_test_result_evidence_builder_version` 拒绝；
      image / Evidence / package 三者的成套 mutation（错 package、旧 image、旧 Evidence、
      PROVEN+null）全部 fail closed —— 因此 ACCEPT 不是因为门太松。
    · ⚠ **`PACKAGE_BINDING` 不会因本轮变 PASS**：该 gate 先要 plan（`plan_body()` 为空即 UNKNOWN）。
      只读重跑实测 `PACKAGE_BINDING=UNKNOWN`；用 gate **自己的逻辑**做投影：同一个 plan 下
      **旧候选 → FAIL `artifact_package_not_proven`，新候选 → PASS** ⇒ 候选侧已就绪，
      剩下的输入是 approved plan（属于后续 Human Approval 流程，不在本轮）。
      未改任何 readiness 规则、未人工改任何输出。
    · readiness 其余 gate：`APPROVED_CANDIDATE=PASS` / `SOURCE_BINDING=PASS`，其余仍
      UNKNOWN / FAIL —— 其 control-state 输入是 **09-15 的投影快照**（TEST_PR gate 读到的
      仍是当时那张已 `TASK_EXPIRED` 的旧 Task），刷新投影需要 tasks/evidence 仓的本地检出，
      属另一轮；本轮不做。
    记录：`docs/control-plane/command-center/B4B15_PAIRED_RECONCILIATION_20260916.md`

B5  deployment_requests_enabled=false（**正确的 fail-closed 姿态**，不是缺陷）
    真实 DEPLOY 必须等人类当次批准后才开；ROLLBACK 同理（#105 另需独立批准）
```

其余全部归 **TECHNICAL_DEBT_V2**（登记在 `docs/project/CC_V1_SCOPE_20260916.md` §9）：

```text
TD-01 独立 Human Approval 签名者及其轮换/指纹生命周期（职责已转移）
TD-02 task_not_claimed 把认领前所有拒绝理由压成一个标签（排障读不到真因）
TD-03 3 条历史 Task（…20260905T1512/1521/20260906T0118）在两把已发布身份下都不验签
TD-04 本地 run_checks 输出目录限制、Windows 上 fcntl 导致部分套件无法本地跑
TD-05 LIVE_SWITCH_PROVENANCE 的历史 enable 来源未追认
TD-06 state publication runs/ retention 策略（最迟 #108 前成形）
TD-07 探活 bucket 目前每个都在 agent ledger 留 attempts 行（正常，但无清理策略）
TD-J  一趟 run_once 只能成功发布一条 Evidence（同轮 clone 目标冲突）
      · 根因：push_evidence 把证据仓 clone 到固定 work/<dirname>，而 run_once 一趟遍历所有 Task；
        `go-boss-health-…` 排在 `go-boss-request-verify-…` 之前 ⇒ 同一趟里第二条发布必然撞已存在目录
      · 后果：B3。VERIFY 执行器已 SUCCESS，却只有失败记录能发布（失败走 work/evidence-failure）
      · repo 修复：每次发布使用由记录身份派生的独立工作区 → transport.py 340da98f…（PR #109 / 3819b55a）
      · repository fix = IMPLEMENTED / TESTED / **INSTALLED（2026-09-16T07:07:18Z）**
      · live 证明：TD-J 安装后的第一张 fresh VERIFY 在同一趟 pass 内成功发布 SUCCESS Evidence
        （Task `go-boss-request-verify-20260916T073128Z-adaf1e8b9da4` / commit `abf71502…`）
      · 同类未修站点（记录在案，仍未动）：prepare_rollback_handoff 仍 clone 到固定
        work/rollback-source-evidence；当轮 CC 通道未启用 ROLLBACK，故当前不可达
```

## 10. RELEASE_CANDIDATE_V1 当前规范

```text
candidate_id
source_repository
source_commit
application_tree
source_fingerprint
migration_head
build_definition
artifact_digest / immutable image
required_services / topology
test result identity
rollback relation
```

```text
TEST_PR
BUILD
CANARY
DEPLOY
```

**必须绑定同一个 immutable candidate。**

当前实况（不要当成已实现）：该 contract **尚未实现为准入 Gate**（= blocker B2）。
现存的相关事实：GO 仓里有一个 canonical candidate 指针（`bd25d7ac…`，PR52 head），
readiness 读它得到 `APPROVED_CANDIDATE=PASS` / `SOURCE_BINDING=PASS`；
`RELEASE_GATES` 四键（three_end_ux / six_vertical_closed_loop / sealed_node / final_release）
与 `CANARY_GATES` / `VERIFY_GATES` 已存在于 deploy gate 常量中；

**2026-09-16 / B4-B1.5 更新（当前事实）**：准入 Gate 已实现并已运行
（`control-plane/command-center-candidate-admission-v1`，CC V1-08 / #103）；canonical candidate
已对账到真实 v3 产物 ⇒ `artifact_digest` `sha256:6b92050e…`、
`build_definition.executor_version` `test-pr-v3`、`test_result_identity.evidence_id`
`1865b17d25e6baa6dd2bebc2bdee89cb9a621ad3`（commit）、`artifact_package`
`PROVEN` / `e70238c7…`。admission = **ACCEPT**，全部 check PASS。
`PACKAGE_BINDING = UNKNOWN`，原因缺的是 **approved plan**，不是候选侧缺口（见 §9 的 B4-B1.5 条目）。
上面"该 contract 尚未实现为准入 Gate"与所列身份描述的是当天的历史状态。
固定八服务拓扑与 `redis`/`caddy` 保护名单已在 gate 中硬编码。

## 11. 下一会话唯一入口

```text
NEXT_ACTION=
第 1 轮（需要新的当次 Human Approval）：在 HK-STAGING-01 上受控安装 **B4-B1.2 的 5 个文件**
（B4-B1 与 B4-B1.1 已在位，store 已建为 go-hk-agent:go-hk-agent 0700，都不要重做）：
  /opt/go-hk-agent-rebuilt/hk_agent/artifact_store.py        5dddc742… -> f22bc4ed…
  /opt/go-hk-agent-rebuilt/hk_agent/test_pr.py               52478829… -> d1c454fc…
  /opt/go-hk-agent-rebuilt/hk_agent/transport.py             b35ace22… -> 32ff16c1…
  /usr/local/libexec/go-hk-deployctl-runtime/artifact_runtime.py
                                                             81f91c7c… -> b32b2168…
  /usr/local/libexec/go-hk-deployctl                        db9d1584… -> d589743d…
  （deployctl 的 _ARTIFACT_SHA256 随之 81f91c7c… -> b32b2168…；其余四个 pin 不动。
    无新路径、无目录变更、不重启，装完做 sha256 readback 并观察一趟 tick。）
第 2 轮（再单独授权）：对同一 canonical RELEASE_CANDIDATE_V1 的源码发起**一张全新的**
fresh bounded TEST_PR（新 Request / 新 Task / 新 nonce；`go-boss-test-pr-52-3249a0c8589a`
的一次尝试已耗尽，**永不复用**），让 test-pr-v3 把镜像封存成 package_sha256，
再把它写进 CURRENT_CANDIDATE.json。之后 PACKAGE_BINDING 才有机会变 PASS。
两轮分开授权，便于区分 installation defect 与 build/durability defect。
不得执行真实 DEPLOY；不得在没有新的当次授权前安装。
RELEASE_GATES / CANARY（含 0114→0133 基线）/ AUTONOMY 是各自独立的 blocker，需分别处理。
```

（2026-09-16 更新：旧的 NEXT_ACTION「再发一张 fresh bounded VERIFY Request」**已失效** ——
新鲜的签名 VERIFY_OK Evidence 已经存在且在窗口内，读取它的门已 PASS。）

（2026-09-16 / B4-B1 更新：NEXT_ACTION 的**第一步**现在是「安装 B4-B1 + 一张新的 TEST_PR」，
不是「直接构建 plan bundle」。原因：候选目前没有任何可交付 artifact
（`artifact_package.durability = NOT_PROVEN`），而 `PACKAGE_BINDING` 现在要求
durability=PROVEN。先有真实封存包，plan bundle 才有可绑定的交付身份。
当前 readiness 仍是 `DEPLOY_READY=UNKNOWN`，无 mandatory FAIL，九门因缺 plan bundle 为 UNKNOWN。）

（次会话动手前先读 `docs/project/CC_V1_SCOPE_20260916.md`，并遵守 §8 的 DO_NOT_REOPEN。）

---

## 12. CI 状态（**红色，必须最先处理**）

```text
在 eef48f8（Scope Reset 提交，改了部署闸的 validate_bundle / load_context 签名并删除 approval 签名）
与 789d6ba（本文件）上，三个 workflow 为 failure：

  isolated-deploy-readiness       failure
  isolated-deploy-dry-run         failure
  isolated-request-visibility     failure

其余 6 个 success（contract / failure-closure / liveness-producer /
liveness-request-transport / projection / state-publication）。

判断：这两个 deploy 消费方（dry-run 派生 DEPLOY Task、readiness 装载计划）与
`validate_bundle(bundle,plan_id,authority_key,hk_key,at,approval_identity=None)` 的
签名变更一致地失败 —— 即 eef48f8 改了调用契约但**没有同步这两个消费方**。
本会话被要求只做交接，因此【未修】。

⇒ 下一次会话的第一件事（在 RELEASE_CANDIDATE_V1 之前）：取这三个 job 的日志，
  把没有传 approval_identity / 仍按旧签名调用 / 仍期待 approval 带 signature 的调用点补上，
  让 CI 回到全绿，再进入 §11 的 NEXT_ACTION。
  ⚠ 不要为了让 CI 变绿而放宽 fail-closed：正确修法是让调用方带上身份，
    而不是让 validate_bundle 接受缺失的身份。
```

## 附：本文件的读数口径

```text
全部身份值读于 2026-09-16 01:20–01:35 CST，来源：
  GitHub API（repository / branches/main / pulls/109 / issues 96–108）
  CC：/etc/go-command-center/boss-request-bridge-v1{,.manifest}.json、systemd 状态、
      target/CURRENT.json、transport journal、/var/backups 列表
  HK：/opt/go-hk-agent-rebuilt 内文件哈希、systemd 状态、docker ps、
      container 内 `alembic current`
未读取、未复制、未记录任何私钥、token、password 或云 AK/SK。
```
