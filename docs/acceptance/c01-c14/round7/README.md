# C01–C14 第七轮修复与独立复验

本轮按照“授权与门禁 → 执行恢复与资金差额 → C13独立完整旅程复验”完成修复。**同一候选五组CI全部通过。** 结论仅覆盖本轮明确范围，不把测试通过等同305项义务全部验收。

- 原Draft：[PR #246](https://github.com/yuguangzhi3836-glitch/GO/pull/246)，保持未合并、未部署。
- 实测Gate：`b2d9f9744dd7d994636caa805e4dc954e278aab9`；产品：`afc142e16c050c0000da5a11a312620387be8f79`。
- Application tree：`ac23b75a75325091c5a95434238473a5592468a7`；1542文件，SHA256 `67dca501719f5985ebfcc668c635d051242df99063b8e40440fb39da55f85785`。
- 最终证据独立归档，保留实测Draft head，应用与测试配置不因归档改变。[精确来源与38项变更](SOURCE_BINDING.json)。

## 实质修复

1. **授权与门禁**：内部Hosted入口校验持久身份、当前会话/角色、具体权限及DB解析的酒店范围；跨酒店和自授权拒绝。媒体提交主体由服务端绑定，内容/媒体maker不能自审。发布、展示、库存和下单使用同一版本化审批；来源撤销、媒体缺失、内容或房价变化均阻断。
2. **执行恢复**：批准与执行分离。业务效果、库存、通知、Trips和执行成功标记同事务提交；失败留下可恢复状态，重放不重复执行。未收费且无支付授权、未入住的确认申请可以取消，UNKNOWN和已有资金仍走原资金保护路径。
3. **资金差额**：最新裁决相对实际净扣款计算；100→50尚未退款后维持50仍能退款50，已退款后不重复退；上调超过实际净扣款拒绝。
4. **真实PG问题**：修复5个业务状态字段宽度不足，完整保留原状态字符串；0139兼容旧历史链及已由当前metadata创建的表，保留数据、索引和唯一约束。降级对全部可能丢失先预检，长状态或审核来源数据存在时拒绝。

C13预审发现的3项P1——未付款确认申请退出死路、11个财务入口范围遗漏、媒体自审——均已修复并独立复验。原FAIL材料保留。未完成结构化加床计价，因此正数加床请求被明确拒绝，未把其当成免费库存。

## 同候选验证

| 范围 | 结果与边界 |
|---|---|
| 全量Python四分片 | 3233执行项：3226通过、0失败、0错误、7环境跳过；含原有subtest计数 |
| 专项回归 | 455通过、0失败/错误/跳过 |
| PG业务增量 | 324通过、0失败/错误/跳过；首轮7个失败节点逐项转PASS |
| PG历史状态迁移 | 7通过；实际PG独立schema，不用SQLite代替 |
| PG支付/outbox | 支付47、outbox1通过；另恢复12场景通过 |
| 浏览器/前端 | Chromium合成业务39项、前端368项通过；loopback HTTP170断言通过 |
| C13独立本地执行 | 新SHA37通过：18 HTTP旅程+15迁移+3库存+1独立约束保留；不累计旧轮79/29 |
| 受限事务检查 | PG18.4合成RIDE事务52次、并发1/4/8，零失败、资金/状态不变量通过；不是生产SLA或千人/万人压测 |

首轮全量回归10个失败节点已在新JUnit逐项确认PASS。7个Python环境跳过节点保留原状态，独立PG对应结果详见C13映射。套件之间有重叠，不相加为业务完成率。

| Workflow | 结果 | 原始证据 |
|---|---|---|
| Canonical mobile retention | PASS | [原始作业](https://github.com/yuguangzhi3836-glitch/GO/actions/runs/36218642890) |
| Canonical parent retention | PASS | [原始作业](https://github.com/yuguangzhi3836-glitch/GO/actions/runs/36218642925) |
| DEPTH48 ordered repair acceptance | PASS | [原始作业](https://github.com/yuguangzhi3836-glitch/GO/actions/runs/36218642881) |
| V7 Cell scoped gap closure | PASS | [原始作业](https://github.com/yuguangzhi3836-glitch/GO/actions/runs/36218642891) |
| V7 next depth PostgreSQL recovery | PASS | [原始作业](https://github.com/yuguangzhi3836-glitch/GO/actions/runs/36218642882) |

## C01–C14 当前状态

这是本轮可观察工作与证据，不是14个执行线程的在线心跳。未新增功能的Cell保留实现，并已纳入本轮专项回归。

| Cell | 状态 | 工作/限制 |
|---|---|---|
| C01 | ROUND7_REPAIR_SCOPED_PASS | 酒店范围授权、媒体提交主体、版本化发布门禁、未付款确认申请取消 |
| C02 | SCOPED_REGRESSION_PASS_NO_NEW_FUNCTION_THIS_ROUND | 本轮专项回归通过，未新增功能；不等同该模块全部业务验收 |
| C03 | SCOPED_REGRESSION_PASS_NO_NEW_FUNCTION_THIS_ROUND | 本轮专项回归通过，未新增功能；不等同该模块全部业务验收 |
| C04 | ROUND7_REPAIR_SCOPED_PASS | 最新裁决相对历史原扣款的差额资格 |
| C05 | SCOPED_REGRESSION_PASS_NO_NEW_FUNCTION_THIS_ROUND | 本轮专项回归通过，未新增功能；不等同该模块全部业务验收 |
| C06 | SCOPED_REGRESSION_PASS_NO_NEW_FUNCTION_THIS_ROUND | 本轮专项回归通过，未新增功能；不等同该模块全部业务验收 |
| C07 | ROUND7_REPAIR_SCOPED_PASS | 具体权限、有效身份会话和酒店范围 |
| C08 | SCOPED_REGRESSION_PASS_NO_NEW_FUNCTION_THIS_ROUND | 本轮专项回归通过，未新增功能；不等同该模块全部业务验收 |
| C09 | ROUND7_REPAIR_SCOPED_PASS | 审批授权/执行状态分离，失败恢复与重放 |
| C10 | ROUND7_REPAIR_SCOPED_PASS | Trips未付款确认申请可取消；终态关闭 |
| C11 | ROUND7_REPAIR_SCOPED_PASS | 只按当前净扣款和最新裁决补差额，UNKNOWN不放行 |
| C12 | ISOLATED_PG_GATES_PASS | 真实PG324业务增量、7状态迁移与52次受限事务检查通过；不代表千人/万人压力测试 |
| C13 | ROUND7_INDEPENDENT_SCOPED_PASS | 新SHA37项独立执行及真实PG原证据复核通过；本轮审查范围无剩余FAIL |
| C14 | RULES_REVIEW_NOT_DISPATCHED | 证据准入程序回归通过；商业规则与真实酒店/媒体权利的独立审核本轮未执行 |

## 独立意见与原始证据

- [C13新候选37项报告](c13-final-afc142e1/WIDTH_afc142e1_REVIEW.md)、独立测试脚本/JUnit/SHA256位于同目录。
- [C13最终CI审查](c13-ci-final/FINAL_CI_REVIEW.md)另附于`c13-ci-final/`：独立核对真实PG原始artifact、固定来源、旧失败关闭及skip精确节点映射。CI观察与C13亲自执行分开记载。
- [完整CI状态](final-ci/WORKFLOWS.json)、[Python四分片及旧10失败映射](final-ci/parent/RESULT.json)、[PG旧7失败映射](final-ci/PG_INCREMENT_RESULT.json)。原始JUnit、日志和archive哈希一并保留。
- 历史原FAIL：[C13预审](c13-preview/)、[首轮CI](first-ci/)、[首轮PG与宽度修复](postgres-width/)；前产品的79/29项报告按各自SHA保留，未迁移成新SHA执行记录。

## 尚未授予的结论

真实酒店代理权、真实媒体权利、商业规则专项意见及真实供应商/PSP验收仍未完成；C14证据准入程序回归通过不等于C14商业审核通过。完整305义务/1009场景清单未改，未签发全局完成率或发布PASS。

C09部分恢复用例为事务/SystemExit注入；C11确有SIGKILL后恢复，但测试主动将持久租约过期，不能推导自然超时的生产恢复SLA。HTTP认证由独立旅程验证，直接route/服务层压力检查不冒充HTTP认证覆盖。

没有访问香港运行环境，没有真实供应商、商户密钥或资金操作；Draft保持未合并、未部署。独立AI审查不新增真人签名或KMS前置要求。
