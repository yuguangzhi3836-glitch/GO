# C13/C14 Lite V2 — Rollback / Retire Runbook

> **本文件不含任何 secret**：没有 PAT 值、没有私钥、没有公开密钥内容。凡是涉及凭据
> 的地方，只写**路径、托管、撤销动作**。
>
> 本 Runbook 只被**生成和验证**，本轮**没有执行**任何 rollback。

- Date: 2026-09-25
- 适用对象: C13/C14 Lite V2（C14 规则审查 + C13 质量验收 + 双见证 + 聚合）
- Rollback baseline（main，注册前）: `aa2ec62b68b49679c6d54217c7cb75f63a9c3ef0`
- 注册 PR: **#252**，单 commit `85533dd5790b8cfbbf48e3ae387cb47aab82a8d3`（+528 / -0，仅 2 文件）
- Backend 固定引用: `a67ea8ac0cbf7990ce7fa1570eef7a0de29bab40`（写死在两条 workflow 内）

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
main                                  = aa2ec62b68b49679c6d54217c7cb75f63a9c3ef0（注册前）
main 上 workflow 总数                  = 26
main 上 c13/c14 workflow              = 0（注册前）；注册后 = 2（PR #252）
main 上 control-plane/c13-c14-lite   = 不存在（backend 从未合并进 main）
main 上 control-plane/c13-c14-witness= 不存在
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
已跑过的 C13/C14 production run       : 0（本轮未 dispatch，因为 merge gate 未过）
历史 POC run                          : 362 之前若干（POC_ONLY），是历史事实，**保留**
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
```

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
⛔ 销毁后，历史上由它签的 witness **签名无法再被验证为"来自该 key"** —— 所以在销毁前，
应先把已签 witness 连同 `public_key_pem`（witness 记录内自带）一并归档。那些记录**自带公钥**，
所以即使私钥销毁，**历史记录的真实性仍可复核**（这正是 witness 记录内嵌公钥的原因）。

### H. HK witness key 销毁

同 G，但：

```text
私钥: /etc/go-hk-agent/keys/c13-c14-witness-ed25519.pem      key_id 36458250ffc1b404
公钥: /etc/go-hk-agent/keys/c13-c14-witness-ed25519.pub
```

⛔ **不要**动 `evidence-signing.pem`（HK 部署证据签名密钥，属于另一条线）。

### I. Issue / Ledger 历史保留

```text
保留: #68 / #77 / #92 及全部历史评论、Actions run、artifact、Evidence 文件
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
[ ] git ls-tree -r origin/main | grep c13-c14-lite 计数 = 0
[ ] CC: 3 个 C13/C14 文件均不存在；既有密钥（task-manifest-signing 等）**原样还在**
[ ] HK: 3 个 C13/C14 文件均不存在；既有密钥（evidence-signing 等）**原样还在**
[ ] CC: systemctl is-active go-boss-request-bridge.timer / go-ai-command-center = 正常
[ ] HK: go-hk-agent.timer enabled 且仍在按周期跑（NRestarts=0）
[ ] 两台 /etc/systemd/system/ 中 c13|c14|witness 命中 = 0
[ ] GitHub 侧两枚 witness PAT 已 revoke（用旧值调用 /user 得 401）
[ ] Ledger 上已追加 RETIRED 记录，且历史评论数量只增不减
[ ] C01–C12 的下一次派发正常（不因撤销而报错）
[ ] 历史 C13/C14 run / artifact / witness 记录仍可查询
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
main 上 26 个 workflow 引用 c13/c14: 0
CC systemd 引用 c13/c14/witness: 0        HK systemd 引用 c13/c14/witness: 0
CC/HK C13/C14 unit: 无                    CC/HK C13/C14 常驻 runtime: 无
注册 patch 反向应用检查: OK（完整移除，528 行，无残件）
```

⇒ `C01_C12_HARD_DEPENDENCY_CREATED = NO`｜`CC_HARD_DEPENDENCY_CREATED = NO`｜
`HK_HARD_DEPENDENCY_CREATED = NO`｜`ROLLBACK_READY = YES`
