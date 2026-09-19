# GO｜香港两日未审查成果总复审包

**审查包版本：2026-09-19｜状态：所有对象均为 Draft/未合并候选；本包不授权任何部署。**

## 总任务

对 2026-09-18 至 2026-09-19 形成、尚未由香港独立身份完成统一验收的 GO 成果做一次总复审。香港只读审查身份必须与实现者、此前审查者和未来 C13 Runner 隔离。

- 不合并、不安装、不部署、不改写任何运行环境。
- 禁止香港 Staging、Final Release、Production、真实 OTA、支付、供应商、密钥和网络出站。
- 仅限固定源码、隔离 PostgreSQL/SQLite、冻结测试和证据核验。
- 任何历史 PASS 只能作为线索；不得迁移为当前候选的 PASS。

## 本次收拢范围

本包包含全部仍打开的两日候选 PR #216–#229。源码、测试、日志、JUnit、SHA256 与证据以每个 PR 的固定 head 和 `Files changed` 为原件入口；不得按 main、PR 号或聊天记录推定源码身份。

| PR | 固定 head | 范围 | 香港需给出的结论 |
|---:|---|---|---|
| #216 | 以 PR head 为准 | C 端日期、机场输入、首页三级入口 | 产品/安全/三端回归结论 |
| #217 | `0c3da07bc32009dee16c69125111f8e4ea9d546b` | 账号持有人酒店/旅行库导入、OTA 账户授权边界、GO Trips | C14 复核后独立 C13 |
| #218 | 以 PR head 为准 | 携程学习成果与 C01–C14 增量任务 | 仅文档一致性与任务边界 |
| #219 | 以 PR head 为准 | 酒店选择导入、报价/价格方案身份、订单金额/退款校验 | 产品与回归结论 |
| #220 | `acdef3bead59b2f6635e9b55681de4f995ccf6b4` | Command Center V1 WP-1…WP-8 收敛线 | 控制面边界、身份与 CI 原件复核 |
| #221 | `181e7568b8ed640aba5c4b6a932f4d6c6e74c5b3` | 原图私有接收、房型映射、取消期限 | 叠加链起点复核 |
| #222 | `fc521219c53b692df91346669e704f4e6b475df1` | 多酒店库、房型映射、媒体审核 | 叠加链复核 |
| #223 | `f66129b718dfb9db2a156a46c69cd58674a2de0b` | Trips 时间、AI 计划、酒店 manifest | 叠加链复核 |
| #224 | `5200c0a2f440781749a0183842b60f0ed6b03920` | OTA 比价可比性、直传证据核验 | 叠加链复核 |
| #225 | `5a708b38de32a52f92384275ab1c30ccf79c53c1` | 酒店可信审核绑定、原图发布/撤销 | 叠加链复核 |
| #226 | `f7595f4904d4415459fd0a938adaa35e01353959` | 酒店审核 UI、事实绑定、身份验收 | 叠加链复核 |
| #227 | `af1c2d5744aef5212eb139f93b150ec7ae171b38` | 全国 C/B 注册、酒店库、协议文件 | 合规/注册门禁与三端验收 |
| #228 | `5f83dc31d56d7ff0e4755a8eac01ac086e084121` | 受限香港注册邮件配置核验动作 | 控制面最小权限复核 |
| #229 | `2a6b5ddbd19a58becf09063c9bc253d9613b929f` | C13 独立验收 Runner 控制面 | 独立 C14；未通过前 Runner 不恢复 |

## 已收录原件

### PR #217

该 PR 固定 head 下共有 219 个变更原件：35 个应用源码、33 个测试、151 个 Evidence（命令、日志、JUnit XML、SOURCE_BINDING、SHA256、C13/C14 原件）。

- 原件树：`https://github.com/yuguangzhi3836-glitch/GO/tree/0c3da07bc32009dee16c69125111f8e4ea9d546b`
- 全量 diff：`https://github.com/yuguangzhi3836-glitch/GO/pull/217/files`
- 当前候选 C14 重绑评论：`https://github.com/yuguangzhi3836-glitch/GO/pull/217#issuecomment-5740342803`
- 历史 C13 身份不匹配评论：`https://github.com/yuguangzhi3836-glitch/GO/pull/217#issuecomment-5740332206`

既有材料显示 129 项候选定向测试通过，但这不是独立 C13 verdict；香港必须重新验证其与固定 candidate/tree 的绑定。

### PR #220–#227 酒店/注册叠加线

#221 → #222 → #223 → #224 → #225 → #226 → #227 是连续叠加链。任何单 PR 的测试 PASS 只能覆盖该 PR 固定 head，香港需先核验 base/head 连续性和无遗漏的 migration/manifest/evidence 关系，再在 #227 固定 head 做统一冻结回归。

其中 #220 是独立的 Command Center V1 收敛线，不得与应用叠加链混为一个候选；其 CI 绿灯不能替代任何产品、香港或 C13/C14 验收。

### PR #228–#229 控制面线

- #228 只允许固定的邮件配置核验动作，不读取或回传密钥、验证码、邮件正文或供应商响应；其本身不能发送真实业务邮件或部署。
- #229 当前结论为 **C14 FAIL**：Runner 注册、资格和独立性仍在同一 PR 的可变源码中；receipt 也无可验证签名/签发者/摘要绑定。因此 `C13_RUNNER = NOT_RESTORED`。

## 香港审查顺序

1. **物料核验**：逐个 PR 固定 head，下载/读取完整 files diff、全部 Evidence、PR 评论与工作流原件；输出每个 PR 的 candidate SHA、application tree、文件清单哈希与缺失项。
2. **分线复审**：
   - #216/#217/#219：C 端、OTA 帐号授权与 GO Trips 业务边界；
   - #220/#228/#229：控制面、身份隔离、签名与拒绝规则；
   - #221–#227：酒店库、媒体权利、酒店审核、注册协议与 C/B 三端链路。
3. **C14 先行**：对 #229 完成独立 C14。必须验证 PR 外不可变 Runner 登记、可验证 C14 receipt 及全部篡改拒绝测试；失败即停止 C13。
4. **C13 后置**：只有 #229 C14 PASS，且 #217 的 candidate/tree/receipt 完全一致时，才能用隔离 Runner 对 #217 做 C13 签名验收。
5. **总报告**：按 PR 输出 PASS / FAIL / BLOCKED，不得用整体“通过”掩盖单项缺失。

## 强制负向核验

- 伪造或替换 candidate SHA、application tree、receipt、Runner ID、资格或独立性声明；
- 向 #228/#229 添加 command、URL、路径、Provider、收件人、验证码、部署或网络参数；
- 跨酒店/跨账号/跨会话访问，过期 state、重放回调、篡改媒体 rights/原图/房型映射；
- 迁移、协议版本/哈希不一致、草案协议下的新注册、OTA 密码/OTP/cookie/token 进入 GO；
- 将旧候选 Evidence 迁移为当前候选 PASS。

## 必交付原件

每条 PR 需回传：Signed Review Task、固定 candidate SHA、application tree/fingerprint、完整文件清单及 SHA256、测试命令与原始 JUnit/log、独立审查身份、PASS/FAIL/BLOCKED verdict、遗留风险和唯一后续动作。

总表必须明确：

- #229 在独立 C14 PASS 前，C13 Runner 始终 `NOT_RESTORED`；
- #217 在独立 C13 PASS 前，保持 Draft；
- 所有其他 PR 继续 Draft；
- 香港 Staging、Final Release、Production 继续 HOLD。

## 原件入口

- PR 全集：`https://github.com/yuguangzhi3836-glitch/GO/pulls?q=is%3Apr+is%3Aopen+author%3Ayuguangzhi3836-glitch`
- #216–#229 的每一份完整原件均以各自 `https://github.com/yuguangzhi3836-glitch/GO/pull/<PR号>/files` 为唯一读取入口。
