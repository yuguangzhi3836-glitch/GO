# Round 7 — 授权、门禁、恢复和差额修复

用户要求先修授权与门禁，再修执行恢复和资金差额，并由 C13 沿完整旅程独立复验。

当前固定产品：`afc142e16c050c0000da5a11a312620387be8f79`；application tree `ac23b75a75325091c5a95434238473a5592468a7`。前一产品及独立79项执行绑定详见c13-final-8f66ebfc。完整源码由父树加明确变更构成，本地只物化 177 个已逐一验证 Git blob 的文件；不宣称本地跑过完整仓库。

## 修复与边界

- 所有内部 Hosted 路由核验持久身份、当前会话/角色、具体权限及数据库解析的酒店范围；内容接口由其独立范围校验负责。跨酒店批量入口要求全部酒店范围；PII 默认掩码，经理揭示需审计。staff 标签不再作为自授权来源。
- publish/page/media/availability/reserve 消费同一独立审批记录。原图 bytes、来源提交者、content snapshot、房型容量、fare hash/version、variant/pool 映射组成清单；变化、撤销、缺字节和旧无来源媒体均阻断。来源提交者和内容 maker 均不得自审。此链只在明确 ENGINEERING/ISOLATED_FIXTURE 模式开启，真实媒体权利和酒店代理权仍 HOLD。
- 审批先持久化 APPROVED_PENDING_EXECUTION；业务效果、库存、通知、Trips 与 APPROVED_EXECUTED 在同一事务提交。故障留下诚实的可恢复状态；相同 checker/证据重试，成功重放不重复执行；订单版本变更须重新审批。
- 未收费且没有任何支付授权、尚未入住的确认申请可退出，库存与 Trips 同步；有资金授权、UNKNOWN 或已入住不能从该路径绕过资金/费用保护。
- 租车 100→50 未退款→再维持50，可以按最新裁决补差额；已补至50再维持50不再退款；上调目标高于实际净扣款拒绝。过时版本、UNKNOWN、跨根与重复资金动作保护不变。
- 未有结构化数量与价格规则的加床请求被拒绝，不把 extra_beds=999 当免费可售库存。加床商品完整配置仍待后续实现。
- 0139 迁移增加媒体服务端提交主体/授权绑定及 publication review 表，旧来源未知资产不回填为已核验。受控 staging bootstrap 只创建 draft；本轮未访问或部署 staging。

## 验证记录

开发者隔离 SQLite 回归 145 PASS、0失败/错误/跳过。前序开发失败日志保留，较宽本地套件因局部检出缺 go_hotel.main/flight/rental.service 无法运行，不能视为完整回归通过。

C13 独立预审真实发现三项 P1：未收费确认取消死路、11 财务入口范围遗漏、媒体自审；当时结论 FAIL 不授最终 PASS。三项产品修复后已交最终固定 SHA 复验。资金旧断言已改为明确区分历史资格与实际净扣款执行，保留已补后上调不得补扣测试。

当前远端 CI 待新 gate；C13 最终结论待独立报告，C14 本轮未派发。固定 305 义务/1009 场景清单不变，不用测试数量替代整项验收。Draft 不合并不部署，真实供应商和 PSP 保持 HOLD。

## C01–C14 当前可观察工作

| Cell | 状态 | 工作 |
|---|---|---|
| C01 | IMPLEMENTED_PENDING_C13_CI | 酒店范围授权、媒体提交主体、版本化发布门禁、未付款确认申请取消 |
| C02 | NOT_REASSESSED_THIS_ROUND | 保留既有实现，未冒充当前执行中 |
| C03 | NOT_REASSESSED_THIS_ROUND | 同上 |
| C04 | IMPLEMENTED_PENDING_C13_CI | 最新裁决相对历史原扣款的差额资格 |
| C05 | NOT_REASSESSED_THIS_ROUND | 保留既有实现 |
| C06 | NOT_REASSESSED_THIS_ROUND | 保留既有实现 |
| C07 | SHARED_AUTHORITY_CHANGED_PENDING_CI | 具体权限、有效身份会话和酒店范围 |
| C08 | NOT_REASSESSED_THIS_ROUND | 保留既有实现 |
| C09 | RECOVERY_CHANGED_PENDING_CI | 审批授权/执行状态分离，失败恢复与重放 |
| C10 | PROJECTION_CHANGED_PENDING_CI | Trips未付款确认申请可取消；终态关闭 |
| C11 | MONEY_GUARDS_PENDING_C13_CI | 只按当前净扣款和最新裁决补差额，UNKNOWN不放行 |
| C12 | CI_CONFIG_UPDATED_PENDING_RUN | 新增酒店旅程和补偿回归加入真实PostgreSQL门禁 |
| C13 | RUNNING_FIXED_PRODUCT_REVIEW | 独立预审3项P1 FAIL已推动修复；最终候选重验中 |
| C14 | RULES_REVIEW_NOT_DISPATCHED | 未授商业条款、真实酒店授权或媒体权利通过 |

## 完整 CI 首次发现与迁移修复

首个 gate `42d71f4e` 的真实 PostgreSQL 日志确认：已有历史创建迁移会引用当前模型，在0139前已建媒体来源列，因此无条件ADD COLUMN失败。历史仅建rail表再stamp的隔离升级也可能没有媒体表。

新迁移不修改旧迁移：仅补缺字段，对已有字段/表/索引核验结构，PG additionally核验时区类型；媒体表不存在时不凭当前模型补造。downgrade若有媒体提交来源或publication审核历史会拒绝丢失数据。历史head断言更新到0139，新增8项本地测试通过；这8项包含SQLite原表/无表/当前metadata、错误结构和不可丢失历史，以及PG反射类型的时区校验单测，不冒充完整迁移链或真实PG执行。

旧业务候选C13独立79项执行已通过，三项预审P1已定向复验关闭。新product仅改迁移与迁移测试两文件，业务源码不变；C13差异重绑定另附，不能把新SHA称为重跑过旧79项。首轮失败日志和原意见原样保留，新gate所有受影响CI仍需重跑。

## 旧测试的明确授权与发布前置

首轮完整Python四分片RESULT：3218执行项，3201 passed、10 failures、0 errors、7 inherited skips（包含原有subtest计数）。失败原日志保留：0139重复列/缺媒体表、新head和table集合断言、未授权财务/UNKNOWN接口、未审批库存销售和供货投影公开页。

在迁移修复之外，最后补7个旧测试文件：库存先走明确合成原图/内容独立审批，财务/UNKNOWN使用真实持久身份的显式酒店授权，UNKNOWN仍先断言无范围403。供货projection测试保留持久房价和去测试标签断言，新增公开页未审批必须阻断的断言。迁移测试更新新head、新表及0138拒绝丢失历史时的真实版本落点。没有删除收费、权限、库存或数据保留约束；C13对这7个差异独立检查。

本地库存3项通过。最终新SHA同head完整CI待复跑，首轮成功结果不直接迁移。

C13 已在当前 `49965321` 候选实跑29项：18个自编HTTP业务探针、8个迁移专项、3个库存用例，全部通过。旧79项/8项原始记录分别保留，不跨SHA相加。完整CI仍待最终gate实测。

## PostgreSQL实际失败后的字段修复

首轮PG增量7失败：已确认订单状态42字符写入VARCHAR(40)、批准待执行状态26字符写入VARCHAR(24)。C13追加静态检查，人工确认凭据绑定39/VARCHAR32、对账结论37/VARCHAR32、商户绑定29/VARCHAR24三处同类问题。未将这三处静态确认冒充实际PG复现。

5列定向扩至64，0139同时覆盖旧列宽升级及当前metadata已建64。缺失的无关历史表不自动补造。保留原状态字符串；降级先查全部5列及媒体/审核记录，任一潜在丢失即拒绝，在检查通过后才执行DDL。新增7项真实DDL与索引/数据保留断言，在PG作业使用独立临时schema实际执行。

开发者SQLite迁移15项、HTTP旅程与资金30项通过。新固定SHA的C13独立结论及完整CI仍待本轮实测，既有PASS不自动迁移。原失败日志与C13静态宽度报告均保留在postgres-width目录。
