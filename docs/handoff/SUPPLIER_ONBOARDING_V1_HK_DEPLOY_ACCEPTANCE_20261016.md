# Supplier Onboarding V1 — 香港部署与现场验收 Evidence

> **TASK ID：GO-B-HANDOFF-20261016** ｜ 执行：Eason / `chenzhenxi1-sudo` + WorkBuddy ｜ 日期：2026-10-16
>
> 配套交接文档 → `docs/handoff/SUPPLIER_ONBOARDING_V1_HANDOFF_20261016.md`
>
> **本文是 Evidence**：只记录本轮在 HK-STAGING-01 上**实际做过**的变更与**实测到的**结果。
> 采集窗口：2026-10-16T08:30Z – 10:57Z（香港主机本地时间 +08:00）。含两段：**部署 + 现场验收**，以及当日稍后补做的
> **注册邮箱验证码通道实装与端到端真实收码验收**。
> ⚠ 所有 SHA / 镜像 id / 计数均为**当时现场值**，复现时请重读。
> 📌 因当日又做了**第二次环境锁推进**（注册通道），§4 / §6 / §8.5 里部分身份值已被**后续**推进取代。
> 本文一律保留**当时值**并就地标注；**最新值以 §6.2 / §8.6 与交接文档 §4 为准**。

---

## 1. 范围与授权

本次执行依据 Eason 当次任务书 `GO-B-HANDOFF-FINAL-20261016` 中的显式授权：

| 授权项 | 是否使用 |
|---|---|
| 修改 / 测试 / 完善自己的 B 端代码 | ✅ 使用（2 个提交） |
| 在自己分支提交推送并更新 PR #592 | ✅ 使用 |
| 修复部署必需兼容性问题 | ✅ 使用 |
| 运行 CI、C13/C14 审核及必要测试 | ✅ 使用 |
| 检查香港真实环境 | ✅ 使用（全程只读复核） |
| 为本次部署配置必要的私有文件持久化目录 | ✅ 以**数据库表**方案替代宿主机挂载（见 §7） |
| 在备份及恢复方案验证通过后执行本次必要的香港测试数据库迁移 | ✅ 使用 |
| 通过 GO Forge 部署本次 B 端候选 | ✅ 使用 |
| 部署失败时用经验证的恢复方案处理 | 未触发（部署成功） |
| 部署成功后更新交接文档和 Evidence | ✅ 本文 |

会话中途另经 Eason 在选项交互中明确选择 **「授权本次世代推进」**：批准修改
`/etc/go-hk-deployctl/environment-graph-v1.json` 的 `migration_head`、用主机密钥重签 install fact、
并在已备份 / 已验证恢复的 HK 测试库上执行 `0145 → 0151` 迁移。

当日稍后，Eason **再次当次明确授权**：把**注册邮箱验证码通道持久写进香港环境锁**
（提供真实 SMTP 凭据与一个外部收码邮箱；并明确选择「**持久写进环境锁**」这条落地方式，而非临时 overlay）。
其代价是**第二次环境锁推进**：改 `runtime.env` → 重算两个模块常量 → 重钉 launcher → 重签 install fact → 重建 8 个业务容器（见 §6.2）。

**未使用**：修改 / 合并老板的 PR 或分支；修改 Production；绕过 Forge；伪造候选或 Evidence；
强行合并互不兼容的历史；丢弃香港现有业务数据；在恢复不可用的情况下迁移。

---

## 2. 执行时序（每一步都留证）

| # | 步骤 | 产物 / 结果 |
|---|---|---|
| 1 | HK 只读前置核查（DB prestate + 迁移数据洁净度） | `/root/onb/evidence/preflight-20261016T083829Z.json`、`preflight-20261016T083845Z.json`、`preflight2-index-feasibility-20261016.json` |
| 2 | 数据库恢复点 | `/home/go-forge/onb-b-end-rp-20261016T080853Z`、`…084514Z`、`…085239Z`（各含 `08-pre-change-db.dump` ≈ 16 MB + `SHA256SUMS` + `01-runtime.env` + install fact 血统 + `candidates-v1` 全量） |
| 3 | 候选镜像 materialise 进 HK docker store | `docker load`，镜像 `sha256:c7977e9b…` 落盘 |
| 4 | 迁移 dry run（可信程序、source 模式） | 隔离库演练通过 |
| 5 | **实库迁移** `0145 → 0151` | `/root/onb/evidence/live-migration-receipt.json`（见 §5） |
| 6 | 环图推进 + 候选事实 + 重签 install fact | `/var/backups/HK-CHANGE-20261016T090041Z-b-end-generation-0151/`（见 §6） |
| 7 | Forge 部署：`identity` → `precheck` → `recreate` → `verify` | `result: PASS`（见 §4） |
| 8 | 香港现场业务验收 | `/root/onb/evidence/acceptance-*`、`acceptance2-*`、`claim-readback-*`、`final-*`（见 §8） |
| 9 | 持久化补证：同镜像重建 api 容器 | 重建后文档 sha256 不变（见 §7） |
| 10 | 交接文档 + 本文 | 本提交 |
| 11 | （当日稍后）注册通道：**只增**备份 | `/var/backups/HK-CHANGE-20261016T104054Z-registration-email/`、`…T104322Z-registration-email-lock/`（含 `SHA256SUMS`） |
| 12 | 邮件配置与密码落到 same-path 隐藏目录 | `/var/lib/go-hotel/media-cache/.go-registration/{config.json,password}`（`700`/`600`） |
| 13 | **第二次环境锁推进**：`runtime.env` + 2 模块常量 + launcher + 重签 install fact | 见 §6.2 |
| 14 | 经部署缝合线重建 8 个业务容器 | api `85d44683efa4` → `3ed6aae14bd8`（healthy，镜像未变）；`redis`/`caddy` 未动 |
| 15 | 注册门复核 + 真实发码 + 真实收码注册 | `/root/onb/evidence/reg-e2e-20261016/`（见 §8.6） |
| 16 | 新账号继续走前段链路 + 审核段与归属守卫探针 | 16 PASS / 0 FAIL（见 §8.6） |

---

## 3. 部署物身份

```text
repo                yuguangzhi3836-glitch/GO
branch              chenzhenxi/supplier-onboarding-v1-20261016
PR                  #592  (draft=true, state=open, mergeable_state=clean)
source commit       3a8c43a56af742d48ca6b03b3eb6a3915d66caf2
application tree    af37d1837a54ed7f568138638c923027a318aab5
                    (== git rev-parse HEAD:application)
source fingerprint  76e19275992c31f8e44cfd80bd350bad3f94cd7db51b5f7b8dcd47f6245a825a

image id            sha256:c7977e9b0382627e2ef5b6161b6e4630e6a1584af6782c7fcae8e67f3c2ff82f
image reference     go-hk-test-pr:3a8c43a56af742d48ca6b03b3eb6a3915d66caf2
package sha256      5bf1599bb0951f093878ec3e61b82bb63b455ac7ecda2a209526fa72f1409beb
package bytes       116507136
config digest       8586164a870949cbaa4bdca8982d0b90f010589ab5d6d27f431361cae1175036
artifact store      go-hk-artifacts

build definition
  builder image     go-hotel:depth48-runtime-6d0fd905
                    sha256:1c9598d699c21620f4a3b489662f7b11be07acb46440516b74452dd2b6065132
  dockerfile        Dockerfile.go-application-python-v2
                    sha256:542c8703433e878f36b8569aaa15c7f76d11302d53644833592e66a99312dfca
  executor          test-pr-v4-runtime-root
  profile           go-application-python-v1

rollback relation
  REPLACES_CURRENT_KNOWN_GOOD
  previous_known_good_image_id = sha256:d093c89ec550f2540c3da8456fb8f9111c6e0ed86b6d688fa4679ab834089e8e
```

**test_result_identity**（候选事实内，说明本镜像是经既有 TEST_PR 通道产出的）：

```text
action_id             HK_STAGING_TEST_PR
executor_result       TEST_PR_OK
executor_version      test-pr-v4-runtime-root
source_pr_number      592
source_commit_sha     3a8c43a56af742d48ca6b03b3eb6a3915d66caf2
task_id               forge-b-end-592-20261016T083038Z
task_canonical_sha256 73682c7c2f05da281bd49f3953e03e982764a3f6c56d29d886ac9196ecd70506
nonce                 Zy2GB6kn2ocBioGrZs3MdcvLv8E-jK4s
```

---

## 4. Forge 部署证据

### 4.1 precheck（只读，全绿）

```text
candidate_fact_migration_head   == 0151_legal_entity_document_blob
environment_migration_head      == 0151_legal_entity_document_blob
migration_guard                 VERIFIED_NO_MIGRATION
require_same_artifact           PASS
precheck                        PASS
target containers (8)           all sha256:d093c89e…   ← 部署前的旧镜像
protected redis/caddy manifest  fd4781b267b69d51ab24f8b9cfc93cbf598a4ed79af69d4e1cff70e800f28427
```

### 4.2 recreate（`role=deploy`）

```text
result                      PASS
environment_lock            HELD
protected_non_target        UNCHANGED      （前后同一清单哈希）
media_mount                 MEDIA_MOUNT: SUCCESS
contract                    fcbca9471dbb9fc98156b192827c0bbbbf4e833e958a7fc8a012961581ce5973
elapsed                     1m35s
exit                       0

collector_verify:
  target_service_count            8
  all_target_services_same_image  true
  api_docker_health               healthy
  worker_process_liveness_pass    7
  alembic_current_equals_head     true
  health_semantic_overclaim       false
  application_health_proven_count 0            ← 明确不冒充「应用层健康已证」
```

### 4.3 独立 verify（部署后现场）

```text
api container  85d44683efa473f3b66e182d0866aeec80a98b34d3716054e3f9169707c0b920
  Image        sha256:c7977e9b0382627e2ef5b6161b6e4630e6a1584af6782c7fcae8e67f3c2ff82f
  Health       healthy
  RestartCount 0
  StartedAt    2026-10-16T09:12:34Z        （第二次 recreate 之后）
  alembic      current == heads == 0151_legal_entity_document_blob

docker ps（go-822-staging 项目，10 容器）
  api                              c7977e9b0382  Up (healthy)
  judgment-worker                  c7977e9b0382  Up
  mobile-engagement-worker         c7977e9b0382  Up
  mobile-push-receipt-worker       c7977e9b0382  Up
  mobile-push-worker               c7977e9b0382  Up
  outbox-worker                    c7977e9b0382  Up
  reconciliation-worker            c7977e9b0382  Up
  recovery-worker                  c7977e9b0382  Up
  caddy                            caddy:2.8-alpine   Up 8 hours   ← 未动
  redis                            redis:7.4-alpine   Up 8 hours (healthy)  ← 未动 && 未重启
```

⇒ **8 个业务容器全部替换为本候选；两个保护容器自始未动**（清单哈希前后一致）。
⇒ **未伪造 Command-Center 的 `_record_v2` deploy 记录** —— 驱动刻意省略该步骤。

---

## 5. 数据库迁移证据

`/root/onb/evidence/live-migration-receipt.json`：

```json
{
  "schema": "onb.b-end-live-migration.v1",
  "environment": "HK-STAGING-01",
  "database": "go_hotel_stg",
  "baseline_revision": "0145_source_latest_index",
  "target_revision": "0151_legal_entity_document_blob",
  "lineage_sha256": "6359dd413d8bfe653e4e3e8d387ffa596e7e3a7a51f8bbf21a255a9c6b15c387",
  "program_sha256": "526ace4129c76dfaa942afeb6dffa43d7b52227308005645fe4dad1ce1fac1de",
  "program_mode": "migrate",
  "candidate_image_id": "sha256:c7977e9b0382627e2ef5b6161b6e4630e6a1584af6782c7fcae8e67f3c2ff82f",
  "staged_source_tree": "/srv/onb-0151",
  "runtime_fingerprint_before": "4a53190459ca102737b408e78d5b081eaa5ac976c93e56e5ee98e61e1366f5f3",
  "runtime_fingerprint_after":  "4a53190459ca102737b408e78d5b081eaa5ac976c93e56e5ee98e61e1366f5f3",
  "runtime_env_sha256": "6682ff61f336fb8ff95a6585e9133c88c52a4eaa440a7aea6a6e06f771e607fc",
  "recovery_point": "/home/go-forge/onb-b-end-rp-20261016T085239Z",
  "deployment_performed": false
}
```

`live-pre.json`（迁移前，`verdict: "PASS"`）：

| 指标 | 迁移前 | 迁移后 |
|---|---|---|
| head / heads_count | `0145_source_latest_index` / 1 | `0151_legal_entity_document_blob` / 1 |
| 表 | 564 | 567 |
| 列 | 6 227 | 6 262 |
| `identity_user` | 1 006 | 1 007 |
| `hotel_canonical_profile` | 114 | 114 |
| 目标表存在 | 否（3 张均 null） | 是 |
| `pg_trgm` 扩展 | 已有 | 已有 |
| PostgreSQL | 18.4（`go_hotel_stg` / `go_app_stg`） | 同 |

**迁移前后运行时指纹完全相同**（`4a531904…`）⇒ 迁移**没有**改动运行时身份，只动了数据库。
`deployment_performed: false` 是**如实**记录：迁移程序自身没有执行部署（部署由 §4 的 Forge 通道单独完成）。

---

## 6. 世代推进证据

**备份目录**：`/var/backups/HK-CHANGE-20261016T090041Z-b-end-generation-0151/`

```text
SHA256SUMS                 2063 B
environment-graph-v1.json   201 B    （旧环图）
install-fact-v1.json       3384 B    （旧 install fact）
go-hk-deployctl           23600 B    （launcher 副本）
collector_runtime_regression.py 12587 B
candidates-v1/                       （全量副本）
candidate-contracts-v1/              （全量副本）
```

| 对象 | 推进前 | 推进后 |
|---|---|---|
| `environment-graph-v1.json` sha256 | `3dbbb6d7862dc76a19bce5f3e8be55b92a06d1f26131f5ec92a6f25e8b92cf8b` | **`ae2bc9dc2ba9696c16cd77269447f419fd7ff58386f1a904795d17c15026ba8e`**（248 B） |
| └ `migration_head` | `0145_source_latest_index` | **`0151_legal_entity_document_blob`** |
| └ `source_commit` | — | `3a8c43a56af742d48ca6b03b3eb6a3915d66caf2` |
| └ `environment` | `HK-STAGING-01` | `HK-STAGING-01`（未变） |
| `install-fact-v1.json` sha256 | `5d5756be…`（归档为 `install-fact-v1.20261007T131231Z-forge-560-authority.json`） | **`0a4b83cbfacd55d61b1c7e64d350c2f2496d817b9514c713cad506551ccc0bac`**（3 678 B） |
| └ `installation_id` | — | `20261016T090041Z-b-end-g0151` |
| └ `installer_identity` | — | `b-end-handoff-manual-generation-bump-0151` |
| └ `installed_at` | — | `2026-10-16T09:00:41Z` |
| └ `launcher_sha256` | `75cb1166…` | **`75cb116612a73819b25044c5596519809a971e9fdd7dc5420149b2fb62e96c8a`（未变）** |
| └ `runtime_digest` | `a864d56f…` | `a864d56f51c7d0acf20e37b8f61dee18d6ce5b618353e2cc19efd4bea971d96f`（未变） |
| └ `candidate_fact_set` | 4 | **5** |
| └ `signature_identity` | — | `hk-evidence-signer:SHA256:U/67Pyj6g18vLYjPNKWu/KEkqpWkMzXlaIFXyJ9CAMc=` |
| 候选事实文件 | — | `/etc/go-hk-deployctl/candidates-v1/fcbca9471dbb9fc98156b192827c0bbbbf4e833e958a7fc8a012961581ce5973.json`（2 340 B，文件 sha256 `92bd50869b4c4364f47c3451120dbb8845b230f2655b3b17ba9a76a5c37b05af`） |
| `collector_runtime_regression.py` | `76024513…` | `7c68cc40…`（**非钉住的离线自测**里的 `0145_source_latest_index` ×3 → `0151_legal_entity_document_blob`） |

**关键设计事实**：`canary_runtime.expected_head()` 与 `collector_runtime.resolve_revision()` 都从环图读 `migration_head`，
运行面模块中 `0145_source_latest_index` 字面量 **0 处**
⇒ **世代推进只需 3 份文档 + 1 个非钉住字面量**，**不需改任何被钉住的模块、不需重钉 launcher**（launcher sha256 与 10 个模块摘要逐条未变）。

序列化自检：新环图用同一 `canonical()` 规则**逐字节复现**旧文件格式（对旧内容回放验证 PASS），再写入新值。
签名自检：脚本内 `assert IF.key_id(priv.public_key()) == IF.key_id(IF.load_public_key(VERIFY_KEY))`，
并三次独立调用 `IF.load_installation()` 全部 PASS。

### 6.2 第二次世代推进（注册邮箱验证码通道，当日稍后）

**备份目录**：`/var/backups/HK-CHANGE-20261016T104322Z-registration-email-lock/`（含 `SHA256SUMS`）。

| 对象 | 推进前 | 推进后 |
|---|---|---|
| `runtime.env` | `6682ff61f336fb8ff95a6585e9133c88c52a4eaa440a7aea6a6e06f771e607fc`（1 281 B） | **`7e89dcb16cf87212fb6daf9c6e16d383590fc7c229655248b6cf717e358277f8`**（1 410 B） |
| └ 新增键（2） | — | `REGISTRATION_VERIFICATION_ENABLED=true`、`REGISTRATION_EMAIL_CONFIG_PATH=/var/lib/go-hotel/media-cache/.go-registration/config.json` |
| `deploy_runtime.py` | `06a3eebc…` | `66b94aabfeb182669c38b895869ba687350e092aebcf0f0a319895c17be6af84` |
| `collector_runtime.py` | `a7f55a7c…` | `3516384dd7465152202a4fa2831e99d19d59f0bcaa836accd158650c543e5293` |
| launcher | `75cb1166…` | `9e152dd18d951cc73f0b54222ebfb8d9fc24eceb70fbc57a6b57e99a17ab1b4f` |
| `install-fact-v1.json` | `0a4b83cb…` | `15a6b27745a8a73119f8349812dcc09a2cf0b19835563410cd5fa77201f6f42b`（3 673 B） |
| └ `installation_id` | — | `20261016T104322Z-registration-email` |
| └ `installer_identity` | — | `registration-email-channel-v1` |
| └ `runtime_digest` | `a864d56f…` | `c0ccb5af070bb198e1aa20276c9db1cbe9870bd5b1ac91efbdf95ed50f66d947` |
| `environment-graph-v1.json` | `ae2bc9dc…` | `ae2bc9dc…`（**未变**） |
| `signature_identity` | — | `hk-evidence-signer:SHA256:U/67Pyj6g18vLYjPNKWu/KEkqpWkMzXlaIFXyJ9CAMc=`（**未变**） |

**模块摘要**：10 个中**恰好 2 个**移动（`deploy_runtime` / `collector_runtime`），其余 8 个**逐字节未变**：
`canary 50284e00…`、`rollback 8467c240…`、`artifact 736b5571…`、`migration_guard 89a0cc30…`、
`media_mount 92af6bfc…`、`candidate_source f9855b4c…`、`install_fact 86cf09ba…`、`candidate_fact b378a472…`。
`load_installation()` = **PASS**。

**重建**：走**部署缝合线** `media_mount.recreate(runner, lambda a: runtime._run(runner, a, 300), extra_files=[runtime._override(image)])`，
8 个业务容器全部换新；**`redis` `0a52d62367bd` / `caddy` `958524e18dca` 的容器 ID 未变**。

> ⚠ **踩坑记录（假 PASS）**：首次重建**漏了 `runtime._override(image)`** ⇒ compose 回退到本地不存在的镜像名
> `go-hotel:aoluguya-direct-r3-1-20260906`，`up` 失败；但 `ProductionRunner.run` 用 `check=False` **不抛异常**，
> `media_mount.verify()` 又只检查**运行中容器**的挂载（旧容器本来就有）⇒ 报 `MEDIA_MOUNT: SUCCESS` 而**容器 ID 一个未变**。
> ⇒ **判据必须是「容器 ID 是否变化」，不能只看 `MEDIA_MOUNT` 字样。**

**配置与密码落点**：base compose 的 8 个服务**无 volumes**，唯一挂载是媒体缓存且为 **same-path bind**
⇒ 秘密放进 `/var/lib/go-hotel/media-cache/.go-registration/`（目录 `700`、文件 `600`），宿主与容器**同一绝对路径**成立，
**无需新增挂载、不改 compose**。密码由本地实验室凭据文件经**管道**送抵香港（**字节不进模型上下文**），两端 sha256 一致
（`2c1c81b2da4175d407720b804cf006adc29e1ef0b16e5cb34cfa3b3a999aeeee`，13 B）。

---

## 7. 文档持久化证据（决定性）

**设计**：`services/document_store.py::_uses_database()` = 「未设 `GO_SUPPLIER_DOCUMENT_DIR`」。
香港**没有**该环境变量 ⇒ 自动改走迁移 `0151` 的表 `legal_entity_document_blob`。
选择理由见 0151 docstring：**八个业务容器每次部署都会丢弃容器文件系统**，本机卷不随部署搬运，
而数据库表随备份 / 恢复整体搬运，且无需新申请宿主机挂载。

| 检查 | 实测 |
|---|---|
| 容器内 `find / -name "led_*"` | **count = 0** |
| `legal_entity_document_blob` 行数 | 1（内容寻址去重） |
| blob 行 | `storage_key = led_e5a636ac00ea3c175d3193c5d05df60ded156dd466043c70.pdf`，`sha256 = e5a636ac00ea3c175d3193c5d05df60ded156dd466043c70d254507ec277e4c2`，`size_bytes = 193`，`mime_type = application/pdf` |
| api 容器重建（`09:12:34Z`）后读回 | 两份文档 `GET …/content` 仍 200，**sha256 完全一致** |
| supplier 文档宿主机挂载 | **无**（`docker inspect` 的 Mounts 里没有） |

**诚实说明**：验收上传的营业执照与签署合同是**同一个 193 字节合成 PDF**
⇒ `legal_entity_document` 2 行共享同一 `storage_key`，去重成 1 个 blob。
合同服务只校验「存在 + 模板 sha 匹配」，**不解析合同正文** ⇒ 可接受的测试夹具，但**不是**对合同正文的真实性验证。

⇒ `DOCUMENT_STORAGE_PERSISTENT = YES`，实现方式 = **数据库表**。

---

## 8. 现场业务验收

入口：`https://staging-api.goaidirect.com`（真实 HTTPS ingress，真实 cookie，变更端点带 `X-CSRF-Token` 双提交）。

### 8.1 公开面 + 无关路由冒烟

```text
/health 200   /partner/ 200   /supplier-console/ 200   /go-admin/ 200   /go-app/ 200
/console-assets/api.js 200    /bff/auth/policy 200     /docs 200         /openapi.json 200
登录后只读路由：/bff/supplier/my-hotel、/onboarding/contract、/legal-entity、
                /legal-entity/documents、/hotel/search  → 全部 200，无 5xx
```

⇒ **既有业务面未被破坏**。

### 8.2 阶段一（`/root/onb/evidence/acceptance-20261016T091022Z`）32 PASS / 7 FAIL

**7 项失败全部定位为验收脚本自身缺陷，非产品缺陷**，逐条如下：

| 缺陷 | 症状 | 根因 | 处置 |
|---|---|---|---|
| 状态码被输出污染 | `save claim (returned GET hotel/search?… HTTP 422 …422)` | `post()`/`get()` 把格式化行写进 stdout，被 `C=$(…)` 一并捕获 | 显示语句改 `>&2`；**已修** |
| **认领请求根本没发出** | claim 未落库 ⇒ 提交 `409 SUPPLIER_PROFILE_INCOMPLETE:HOTEL_RELATIONSHIP` | `sec 5` 只构造了 `claim.json` 却**从未 `PUT /bff/supplier/hotel/claim`**；`$C` 还是搜索的状态码 | 拆成两轮并确认持久化；**本轮另做 §8.4 现场回读补证** |
| `supplier_id` 取空 | 队列匹配 `SEEN=NO`、案件详情 URL 为空 | 从错误响应体取值 | 改为常量 `SUP`；**已修** |
| 合同 sha 取错 | `409 CONTRACT_TEMPLATE_CHANGED` | 把 `template.marking` 当成 `template.sha256` 传 | 改取 `d['data']['template']['sha256']` 并与下载文件比对；**已修** |
| 顺序不当 | 同一轮内认领与提交相邻 | 认领未落库即提交 | 拆两轮；**已修** |
| `jget` 报错 | `NameError: sys` | 用了未 import 的 `sys` | 加 `import json,sys`；**已修** |
| 证据目录 jar 未预建 | 阶段二首跑 `awk: cannot open …applicant.jar` ⇒ cookie 未落盘 | 重定向到不存在的文件 | jar 赋值后 `: > "$JA"`；**已修** |

**本阶段确已证明**（原始响应体留存于该目录）：三合一登录 200、`/bff/auth/me` 回本账号、
`PUT` 企业资料 200、法人 `stored uscc == input`、**执照 raw octet-stream 上传 201**、
下载字节 sha256 与上传一致、`GET meta` 200、酒店搜索 200、**审核员跨角色读取同一执照字节一致**、
合同模板 200（1 431 B / `fa639473…`）、`my-hotel` 200。

### 8.3 阶段二（`/root/onb/evidence/acceptance2-20261016T091201Z`）26 PASS / 0 FAIL

```text
申请人登录 200 + 会话归属校验（/bff/auth/me）               PASS
前置状态 UNDER_REVIEW                                      PASS
GO Admin 队列包含该案（items[] 含 sup_edaab1be…）            PASS
案件详情 200                                                PASS
decision=NEEDS_CHANGES 200，申请人回读 state=NEEDS_CHANGES   PASS
   note = "执照影像不清晰，请重新上传"
   findings = [{"code":"LICENSE_ILLEGIBLE","message":"影像模糊"}]
修正后重提 → 回 UNDER_REVIEW                                PASS
decision=APPROVE 200 → state=VERIFIED                       PASS
   hotel_id = hotel_ac72aa53c89d4c3984b72436cb85f617
   hotel_registration_direct_id = hregdir_f9d4bf65e75e4638a242f1493f79561e
my-hotel: hotel.state=APPROVED / relationship_type=OWNER /
          go_direct_state=GO_DIRECT_VERIFIED                PASS
合同 can_confirm=true / blockers=[] /
     模板 sha 与下载文件一致                                 PASS
SIGNED_CONTRACT 上传 201（led_22096878eaf04692adf9bcb89f601009）  PASS
合同确认 200 → state=CONTRACT_ACTIVE / business_ready=true    PASS
数据库：commercial_case=1 / hotel_registration_go_direct=1（APPROVED） PASS
```

### 8.4 认领路径现场回读（`/root/onb/evidence/claim-readback-20261016T091904Z`）

用于补上 §8.2 中「阶段一脚本没发认领请求」留下的证据缺口：

```text
POST /bff/auth/login (申请人)                       200
GET  /bff/auth/me                                  200

GET  /bff/supplier/hotel/claim                     200
  persisted claim:
    mode                  EXISTING
    relationship_type     OWNER
    hotel_id              hotel_ac72aa53c89d4c3984b72436cb85f617
    hotel_display         {"name":"敖麓谷雅",
                           "address":"黑龙江省哈尔滨市松北区创新三路800号",
                           "claim_state":"AVAILABLE","page_state":"DRAFT"}
    hotel_registration_direct_id  hregdir_f9d4bf65e75e4638a242f1493f79561e
    saved_at              2026-10-16T09:10:48+00:00
    approved_at           2026-10-16T09:12:02+00:00
    conflict              null

GET  /bff/supplier/my-hotel                        200
    state=CONTRACT_ACTIVE  business_ready=true  business_enabled=false
    supplier_id=sup_edaab1be801c42759303abf3195e234e
    hotel: claimed=true state=APPROVED relationship_type=OWNER
           go_direct_state=GO_DIRECT_VERIFIED completeness_bps=6900
    contract: template_sha256=fa6394731990f7512c16c62b6edb13a902df4ccac1c907e5705a035abd665f91
              template_version=2026-10-06-test-v1

PUT  /bff/supplier/hotel/claim                     409 HOTEL_CLAIM_NOT_EDITABLE
     （案件已过可编辑状态 → 状态守卫正确生效）

GET  /bff/supplier/onboarding                      200
    state=CONTRACT_ACTIVE / supplier_id=sup_edaab1be… /
    review_note="资料齐全，通过（B7 验收）"
```

⇒ **认领写入确实持久化**（`saved_at` = 09:10:48Z），且端点的状态守卫在超状态时正确拒绝。

### 8.5 最终快照（`/root/onb/evidence/final-20261016T091418Z`）

```text
launcher_sha256      75cb116612a73819b25044c5596519809a971e9fdd7dc5420149b2fb62e96c8a
driver_sha256        30d6f94eb6e611a84ea2bb832a2999d82e71f445ab453d9208eb3babe1c0481a
contract             fcbca9471dbb9fc98156b192827c0bbbbf4e833e958a7fc8a012961581ce5973
asked_candidate      sha256:c7977e9b0382627e2ef5b6161b6e4630e6a1584af6782c7fcae8e67f3c2ff82f
expected_current     sha256:d093c89ec550f2540c3da8456fb8f9111c6e0ed86b6d688fa4679ab834089e8e
installed_identity   {installation_id: 20261016T090041Z-b-end-g0151,
                      launcher_version: 0.7.0-environment-lock,
                      runtime_digest: a864d56f…}
容器                  10 个全部合规（8 业务 = c7977e9b0382；caddy/redis 未动）
alembic              current == heads == 0151_legal_entity_document_blob
                      Parent: 0150_identity_login_identifiers
                      Path:   /app/alembic/versions/0151_legal_entity_document_blob.py
数据库计数            identity_user 1007 / hotel_canonical_profile 114 /
                      commercial_case 1 / legal_entity 1 /
                      legal_entity_document 2 / legal_entity_document_blob 1 /
                      hotel_registration_go_direct 1 (APPROVED, hotel_ac72aa53…)
```

### 8.6 注册邮箱验证码端到端（当日稍后，`/root/onb/evidence/reg-e2e-20261016`）

```text
前置（现场回读）：release_gate.registration_verification.status   NOT_READY -> READY
                  reason                                           REGISTRATION_…_NOT_CONFIGURED -> null
                  verification_channels                            []          -> ["email"]
                  verification_test_code                           —           -> null（真实投递）

发码  POST /v1/registration/challenges
      -> status=SENT  challenge_id=VBmNk0bfNUgo20yXky899-LyMazRC3go  ttl=600s
      （服务端未抛 REGISTRATION_EMAIL_SEND_FAILED
        ⇒ 香港用真实凭据完成 smtpdm.aliyun.com:465 的 TLS 登录，且服务商接受了对外投递）

收码 -> POST /bff/auth/supplier/register（带真实收件箱取到的 6 位码）
      -> 账号建成，state=PROFILE_DRAFT
三合一登录：新账号以 username / email / phone 各登录一次                    全 PASS
单次性：同一验证码二次使用                                                 被拒 PASS
前段链路：企业资料 -> 法人(USCC) -> 执照上传 -> 酒店搜索 -> 认领 -> 提交 -> UNDER_REVIEW   PASS
审核段：退回 -> 重提                                                        PASS
        对「已被前一验收供应商持有」的酒店执行 APPROVE
        -> 409 CLAIM_CONFLICT（归属守卫按设计拒绝）                          PASS
        在位持有人未被改动；hotel_registration_go_direct 仍为 1 行           PASS
合计 16 PASS / 0 FAIL
```

> ⚠ §8.2 / §8.3 的验收账号（`sup_edaab1be…`）是在注册门**尚未开启**时由**产品自身写边界**创建的；
> §8.6 才是**经真实邮箱验证码自助注册**出来的账号。**两者不是同一账号，也不可互相替代**：
> §8.2/§8.3 覆盖全链（含合同段），§8.6 覆盖「真实注册 → 提交 → 审核段（退回/重提 + 归属守卫负例）」。

---

## 9. 边界自证（本轮在 HK 上**只**做了这些）

1. `/home/go-forge/onb-b-end-rp-*` 三个恢复点（**只增**）；
2. `/root/onb/` 下我的脚本与 `/root/onb/evidence/` 各证据目录；
3. `/home/go-forge/forge-b-end-drivers/forge-b-end-driver.py`（`root:root 700`）；
4. `/srv/onb-0151`（迁移源码只读暂存）；
5. **已授权的一次实库迁移**（`0145 → 0151`：3 表 + 4 索引 + 1 列族 + 1 约束 + 1 002 行 email 回填）；
6. **已授权的两次世代推进**：
   ① 环图 + 候选事实 + install fact + `/var/backups/HK-CHANGE-20261016T090041Z-b-end-generation-0151/`；
   ② 注册通道 `/var/backups/HK-CHANGE-20261016T104322Z-registration-email-lock/`（含 `runtime.env`、两个模块副本、launcher、install fact）；
7. `docker load`（materialise 候选镜像）；
8. **通过部署缝合线三次 `recreate`**（部署 + 持久化验证 + 注册通道生效）；
9. 邮件配置与密码：`/var/lib/go-hotel/media-cache/.go-registration/{config.json,password}`（`700`/`600`，**只增**）；
10. 验收产生的普通业务行：2 账号 / 2 案件 / 1 法人 / 2 文档 / 1 blob / 1 酒店注册 / 1 挑战，以及验收期间新增的审计事件行。

**未做**：未碰老板的 PR；未动 `main`；未重启 / 停止 `redis` 与 `caddy`（保护容器清单哈希前后相同）；
未绕过 Forge；未伪造候选事实 / Evidence；未伪造 Command-Center deploy 记录；
未直接 INSERT 数据库创建验收账号（走的是**产品自身写边界**或**真实注册门**）。

⚠ **本轮确实改了** `runtime.env`、两个被钉住的运行时模块、launcher 与 install fact —— 但这是**当次已获授权的第二次世代推进**，
且**同步重签了 install fact**（`load_installation()` PASS），**不是**绕过签名链。此处如实记录，不作淡化。

---

## 10. 本轮**未**闭合的事项（如实列出，不包装）

| 事项 | 性质 | 为什么停在这里 | 由谁处理 |
|---|---|---|---|
| ~~香港注册邮箱验证码通道未配置~~ | ✅ **已闭合**（当日） | 经 owner **当次授权**完成**第二次环境锁推进**（§6.2）并端到端**真实收码**跑通（§8.6） | — |
| **合同为测试夹具** | 资产缺口 | `PRODUCTION_CONTRACT_TEMPLATE_REQUIRED`，正式商业合同模板尚未接入 ⇒ **不是正式商业验收** | owner 提供正式模板 |
| **`main` 整合** | 结构性阻塞 | 两线无共同祖先 + `0135` 迁移链冲突 + 118 个 main-only 路径 ⇒ 需刻意设计的 source-composite | owner 决策 |
| **真实浏览器双身份回归（HK）** | 验证手段差异 | 本轮香港以 HTTPS + 真实 cookie（含 CSRF 双提交）的 **HTTP 端到端**完成，覆盖同一流程；真浏览器载体只在本机实验室跑过（48/48 + 21/21） | 可随时补（不阻塞） |
| `/internal/*` 无鉴权（SEC-01） | 既有债务 | 本轮**未修**（不在授权范围）；注意香港审核台正是走该路径 | 另立任务 |
| 合同正文未做真实性校验 | 见 §7 诚实说明 | 验收用的是 193 字节合成 PDF；服务不解析正文 | 与正式合同模板一并处理 |
| `document_store.py` 第 6 行 docstring 陈旧（写 multipart） | 纯注释 | **故意未修**，以免污染已验证的 `application/**` 字节（`af37d183…`） | 下次产品代码变更时顺手修 |
