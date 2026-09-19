# CCV1-102 · 「香港两日未审查成果总复审包」受理与物料核验报告

- 报告日期：2026-09-19
- 受理对象：`Draft: HK two-day unreviewed work-product review package`（其本身 = **PR #230**，固定 head `d0f13b55bd8e...`，1 文件 / +92）
- 执行身份：`Eason-13490` / WorkBuddy（**非**独立香港审查身份，见 §3-F6）
- 授权口径：本次只做 **只读** 物料核验（GitHub REST 读 + 本地 git 只读）。**零 SSH、零部署、零评论、零推送、零合并、未改任何 PR 元数据。**
- 证据目录：`D:\Code\Workbuddy\.workbuddy\tmp\ccv1-102\`
  （`pr_meta.json`、`pr217_files.json`、`tree_diff.json`、`fetch*.py`）

---

## §0 结论先行

| 结论项 | 判定 |
|---|---|
| 14 个候选 PR（#216–#229）是否真实存在、是否 Draft | **是**，14/14 存在，14/14 Draft，base 与 head 与包内 pin 表**逐条相符** |
| 包内固定 head 表（12 个显式 SHA） | **11/11 显式 SHA 全部与现场一致**（#216/#218/#219 按包内「以 PR head 为准」取现场值） |
| #217「219 个变更原件 = 35 源码 + 33 测试 + 151 Evidence」 | **完全属实**（API 复算 219，分桶 35/33/151） |
| 包内「#221→#222→…→#227 连续叠加链」 | **不完整** —— 真实链条是 **#216→#217→#219→#221→#222→#223→#224→#225→#226→#227（10 段）** |
| #229「C14 FAIL / C13_RUNNER = NOT_RESTORED」 | **成立，且比包内描述更严重**（见 §3-F4：门禁硬编码绑定三元组在仓库内自相矛盾） |
| #217 当前 head 的 source binding 是否可复现 | **可复现，但存在原件版本漂移**（round2 SOURCE_BINDING 描述的是**上一个 head**，见 §3-F2） |
| 「独立香港审查身份」是否可满足 | **不可满足** —— 本机令牌身份 = `chenzhenxi1-sudo` = 实现方账号（见 §3-F6） |
| 可否给出 C13/C14 签名判定 | **不可以** —— 无独立身份 = 无签名资格；给出即属伪造独立性声明 |
| 总表要求（#229 前 C13 不恢复 / #217 keep Draft / 其余 keep Draft / HK-Staging·Final Release·Production HOLD） | **现场事实与之一致，无需变更即已满足** |

---

## §1 物料核验（Step 1，逐 PR 固定 head）

数据来源：`GET /repos/yuguangzhi3836-glitch/GO/pulls/{n}`、`.../pulls/{n}/files`、`.../commits/{sha}/check-runs`，均只读。
抓取时间：2026-09-19 17:0x CST。

| PR | author | 固定 head（现场） | head 分支 | base 分支 | changed_files | CI（该 head 上） | Draft |
|---:|---|---|---|---|---:|---|---|
| #216 | `yuguangzhi3836-glitch` | `ff0005dacc6e3aa6d6ea27003a3ccd5deb4f1de3` | `fix/consumer-entry-requirements-20260918` | `fix/aoluguya-hero-public-gallery-20260918` | 21 | **1 run：`date-range` = failure** | 是 |
| #217 | `yuguangzhi3836-glitch` | `0c3da07bc32009dee16c69125111f8e4ea9d546b` | `feat/account-holder-library-import-20260918` | `fix/consumer-entry-requirements-20260918` | 219 | 0 run（无 CI） | 是 |
| #218 | `yuguangzhi3836-glitch` | `d66c86070779...` | `ops/ctrip-learning-cell-upgrades-20260919` | `main` | 1（仅 1 个 md） | 0 run | 是 |
| #219 | `yuguangzhi3836-glitch` | `5f62478b970f...` | `feat/ctrip-depth-round1-20260919` | `feat/account-holder-library-import-20260918` | 17 | 0 run | 是 |
| #220 | **`chenzhenxi1-sudo`** | `acdef3bead59b2f6635e9b55681de4f995ccf6b4` | `cc/candidate-convergence-wp1-20260918` | `main` | 65 | **9 run：9 success** | 是 |
| #221 | `yuguangzhi3836-glitch` | `181e7568b8ed640aba5c4b6a932f4d6c6e74c5b3` | `feat/ctrip-depth-round2-20260919` | `feat/ctrip-depth-round1-20260919` | 25 | 0 run | 是 |
| #222 | `yuguangzhi3836-glitch` | `fc521219c53b692df91346669e704f4e6b475df1` | `feat/hotel-library-round3-20260919` | `feat/ctrip-depth-round2-20260919` | 23 | 0 run | 是 |
| #223 | `yuguangzhi3836-glitch` | `f66129b718dfb9db2a156a46c69cd58674a2de0b` | `feat/cell-depth-review-20260919` | `feat/hotel-library-round3-20260919` | 25 | 0 run | 是 |
| #224 | `yuguangzhi3836-glitch` | `5200c0a2f440781749a0183842b60f0ed6b03920` | `feat/hotel-evidence-comparable-quotes-20260919` | `feat/cell-depth-review-20260919` | 16 | 0 run | 是 |
| #225 | `yuguangzhi3836-glitch` | `5a708b38de32a52f92384275ab1c30ccf79c53c1` | `feat/hotel-reviewed-publication-20260919` | `feat/hotel-evidence-comparable-quotes-20260919` | 22 | 0 run | 是 |
| #226 | `yuguangzhi3836-glitch` | `f7595f4904d4415459fd0a938adaa35e01353959` | `feat/hotel-review-console-20260919` | `feat/hotel-reviewed-publication-20260919` | 47 | 0 run | 是 |
| #227 | `yuguangzhi3836-glitch` | `af1c2d5744aef5212eb139f93b150ec7ae171b38` | `feat/nationwide-registration-library-20260919` | `feat/hotel-review-console-20260919` | 66 | 0 run | 是 |
| #228 | `yuguangzhi3836-glitch` | `5f83dc31d56d7ff0e4755a8eac01ac086e084121` | `feat/hk-staging-registration-email-config-verify-20260919` | `main` | 6 | **3 run：2 success / 1 failure（`isolated-contract`）** | 是 |
| #229 | `yuguangzhi3836-glitch` | `2a6b5ddbd19a58becf09063c9bc253d9613b929f` | `cc/c13-isolated-acceptance-v1-20260919` | `main` | 3 | 0 run | 是 |

补充事实：

- 全仓 **open PR = 144**；其中 `author:yuguangzhi3836-glitch` = **142**，`author:chenzhenxi1-sudo` = **2**，即 **#220 与 #61**。
- 包内给出的「PR 全集」链接用 `author:yuguangzhi3836-glitch` 过滤 —— 该过滤**会排除 #220**，与包内把 #220 纳入「本次收拢范围」自相矛盾。
- **#230 就是本审查包本身**（1 文件 `docs/review/HK_TWO_DAY_UNREVIEWED_WORK_PRODUCT_REVIEW_PACKAGE_20260919.md`，+92），同为 Draft。

### #217 原件构成复算

```
GET /pulls/217/files  →  219 条
分桶：application code 35 · tests 33 · evidence 151   ← 与包内「35 / 33 / 151」完全一致
Evidence 顶层目录：
  evidence/cell-depth-20260918/{c01_c07,c02_c03,c04_c05,c04-unknown,c06_c09,c08_c10,c11_c12,c13,c14}
  evidence/pr217-account-holder-round2-20260918/SOURCE_BINDING.json
```

---

## §2 叠加链核验（纠正包内描述）

**方法**：逐个比较「上一 PR 的 head 分支名」与「下一 PR 的 base 分支名」是否相同（GitHub API 现场值，非推断）。

```
#216 head fix/consumer-entry-requirements-20260918
   → #217 base fix/consumer-entry-requirements-20260918        ✔ 相接
#217 head feat/account-holder-library-import-20260918
   → #219 base feat/account-holder-library-import-20260918     ✔ 相接
#219 head feat/ctrip-depth-round1-20260919
   → #221 base feat/ctrip-depth-round1-20260919                ✔ 相接
#221 head feat/ctrip-depth-round2-20260919
   → #222 base feat/ctrip-depth-round2-20260919                ✔ 相接
#222 head feat/hotel-library-round3-20260919
   → #223 base feat/hotel-library-round3-20260919              ✔ 相接
#223 head feat/cell-depth-review-20260919
   → #224 base feat/cell-depth-review-20260919                 ✔ 相接
#224 head feat/hotel-evidence-comparable-quotes-20260919
   → #225 base feat/hotel-evidence-comparable-quotes-20260919  ✔ 相接
#225 head feat/hotel-reviewed-publication-20260919
   → #226 base feat/hotel-reviewed-publication-20260919        ✔ 相接
#226 head feat/hotel-review-console-20260919
   → #227 base feat/hotel-review-console-20260919              ✔ 相接
#216 base = fix/aoluguya-hero-public-gallery-20260918  ← 非 main，链根在更早的分支上
```

**结论**：叠加链不是包内写的 7 段，而是 **10 个 PR / 9 个连接段**：`#216 → #217 → #219 → #221 → #222 → #223 → #224 → #225 → #226 → #227`。
包内把 #216/#217/#219 划到「C 端/OTA/GO Trips」线、把 #221–#227 当作独立叠加链，**与现场拓扑不符**：这三者正是叠加链的开头三段。
因此「在 #227 固定 head 做统一冻结回归」实际上等于对**整条 10 段链**做回归，而不是对 7 段做回归。链根又不在 `main` 上。

---

## §3 核查发现

### F1 — 叠加链段数与包内描述不符（已确认）
见 §2。属包内**事实性偏差**，影响 Step 2 的分线复审划分与 Step 5 的冻结回归范围。

### F2 — #217 当前 head 内的 round2 SOURCE_BINDING 描述的是「上一个 head」（已确认，可复现）

`evidence/pr217-account-holder-round2-20260918/SOURCE_BINDING.json`（**位于 `0c3da07b` 内**）声明：

```json
"base_commit": "1d1b6b45a5e6e3507bda8c4f3d9ca7b7c8e7175c",
"application_tree": "9206696542000e020601f14233c339cfec6b364c",
"application_file_count": 1421,
"application_source_sha256": "0034eefc..."
```

独立复算（本地 git + GitHub tree API）：

```
application/ 的 git tree oid
  0c3da07bc3  (#217 当前 head, 2026-09-19T07:05) → f6d329352dd8484010036448810a927d5eec4be7   blob=1441
  0cdff19160  (#217 上一个 head, 2026-09-18T16:44) → 9206696542000e020601f14233c339cfec6b364c   ← 与此处声明一致
  1d1b6b45a5  (round2 的 base_commit)              → aef958a0f68d4096a6686a92630898340ca7e7a0
  ff0005dacc  (#216 head / #217 base)              → 69f8ba35d8f483b27142e6a86cb35fa9993ec70a
```

两个 tree 的差异极干净：30 个顶层条目**完全相同**，仅 `application/src` 与 `application/tests` 两个子树的 oid 不同（即末次提交 `0c3da07b` 的改动）。

**含义**：该 round2 binding 的 `application_tree` / `file_count` 描述的是 `0cdff19160` 的 `application/`，**不是它自己所在的 `0c3da07b`**。这份原件随末次提交一起上船，却没有随之更新 —— 属于「旧候选 Evidence 出现在当前候选 head 内」。而 `evidence/cell-depth-20260918/c14/SOURCE_BINDING.json`（同一 head）声明的 `application_git_tree: f6d32935…` / `application_files: 1441` **与现场完全吻合**，并且是唯一声明了 `fingerprint_algorithm` 的一份。

⇒ 同一 head 内存在**两份互相矛盾的 application binding**，其中与现场一致的是 c14 那份，round2 那份是上一版的。

### F3 — c14 binding 引用的 candidate SHA 在仓库中不存在（已确认）

`evidence/cell-depth-20260918/c14/SOURCE_BINDING.json` 声明 `"candidate_sha": "43d62cf6682d4ee93469dace60eb5fe42f894fdb"`。

核验：

```
GET /repos/.../commits/43d62cf…      → HTTP 422  "No commit found for SHA"
GET /repos/.../git/commits/43d62cf…  → HTTP 404
GET /repos/.../git/trees/43d62cf…    → HTTP 404
git cat-file -t 43d62cf… (GO-WP1)    → fatal: remote error: upload-pack: not our ref
```

⇒ 该 SHA **既不是仓库里的提交，也不是树对象，远端不可达**。任何绑定在 `43d62cf…` 上的历史 PASS（含评论中提到的 709/0/0/0 回归）**在本仓库范围内无法被独立复算**，只能作为线索 —— 与包内「历史 PASS 只能作为线索」的要求一致，但需明确记录为**不可验证候选**。

### F4 — #229 的 C13 门禁硬编码了一个「跨版本」绑定三元组（已确认，本次最重要发现）

`control-plane/c13-independent-acceptance-v1/c13_gate.py` @ `2a6b5ddbd19a…` 固定 head：

```python
FIXED_CANDIDATE_SHA   = "0c3da07bc32009dee16c69125111f8e4ea9d546b"   # = #217 当前 head  ✔ 与现场一致
FIXED_APPLICATION_TREE= "9206696542000e020601f14233c339cfec6b364c"   # = #217 上一个 head 的 application/ tree  ✘
FIXED_C14_RECEIPT_ID  = "5740342803"                                 # = 一条 GitHub 评论 id，无签名/签发者/摘要
```

**判定**：`0c3da07b` 这一提交的 `application/` tree 是 `f6d32935…`，**不是** `92066965…`。以 `(0c3da07b, 92066965)` 为唯一放行组合的门禁，在仓库的任何合法状态下都**不对应同一个真实候选**。

⇒ 这正是包内「强制负向核验」第一条「伪造或替换 candidate SHA / application tree」所针对的形态。**此处不做主观归因**（可能是打包疏漏而非故意），但结论是客观的：**该门禁的固定绑定不可信，C14 不通过成立，且包内对该 FAIL 的表述（只说 runner 注册同源、receipt 无签名）低估了问题的性质。**

包内对 #229 的两条 FAIL 理由，逐条现场复核：

| 包内理由 | 现场核验 |
|---|---|
| Runner 注册、资格、独立性在同一 PR 可变源码中 | **成立**。`HOST_RUNNER_REGISTRY = {"isolated-c13-01": {...}}` 就是 `c13_gate.py` 里的字面量；`independence_attested_for` 是自声明字典，无任何 PR 外的主体。README 自称「host-owned qualification registry」与代码不符。 |
| receipt 无可验证签名 / 签发者 / 摘要绑定 | **成立**。`FIXED_C14_RECEIPT_ID` 是裸字符串 `"5740342803"`（= #217 上的一条评论 id），校验方式仅为**字面量相等**；全文件 0 处签名、0 处签发者、0 处摘要字段。 |
| （补充）篡改拒绝测试的强度 | **名不副实**。`test_refuses_non_hex_candidate_sha` 传 `"z"*40`，实际只是被三元组不等拒绝 —— 门禁**没有任何 hex 校验**；`test_refuses_unverified_numeric_receipt` 同理；`test_refuses_unqualified_runner_input` 期望的是 `TypeError`（Python 参数个数错误），**不是** `Refusal`，即未测试任何拒绝路径。 |

### F5 — 两条 PR 的 CI 现状为红，包内未披露

- **#216** head `ff0005dacc…`：check run `date-range` = **failure**（`mergeable_state = unstable`）
- **#228** head `5f83dc31…`：`isolated-request-visibility` = success、`isolated-candidate-admission` = success、**`isolated-contract` = failure**（`unstable`）
- 其余 #217/#218/#219/#221–#227/#229：该 head 上 **0 个 check run**（即无 CI 结果可引用；包内引用的 129 项测试是提交者在本地跑的，不构成 CI 记录）。

### F6 — 「独立香港审查身份」在当前条件下不可满足（阻断项）

要求：审查身份须与**实现者**、**此前审查者**、**未来 C13 Runner** 三者隔离。

现场事实：

- 本机 GitHub 令牌身份 = **`chenzhenxi1-sudo`**（`GET /user` 返回 id 296171158）。该账号正是：
  - #220 的作者（即 CCV1 收敛线的实现方）；
  - 与 #217 上两条 C13/C14 评论作者 `yuguangzhi3836-glitch` **不同**，但同属本工作站的既有身份谱系；
- 我运行在 `Eason-13490`，即实现所用的主执行工作站（`D:\Code\Workbuddy\GO-WP1` 等 9 个 worktree 同机）。

⇒ 从本工作站产出的任何「Signed Review Task / Signed Evidence」，其签发者都只能是**实现方身份**。若以「独立香港审查身份」名义出具，即构成包内明令禁止的「伪造…资格或独立性声明」。
**故：C13/C14 签名判定在本窗口不可出具。这是身份层的阻断，不是技术层的失败。**

同理，#229 中 `ENVIRONMENT = "GO-ISOLATED-ACCEPTANCE-01"`、runner `isolated-c13-01` 是否真实存在，属于**主机侧事实**，本次零 SSH，未核验 —— 标注为 **BLOCKED（未核验）**，不作任何推定。

---

## §4 逐 PR 判定（Step 5 总表）

判定口径：**只判定本次实际核验到的范围**。未执行的项一律 `BLOCKED`，不用「整体通过」掩盖。

| PR | 物料核验 | 分线复审 | 独立 C13/C14 | 本次 verdict | 依据 / 遗留 |
|---:|---|---|---|---|---|
| #216 | PASS（head/base/文件数属实） | **BLOCKED**（未做业务复审） | BLOCKED | **BLOCKED** | CI `date-range` 红；且是叠加链第 1 段，不能单独验收 |
| #217 | PASS（219 原件构成完全属实） | **BLOCKED**（未做 OTA/授权业务复审） | **BLOCKED**（无独立身份） | **BLOCKED** | 见 F2（round2 binding 漂移）+ F3（c14 candidate 不存在）；**保持 Draft 成立** |
| #218 | PASS（1 文件 docs-only 属实） | **BLOCKED** | BLOCKED | **BLOCKED** | 仅文档一致性未做逐条比对 |
| #219 | PASS | **BLOCKED** | BLOCKED | **BLOCKED** | 叠加链第 3 段 |
| #220 | PASS（9/9 CI success 属实，与本地记录一致） | BLOCKED | BLOCKED | **BLOCKED** | 我方自己的线；CI 绿灯≠产品/香港/C13 验收，与包内口径一致 |
| #221–#227 | PASS（各 head/base/文件数属实） | **BLOCKED** | BLOCKED | **BLOCKED** | 叠加链未做统一冻结回归；#227 是链尾 |
| #228 | PASS（6 文件属实） | **BLOCKED** | BLOCKED | **BLOCKED** | CI `isolated-contract` 红；「不读密钥/不发送真实邮件」未做行为级复核 |
| #229 | PASS | **FAIL**（门禁绑定自相矛盾，F4） | **FAIL**（同 F4 + receipt 无签名） | **FAIL** | **C13_RUNNER = NOT_RESTORED** |

### 总表强制项对照

| 包内要求 | 现场事实 | 是否已满足 |
|---|---|---|
| #229 在独立 C14 PASS 前 C13 Runner 始终 NOT_RESTORED | #229 门禁绑定不可信（F4）⇒ C14 不通过 | ✅ 一致，维持 NOT_RESTORED |
| #217 在独立 C13 PASS 前保持 Draft | #217 draft=true | ✅ 一致 |
| 所有其他 PR 继续 Draft | #216–#228 全部 draft=true（含 #230 本包） | ✅ 一致 |
| HK Staging / Final Release / Production 继续 HOLD | 本次零 SSH、零部署、未触任何运行环境 | ✅ 一致 |

---

## §5 必交付原件的现状

包内要求每条 PR 回传 8 类原件。本次窗口能给出的 / 不能给出的：

| 原件 | 状态 |
|---|---|
| 固定 candidate SHA | ✅ 已给（§1 表，14/14） |
| application tree / fingerprint | ⚠️ 部分：#217 已复算（`f6d32935…` / 1441 blobs），其余 13 个 PR 未逐条复算 |
| 完整文件清单及 SHA256 | ⚠️ 部分：文件清单已取（#217 全 219 条）；**逐文件 SHA256 未计算** |
| 测试命令与原始 JUnit / log | ❌ 未执行（需隔离环境） |
| 独立审查身份 | ❌ **不可提供**（F6） |
| Signed Review Task | ❌ **不可提供**（无独立身份 ⇒ 无签名资格） |
| PASS/FAIL/BLOCKED verdict | ✅ 已给（§4） |
| 遗留风险 + 唯一后续动作 | ✅ 已给（§4 / §6） |

---

## §6 唯一后续动作

按优先级，**一次只做一件**：

1. **【唯一推荐，且必须先做】** 由余总确认「独立香港审查身份」的落点：给出一个**不属 `chenzhenxi1-sudo`、不在 `Eason-13490` 上、不承载本机既有权杖**的审查身份与其执行环境。
   在此之前，#217 的 C13 与 #216–#228 的独立复审**全部保持 BLOCKED**，不作降级处理。
2. 身份落定后，第一个动作是修 #229 门禁的固定绑定（把 `FIXED_APPLICATION_TREE` 从 `92066965…` 改为该候选真实的 `f6d32935…`，或改为按已声明 `fingerprint_algorithm` 现场复算），并补齐 hex 校验与真正的 `Refusal` 路径测试 —— 然后才能谈 C14 重跑。
3. #217 的 round2 `SOURCE_BINDING.json` 需要就其自身 head 重新生成（F2），与 c14 binding 对齐到同一版本。

## §7 本次未做 / 未验证（明确清单）

- 未做：任何测试执行、任何 JUnit 复跑、任何隔离 PostgreSQL/SQLite 起停。
- 未做：#216/#217/#219 的 C 端与 OTA 授权业务复审；#218 文档逐条一致性比对；#221–#227 叠加链统一冻结回归；#228 邮件核验动作的行为级复核；#220 控制面边界复核。
- 未核：`GO-ISOLATED-ACCEPTANCE-01` 环境与 `isolated-c13-01` runner 是否真实存在（需主机侧只读核验）。
- 未核：其余 13 个 PR 的 application tree 复算与逐文件 SHA256。
- 未触：任何 PR 的评论 / 元数据 / 分支 / 合并状态；任何服务器；任何运行环境。
