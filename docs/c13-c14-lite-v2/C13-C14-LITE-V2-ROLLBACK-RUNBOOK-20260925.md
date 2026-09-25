# C13/C14 Lite V2 — Rollback / Retire Runbook

> **本文件不含任何 secret**：没有 PAT 值、没有私钥、没有公开密钥内容。凡是涉及凭据
> 的地方，只写**路径、托管、撤销动作**。
>
> 本 Runbook 只被**生成和验证**，本轮**没有执行**任何 rollback。

- Date: 2026-09-25
- 适用对象: C13/C14 Lite V2（C14 规则审查 + C13 质量验收 + 双见证 + 聚合）
- Rollback baseline（main，注册前）: `aa2ec62b68b49679c6d54217c7cb75f63a9c3ef0`
- 注册 PR: **#252**，单 commit `85533dd5790b8cfbbf48e3ae387cb47aab82a8d3`（+528 / -0，仅 2 文件）
- 🆕 **注册合并（真人合并，2026-09-25 21:22:26 +0800 / 13:22:27Z）**:
  `REGISTRATION_MERGE_SHA = 7db7b2aa52ecabc1ff1c92d9d1673f44f5ce68c5`
  （merge commit：`parent1 = aa2ec62b…`（旧 main）、`parent2 = 85533dd57…`（#252 head）；
  root tree `85ab281cfc10375081fe36c96482cf108c56280b`；GitHub 已 gpgsig 签名；
  `merged_by = chenzhenxi1-sudo`）
  ⇒ **注册后 main = `7db7b2aa5…`**，撤销时"回到注册前"要回到的是 `aa2ec62b…`。
- Backend 固定引用: `a67ea8ac0cbf7990ce7fa1570eef7a0de29bab40`（写死在两条 workflow 内；
  远端可达性实测 HTTP 200，且是 #251 当前 head `3085ba157` 的祖先）

---

## 0. 一句话结论

C13/C14 Lite V2 是**可插拔验收层**：撤销 = **一次 Git revert + 每台删 3 个文件 + 撤销 1 个
GitHub 凭据 + 在 Ledger 上追加一条 RETIRED 记录**。全程**不需要**删除任何历史 Issue、Actions
run、artifact 或 Evidence，**不需要**改写 `main` 历史，**不需要**动 C01–C12 / CC / HK 的
原有运行链。

---

## 1. 撤销前的现状清单（baseline，2026-09-25 实测）

撤销就是把这个清单里的东西**逐项归零**。四类状态必须分开看：

### 1.1 Git 仓库状态（main）

```text
main（注册前 baseline）                = aa2ec62b68b49679c6d54217c7cb75f63a9c3ef0
main（当前，注册已合并）               = 7db7b2aa52ecabc1ff1c92d9d1673f44f5ce68c5
main 上 workflow 总数                  = 26（注册前）→ 28（注册后，实测 28）
main 上 c13/c14 workflow              = 0（注册前）；注册后 = 2（PR #252）
main 上 control-plane/c13-c14-lite   = 不存在（backend 从未合并进 main）
main 上 control-plane/c13-c14-witness= 不存在
```

已注册的两条 production workflow（实测，2026-09-25 21:2x +0800）：

```text
id 366980580  C14 rule and compliance review (Lite V2)  .github/workflows/c14-rule-compliance.yml  state=active
id 366980579  C13 quality acceptance (Lite V2)          .github/workflows/c13-quality-acceptance.yml  state=active
注册内容与 PR head 逐字节一致: c14 blob a9400e2fde4be173ce6d910f88d8ceb6dbdc42f4
                              c13 blob 5d5ccdafe73d19ddec5ec2a34ca4803f21cd8dee
                              （两者在 main 与 #252 head 上相同）
```

backend 与 witness runtime 只活在**未合并**的分支上：

```text
#248  cc/c13-c14-lite-v2-github-backend-20260925
#249  cc/ccv1-144-cc-hk-witness-20260925
#250  cc/ccv1-144a-github-witness-credential-20260925
#251  cc/ccv1-145-full-chain-simulation-20260925         ← backend 固定引用指向这个 head
#252  cc/c13-c14-production-workflow-registration-20260925（registration）
```

### 1.2 GitHub Actions 状态

```text
已注册的 production workflow（注册后）: c14-rule-compliance.yml, c13-quality-acceptance.yml
🆕 第一次真实 C13/C14 production run（2026-09-25 13:30:51Z）:
  C14 run id 36141430817 · conclusion=success · head_sha 7db7b2aa5…
  C14 verdict = PASS_SCOPED · C14_ROOT = 411382da06dd4f4d5a0a9b470f61c758bf51d7b3aada5fb3711ae6ddd96e9cef
  artifact 10866698116（bundle/contract/opinion，2884 B，digest sha256:b09e75cf…）
  artifact 10866808048（readback，678 B，digest sha256:508f9e6a…）
  ⚠ 两个 artifact 均由 **GitHub retention 90 天**约束 ⇒ 作为长期审计证据须在到期前归档
    （不可变副本 + SHA256 + artifact_id / run_id / 归档时间）。撤销**不会**保住它们。
C13 production run                     : 0（本轮按指令只派发 C14）
历史 POC run                          : 若干次（POC_ONLY），是历史事实，**不主动删除**
                                        ⚠ 其 artifact 同样受 GitHub retention 期限约束；若要作为
                                          长期审计证据，须在到期前归档（见 §2.I）
```

### 1.3 Host secret 状态（两台，各 3 个文件）

```text
CC（iZj6c7k6k01biwlbnwutu5Z）:
  /etc/go-command-center/keys/github-witness-reader.token    0600 root:root            93 B
  /etc/go-command-center/keys/c13-c14-witness-ed25519.pem    0600 root:root           119 B
  /etc/go-command-center/keys/c13-c14-witness-ed25519.pub    0644 root:root            81 B
  C13/C14 相关 unit / service                               无
  C13/C14 runtime 常驻安装                                   无（runtime 只在 /tmp，已清理）

HK（iZj6ccs8t04f1p4d8pe69zZ）:
  /etc/go-hk-agent/keys/github-witness-reader.token          0600 go-hk-agent:go-hk-agent  93 B
  /etc/go-hk-agent/keys/c13-c14-witness-ed25519.pem          0600 go-hk-agent:go-hk-agent 119 B
  /etc/go-hk-agent/keys/c13-c14-witness-ed25519.pub          0640 root:go-hk-agent         81 B
  C13/C14 相关 unit / service                               无
  C13/C14 runtime 常驻安装                                   无

两台都**未**触碰的既有凭据（撤销时**绝对不能**动）:
  CC: task-manifest-signing.pem/.pub, task-manifest-signing-public.pem,
      github-requests-reader.token, github-evidence-reader*, github-go-pr-resolver*,
      github-tasks-writer*
  HK: evidence-signing.pem/.pub, evidence-write, tasks-read, task-verify.pub,
      github-go-source-reader*
```

### 1.4 Issue / Ledger 状态

```text
CURRENT_CANONICAL_LEDGER = Issue #68（V7.0 14-CELL EXECUTION LEDGER, open）
C13 行: independent acceptance · TRIGGER_ARMED · "Activate only on a new frozen candidate"
C14 行: source/authority gate · TRIGGER_ARMED · "Activate only on a new frozen candidate, before C13"
Dispatch 记录 = Issue #92（14-CELL R2 Dispatch）

🆕 本轮 activation 记录（2026-09-25 13:30:16Z，append-only，评论 id 5833230504）:
  round id            = V70-R3
  C14 task id         = V70-R3-C14-01
  C13 task id         = V70-R3-C13-01
  scheduler request   = V70-R3-C13C14-01
  candidate           = 7db7b2aa52ecabc1ff1c92d9d1673f44f5ce68c5
  application tree    = dd815baf0105cce603e9a28b002cfb9d8b95d186
  ⇒ #68 body 与全部历史评论**未改动**；评论数 38 → 39。
  ⚠ 该评论作者 = `chenzhenxi1-sudo`（实现/调度身份），不是 Owner。
     #68 此前 38/38 条评论均为 Owner 撰写；这是第一条非 Owner 评论，
     撤销/善后时按"可被 Owner 删除或由后一条记录取代"处理（见 §A / §I）。
```

**撤销时这条 activation 记录怎么处理**：不在 rollback 中删除（append-only 原则，见 §I）。
它只是"闸门被激活过"的历史事实；若 Owner 要收回该激活，正确做法是**再追加一条**
`C13_C14_MODE = DISABLED | RETIRED`（§A 的格式），而不是编辑或删除本条。

---

## 2. 撤销动作（A–J）

> 顺序建议：**先停派发 → 再退注册 → 再删代码 → 最后销毁凭据**。
> 先删凭据会让"Scheduler 还在派发但没人能验"这种中间态变得难以解释。

### A. Scheduler 停止派发 C13/C14

**不需要改任何代码。** C13/C14 的"是否派发"由现有 14-Cell Ledger 的 Cell 状态表达：

```text
C13/C14 状态:  TRIGGER_ARMED  →  DISABLED 或 RETIRED
```

动作：在 Ledger Issue（当前是 #68）上**追加一条评论**（append-only），写明：

```text
C13_C14_MODE = DISABLED | RETIRED
effective_at = <ISO8601>
authority    = <人>
reason       = <原因>
last_valid_round = <最后一个有效 round 的 id>
```

⛔ **不得**修改 #68 的 body、不得改历史评论、不得删除旧 PASS。
⛔ 不得为此新建 registry / scheduler / authority service —— 现有 Ledger 状态字段足够。

**验收**：Scheduler 不再向 C13/C14 派发新 task；C01–C12 的派发不受影响。

### B. workflow registration 独立 revert

**这是最干净的一步，也是设计成这样的原因。**

```bash
# 在 main 上
git revert --no-edit 85533dd5790b8cfbbf48e3ae387cb47aab82a8d3
git push origin main          # 走正常 PR 流程亦可
```

已用 `git apply --check --reverse` 验证：该 patch 反向应用**完整移除两个文件、528 行全删、
不留残件**。

**验收**：`git ls-tree origin/main .github/workflows/ --name-only | grep -c 'c1[34]'` = **0**；
main 上 workflow 总数回到 **26**。

### C. backend 移除

backend（`control-plane/c13-c14-lite/`）**从未进入 main**，所以"移除"= **不合并 + revert 注册**：

```text
1. 执行 B（revert 注册）⇒ workflow 消失 ⇒ 对 backend 的唯一引用消失
2. #248 / #249 / #250 / #251 若仍未合并：直接关闭（close），不要 merge
3. 若已合并进 main：对相应 merge 做 revert（同样是普通 revert PR）
```

⛔ **不要**为了"清理"而 force-push 或改写 main 历史。
⛔ 分支关闭后，`a67ea8ac0…` 这个 commit 对象仍在仓库中（历史事实），**这没有问题**。

**验收**：`git ls-tree -r origin/main --name-only | grep -c 'c13-c14-lite'` = **0**。

### D. 两台的 runtime 移除

当前**没有**常驻 runtime（只在 `/tmp`，且已清理）。若未来有：

```bash
# 每台
rm -rf /tmp/ccv1-14*  /tmp/ccv1-145*        # 临时 runtime
# 如果曾经安装到常驻路径（当前没有）：
#   rm -rf <安装目录>；并删除对应 unit：systemctl disable --now <unit>；rm /etc/systemd/system/<unit>
```

⛔ 删 unit 前先确认它**只**属于 C13/C14。本轮实测：**两台都没有**任何 c13/c14/witness unit。

**验收**：`ls /etc/systemd/system/ | grep -Ei 'c13|c14|witness'` 为空。

### E. CC credential 撤销 / 移除

```text
凭据: /etc/go-command-center/keys/github-witness-reader.token
用途: 只读 GitHub Actions witness readback
```

1. **GitHub 侧先撤销**（这是真正切断能力的动作）：
   Settings → Developer settings → Fine-grained tokens → 找到对应的那枚
   （不可逆指纹前 8 位 `bcead04b`，可据此辨认；**不要**输出或粘贴 token 值）→ Revoke。
   ⚠ 撤销前确认它**只**用于 witness readback，不承载别的用途。
2. **主机侧删除文件**：

```bash
rm -f /etc/go-command-center/keys/github-witness-reader.token
```

3. 可选：删除保留的安装/轮换脚本 `/root/go-witness-credential-install.sh`。

⛔ **不要**动 `github-requests-reader.token`（属于另一条线）。

**验收**：`GET /user` 用该 token 返回 401；文件不存在。

### F. HK credential 撤销 / 移除

同 E，但：

```text
凭据: /etc/go-hk-agent/keys/github-witness-reader.token
指纹前 8 位（不可逆）: 7f11873b
主机侧: rm -f /etc/go-hk-agent/keys/github-witness-reader.token
```

**HK 独立撤销**，不影响 CC。

### G. CC witness key 销毁

```text
私钥: /etc/go-command-center/keys/c13-c14-witness-ed25519.pem
公钥: /etc/go-command-center/keys/c13-c14-witness-ed25519.pub
key_id: 26ca5651b363c463
purpose: c13c14-acceptance-witness
```

```bash
shred -u /etc/go-command-center/keys/c13-c14-witness-ed25519.pem 2>/dev/null \
  || rm -f /etc/go-command-center/keys/c13-c14-witness-ed25519.pem
rm -f /etc/go-command-center/keys/c13-c14-witness-ed25519.pub
```

⛔ 这**不是** `task-manifest-signing.pem`（那是 Task 签名密钥，**绝对不要动**）。

**销毁私钥意味着什么、不意味着什么**——这里必须说准：

- 销毁私钥**只**意味着一件事：**不能再产生新的、属于该 key 的签名**。
- 它**不**意味着历史 witness 失去可验证性。每条 witness **内嵌自己的 `public_key_pem`**，
  而验证只需要公钥 ⇒ **历史记录仍可用归档的公钥复核**（`lw_witness.verify_witness`
  就是纯公钥验证，不碰私钥）。

但"记录能自证"**不等于**"记录长期可信"，两者之间还差一层，必须补上：

- 一条内嵌公钥的 witness 只能证明「**这条记录是由持有对应私钥的人签的**」，
  **不能**证明「**那条记录当时确实是 CC / HK 签的**」。任何人拿自己的公钥 + 自己重签的记录，
  都能造出一条"自证通过"的假记录。
- ⇒ **长期真实性依赖一份独立受信的 key binding evidence**：启用 / 轮换当时就要把
  **`key_id` + `fingerprint` + `public_key_pem`** 与 **role（CC / HK）+ purpose + 生效时间**
  绑定并留痕（记进 Ledger，或落入一份随卷归档的登记记录）。这份登记必须**早于、且独立于**
  被验证的 witness，否则它挡不住上面那种自签伪造。
- 有了它才能回答："这条 2026-09-25 的 CC witness，确实出自当时那个
  `key_id = 26ca5651b363c463`、fingerprint `sha256:26ca5651…`"，而不只是"它出自某个
  持有私钥的人"。

⇒ **正确顺序：① 归档 witness 记录本身 → ② 归档 / 确认 key binding evidence
（key_id + fingerprint + public_key_pem + role/purpose + 生效时间）→ ③ 再销毁私钥。**
销毁之后：**既有签名仍可验证，新签名不再产生。**

### H. HK witness key 销毁

同 G，但：

```text
私钥: /etc/go-hk-agent/keys/c13-c14-witness-ed25519.pem      key_id 36458250ffc1b404
公钥: /etc/go-hk-agent/keys/c13-c14-witness-ed25519.pub
```

⛔ **不要**动 `evidence-signing.pem`（HK 部署证据签名密钥，属于另一条线）。

### I. Issue / Ledger 历史保留

```text
Rollback **不主动删除**历史 Issue / 评论 / Actions run / artifact / Evidence。
但"不主动删除"**不等于**"永久留存"，按类型分开处理：

- Issue / 评论 / Ledger 记录：在 GitHub 上长期存在，**不需要动作**。
- Actions run 元数据：**不主动删除**。
- 🔴 **GitHub Actions artifact 有 retention 期限，到期会被 GitHub 自动清理。**
  ⇒ 若某次 artifact 被当作**长期审计证据**，必须**在 retention 到期前归档**：
  至少归档**不可变证据副本 + SHA256**（例如把 artifact ZIP 与它对应的
  `artifact.digest` 一并落到受控归档，并同时记录 `artifact_id` / `run_id` / 归档时间）。
  ⚠ 未归档的 artifact 会**静默到期消失**；"rollback 不删它"并**不能**保住它。
- 仓内 Evidence 文件：随 Git 历史长期存在，**不需要动作**。
追加: 只追加 RETIRED/DISABLED 记录（见 A）
```

⛔ 禁止：删除 Issue、删除评论、改写 body、删除历史 Actions run、删除 artifact 作为"证据消失"、
把执行过的 C13/C14 说成"从未存在"。

**正确历史形态**：

```text
过去:      C13/C14 曾启用并真实运行（含所有 round 记录）
某时间点:  C13_C14_MODE = RETIRED，authority=…，effective_at=…
之后:      Scheduler 不再派发；workflow / runtime / key / credential 已撤除
```

### J. 恢复接入前的 gate semantics

C13/C14 Lite V2 **没有替换**任何既有 gate，只是在既有链路上**增加**一层验收。
撤销后自动回到：

```text
GAP → TASK → TEST → source-bound EVIDENCE → (C14) → (C13) → DONE-SCOPED → NEXT-DEPTH
                                             ↑ 去掉这两步即回到 pre-C13/C14 形态
```

因为：

- C01–C12 的派发与状态表达完全不引用 C13/C14（实测：main 上 26 个 workflow **无一**引用）；
- CC / HK 没有任何 unit 引用 C13/C14（实测：两台 systemd 目录 **零命中**）；
- 部署链路（Command Center / HK executor / bridge）与 C13/C14 无代码耦合。

⇒ **恢复动作 = 什么都不用改**，因为从未建立依赖。

---

## 3. 回滚后验证清单

逐项应为真：

```text
[ ] git ls-tree origin/main .github/workflows/ 中 c13/c14 计数 = 0，workflow 总数 = 26
    （撤销基线：main 从 7db7b2aa5… 退回 aa2ec62b…，即 revert 85533dd57…）
[ ] git ls-tree -r origin/main | grep c13-c14-lite 计数 = 0
[ ] GitHub Actions workflow 列表中 c14-rule-compliance.yml / c13-quality-acceptance.yml
    不再以 active 出现在默认分支（撤销前 id 366980580 / 366980579）
[ ] CC: 3 个 C13/C14 文件均不存在；既有密钥（task-manifest-signing 等）**原样还在**
[ ] HK: 3 个 C13/C14 文件均不存在；既有密钥（evidence-signing 等）**原样还在**
[ ] CC: systemctl is-active go-boss-request-bridge.timer / go-ai-command-center = 正常
[ ] HK: go-hk-agent.timer enabled 且仍在按周期跑（NRestarts=0）
[ ] 两台 /etc/systemd/system/ 中 c13|c14|witness 命中 = 0
[ ] GitHub 侧两枚 witness PAT 已 revoke（用旧值调用 /user 得 401）
[ ] Ledger 上已追加 RETIRED 记录，且历史评论数量只增不减
[ ] C01–C12 的下一次派发正常（不因撤销而报错）
[ ] 历史 C13/C14 run / witness 记录仍可查询
[ ] 作为长期审计证据的 artifact 已在 retention 到期前归档（不可变副本 + SHA256）
[ ] key binding evidence（key_id / fingerprint / public_key_pem + role/purpose + 生效时间）已归档
```

---

## 4. 明确**不需要**做的事

```text
不需要删除历史 Issue             不需要删除 Actions run
不需要删除 artifact 作为"证据清除" 不需要改写 main 历史 / force-push
不需要改写旧 Evidence            不需要重装 CC / HK 的 executor
不需要重写 C01–C12               不需要恢复任何备份
不需要重启任何服务（无 unit 依赖）
```

**可回退 ≠ 可改写历史。**

---

## 5. 本轮对"可撤销性"的实测证据

```text
main 上引用 c13/c14 的文件（除注册的 2 个）: 仅 1 个历史证据清单
  evidence/v70-cell-closure-20260913/SHA256.json   ← 历史事实，保留，不影响运行
main 上 26 个 workflow 引用 c13/c14: 0（注册前实测；注册后新增的 2 条自身不构成依赖）
CC systemd 引用 c13/c14/witness: 0        HK systemd 引用 c13/c14/witness: 0
CC/HK C13/C14 unit: 无                    CC/HK C13/C14 常驻 runtime: 无
注册 patch 反向应用检查: OK（完整移除，528 行，无残件）
profile check（注册后补测）: 两条已注册 workflow 通过 backend 自带离线结构检查
  （lite_workflow_check.py 的 7 项：权限最小化 / 无部署权威 / 凭据边界 / 可派发身份 /
    artifact 纪律 / 同步骤 env 陷阱 / readback 声明 run head）⇒ gate=PASS
```

**注册合并后重新测得的"可撤销性"（2026-09-25，只读）**：

```text
撤销 = revert 一个 merge 的**单个提交** 85533dd57…  ⇒ main 回到 aa2ec62b…，workflow 28→26
注册只加 2 个文件（+528/-0），main 上仍**没有** backend/witness 路径
backend 的固定引用 a67ea8ac0… 活在**未合并**的 #251 分支上 ⇒ 撤销注册后引用自然消失
未见新增硬依赖：C01–C12 / CC / HK / 部署链均未因注册而引用 C13/C14
```

⇒ `C01_C12_HARD_DEPENDENCY_CREATED = NO`｜`CC_HARD_DEPENDENCY_CREATED = NO`｜
`HK_HARD_DEPENDENCY_CREATED = NO`｜`ROLLBACK_READY = YES`
