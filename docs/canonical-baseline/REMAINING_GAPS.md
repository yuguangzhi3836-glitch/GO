# 当前候选的验收范围与剩余缺口

唯一应用源码：PR47 `application/`，测试提交 `800538c1714dd3e50f3abf8c97964a2ee8ba4e72`。
应用 Git tree：`219e4ca8a7176e3ff4c32af5524e322635c2d845`。
源码 SHA256 树：`be152b85b7b55ae6cc661446b20a309fc4c004c1c0c25f7b0c74fe0ea1c664da`。
当前清单见 `CURRENT_CANDIDATE.json`；完整指纹见 `DEPTH42_SOURCE_FINGERPRINT.json`；本轮八个源码差异见 `DEPTH42_GO_TRIP_REPAIRS.json`。

## 已关闭的本次隔离旅程缺口

Run 34694860505 的六个 CI job 均成功。39 个浏览器场景通过；六单独立账本审计通过。详情视口逐项记录由绑定本轮源码的原始 browser-results.json 与归档校验确认。
消费者真实界面完成登录、两位旅客确认、住宿／往返机票／火车／接送／租车／景点下单、模拟支付和退款；六单刷新重入、所属供应商及管理员同单最终状态核对通过；无关供应商保持 404。
酒店必选退款确认框先验证不可跳过，再由浏览器明确勾选。每单均核对报价、币种、最终退款记录、原支付扣款与退款次数，并重放请求确认不产生重复退款。
独立只读 SQLite 审计绕开应用投影，核对真实测试数据库的订单、支付意图、冻结绑定、授权／扣款／退款、两组借贷分录，六单 PASS。
小屏订单字段溢出已修复，长编号完整换行，未隐藏数据。新版 UX 汇总在任何场景失败时维持 HOLD。

本轮新增关闭：GO Trip 全部状态订单及订单号／名称搜索、酒店返回统一订单入口、酒店退款中断后进度同步、非酒店状态更新的供应商归属保留、逐资金动作借贷分录不一致不能显示账本平衡。Python 1723 PASS、6 SKIP、0 FAIL／ERROR；前端 246、兼容 34、隔离 HTTP 148 项通过。手机本地类型与契约检查通过。

## 仍为 HOLD 的范围

| 项目 | 剩余范围 |
|---|---|
| 完整三端 UX／大师级 VI | 本次仅判定上述代表旅程；没有证明所有菜单、异常分支和业务组合。截图仍有中英混排、管理员泛化字段标题等显示债务，不能认定完整产品体验 100% |
| 真实供应与银行结算 | 使用合成数据及模拟适配器；没有调用真实供应商、库存或银行。本次资金范围是 ORIGINAL_PAYMENT_ROOT，不包含所有改期补款、押金等支付根 |
| PostgreSQL | 本候选回归中六项独立 PostgreSQL 检查跳过；不能继承旧版本 PostgreSQL PASS |
| 搜索交互视觉验收 | 新查询已通过 Node VM 交互测试；尚未单独记录真实浏览器搜索输入及原生触控验收 |
| 原生端 | 移动网页视口不能代替 iOS／Android 真机或原生模拟器完整旅程 |
| 供应商认证脚本历史修订 | 此前未纳入的认证输入修订没有在本次重做或执行；相关完整功能保留门禁仍 HOLD |
| Sealed Node／部署包 | 本次记录 Node 22.22.0、Chromium 140.0.7339.186、Python 3.13.5 及冻结依赖；尚未生成并独立恢复绑定新源码的完整镜像／部署包 |
| 香港／Production | 未访问香港或 Production，没有新的现场运行或签名回执验证；未合并、安装、部署 |

`CURRENT_PARENT.json` 与旧 ZIP／镜像保留为历史统一父包，不能拿来安装本候选。
旧 PR48、6d2e75cb、4372aad8 的失败证据按各自源码归档，不转移为当前 PASS。

ISOLATED_THREE_END_RECORDED_JOURNEY=PASS
ISOLATED_SIX_VERTICAL_ORIGINAL_PAYMENT_REFUND=PASS
FULL_THREE_END_UX=HOLD
SEALED_NODE_GATE=HOLD
FINAL_RELEASE_GATE=HOLD
HK_STAGING=NOT_ACCESSED
PRODUCTION=HOLD
