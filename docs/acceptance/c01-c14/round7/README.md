# Round 7 — 授权、门禁、恢复和差额修复

用户要求先修授权与门禁，再修执行恢复和资金差额，并由 C13 沿完整旅程独立复验。

固定产品：`8f66ebfc2c54bd76de91d5062ccb444a7f43179f`；application tree `85d01481aa5775f2f9e45673cd56786644c7b70f`。完整源码由父树加明确变更构成，本地只物化 177 个已逐一验证 Git blob 的文件；不宣称本地跑过完整仓库。

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
