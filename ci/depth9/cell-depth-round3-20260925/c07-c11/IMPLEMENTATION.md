# C11 管理员押金运营候选

新增只读 review 汇总 C04 当前义务、裁决、无损/取消返还事实及 C11 钱图。所有写动作仍走既有资金 API，在事务中重新核权限、版本和来源；UI 不提交金额或收款方。

管理员组件 `GORentalDepositOperations.render({container,orderId,request})` 由 root 的租车订单页挂载。每个授权、裁决结算、正常释放按钮要求明确勾选；响应后读回。提交结果不确定时只在最新权威快照仍允许完全相同 URL/body 的情况下提供原请求重试。unknown、钱图损坏、读取失败均停止执行。来源变化要求重新审核；丢失响应不直接宣布成功。

GET `/internal/v1/admin/mobility/rentals/orders/{order_id}/deposit-money-review` 使用 GO_ADMIN/admin:approve 及隔离门控。`movements` 是原始核对记录，不是整图成功证明。钱图不一致返回 RECONCILIATION_REQUIRED 和 null 金额。源事实失效或争议链读取失败不开放动作。

自测：36 个 backend（新增 review 8，既有资金 28），9 个前端交互状态测试通过，无 skip。JUnit 和 node 原始结果同目录。真实 API 浏览器旅程由 C12 扩展，PG 与集成由 root 固定产品版本后执行；自测不等于独立 C13 验收。

本轮未实现：unknown 可信收据修复、已结算申诉后的独立补偿、全量财务账期运营 UI、持续运营任务派发复查。NOT_ASSESSED 项保留在 NORMALIZED.json 的 C11 全职责 22 项分母；C07–C10本轮只扩充清单，不宣称完成。外部真实 PSP、供应商和部署仍 HOLD。

冻结源码与测试五文件见 MANIFEST.json。共享 app/index/main 未由 C11 修改。
