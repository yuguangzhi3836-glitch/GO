# CC V1 CURRENT HANDOFF · 2026-09-16

> 面向**下一次全新 WorkBuddy 会话**的唯一入口文件。所有身份值均于 2026-09-16 01:20–01:35 CST
> **从实况重新读取**（未从旧会话复制）。本文件不含任何 private key / token / password / AK。
>
> 读取顺序建议：本文件 → `docs/project/CC_V1_SCOPE_20260916.md`（范围权威）→ 才动手。

> **2026-09-16 修订说明（补 TD-J，未改写其余段落）**：本文件 01:26 CST 的读数之后，以下事实已被
> 后续工作取代；读时以更晚的权威件为准，**不要按本文的旧描述行动**：
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
> * TD-J：**仓库修复已进 PR #109，live 未安装**（见 §9）；B3 因此仍未清。
>   本轮报告 + 安装方案（未执行）：`docs/control-plane/hk-staging/TDJ_EVIDENCE_WORKSPACE_FIX_20260916.md`

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
     live: hk_agent/transport.py 6f329b2eae7bc627229002e998cf17ee9d95b2e1fb6fc7cb22a508b52ad5fbe0
     repo: hk_agent/transport.py 340da98f95acdb0c212aa116681da8d8344c6da306e44dfcf332c67ee1957de8
           （TD-J 修复，PR #109 / 3819b55a，**未安装**：live 仍是上面那版）
     proof: REAL — TEST_PR 受控失败 → 签名 FAILED Evidence → 投影 EXECUTION_FAILED / retry_permitted=false
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
                      hk_agent/transport.py 6f329b2eae7bc627229002e998cf17ee9d95b2e1fb6fc7cb22a508b52ad5fbe0
                          （= #97 失败闭环版本）
                          ⚠ 仓里已有一个**未安装**的替代版本 340da98f…（TD-J 修复，见 §9）
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

B3  没有新鲜的 VERIFY
    readiness 的 VERIFY 门为 FAIL（最近一次真实 VERIFY 已超出 86400s 窗口）
    根因已定位并复现 = TD-J（见下方技术债）：同一趟 run_once 的第二条 Evidence 没有 clone 目标
    2026-09-16T05:02:20Z 那张 fresh VERIFY 的**执行器层面已通过**（deployctl 只返回 SUCCESS/VERIFY_OK），
    失败在执行之后：kind=EVIDENCE_PUBLISH_FAILED / stage=evidence_publish /
    reason_code=GITHUB_TRANSPORT_REJECT
    ⇒ 没有签名 Evidence 就不算清掉，门仍 FAIL
    仓库修复已进 PR #109（transport.py 340da98f…），但 **live 未安装、VERIFY 未重发**

B4  没有可用的部署计划 bundle（plan + approval + canary/preflight task+evidence）
    ⇒ PACKAGE_BINDING / DEPLOYMENT_PLAN / CURRENT_RUNTIME / CANARY / RELEASE_GATES /
      BRIDGE_ACCEPTANCE 六门 UNKNOWN，无法到 DEPLOY_READY=YES
    （CANARY 在现存 live executor 要求它时必须 PASS；不要新增 gate）

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
      · repository fix = IMPLEMENTED / TESTED；live install = **NOT_INSTALLED**；fresh VERIFY = **NOT_RETRIED**
      · 同类未修站点（记录在案，本轮不动）：prepare_rollback_handoff 仍 clone 到固定
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
固定八服务拓扑与 `redis`/`caddy` 保护名单已在 gate 中硬编码。

## 11. 下一会话唯一入口

```text
NEXT_ACTION=
Implement/finalize RELEASE_CANDIDATE_V1 admission Gate,
then select one real compliant product candidate and drive it through real TEST_PR.
```

（本会话不执行。次会话动手前先读 `docs/project/CC_V1_SCOPE_20260916.md`，并遵守 §8 的 DO_NOT_REOPEN。）

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
