# GO 四品类开源复用评估
日期：2026-09-27（Asia/Shanghai）
类型：DOCUMENTATION；状态：源码与官方资料初审完成，尚未取得运行验收。
GO 固定源码基线：`2b4863540d07b9a07aed1fc4d8cec9d081602f0b`。此文件不代表部署、C13/C14 或供应商接入 PASS。

## 1. 用户决策与评估口径
余总本轮明确授权：酒店、机票、租车、景点门票主动搜索成熟开源方案；确实优于自行开发的能力予以复用，由开发侧负责评估和整合。继续遵循现有审核发布程序。
比较同一业务能力，不以星数、界面完整度、文件数或开源标签代替稳定性证据。成熟度包含：业务覆盖、库存一致性、资金正确性、维护状态、许可证适配、运营成本和迁移风险。
开源库存管理软件、第三方库存分销平台、API SDK 是三种不同产物。软件安装不会自动带来航司/酒店/景区授权库存，也不替代商务合同与真实联调。

## 2. 决策摘要
| 品类 | 候选 | 本轮结论 |
| --- | --- | --- |
| 酒店 | QloApps；HotelDruid | 纳入酒店后台/房态房价功能对标；尚无证据支持替换 GO 已有逐日库存核心。QloApps 是 PHP/MySQL PMS+预订引擎，与 GO 的 Python/PostgreSQL 差异明显。HotelDruid 的预订引擎及渠道管理扩展是专有模块，不能按全部开源处理。 |
| 机票 | 供应商正式 API 与仍维护的 SDK | 本轮未找到足以替换 GO 完整机票业务链的成熟开源整套系统。优先复用所选供应商正式 API/SDK。Amadeus Self-Service Python SDK 与 Duffel 旧 Python SDK 已归档，排除为新接入默认依赖；这不等于供应商所有商业产品停服。 |
| 租车 | BookCars | 多供应商、车队、调度、分时定价值得复用评估；本次源码初审未通过交易核心替换条件。保留为车队/后台能力候选，先验证并发占用、支付事实绑定和交还车异常。 |
| 门票 | pretix | 第一优先隔离验证对象：配额、场次、临时保留、电子票和核销具有较强公开资料支持。优先评估经 API 接入的票务引擎；不得直接将接入文档能力当作 GO 已通过验收。 |

本轮没有一个候选获得“直接替换生产核心”的结论。pretix 获得进入首轮对照验证的优先级；BookCars 的资金及库存路径未通过静态初审。
该结论不要求继续全量自研。相反，下一步应先做候选能力验证，再决定哪一段复用/替换，避免先重复开发再比较。

## 3. GO 当前源码抽查结果
以下均是固定 main 中选定路径的观察，不是对所有入口、未合并 PR 或香港运行版本的总评。项目状态文档仍绑定 9 月14日旧 checkpoint，未把其中旧状态当成今天运行事实。

- `application/src/go_hotel/services/hosted_reservation_operations.py` 已含逐日库存/房价、共享库存池、入住和提前预订限制、交易内条件更新与幂等处理。不能因旧 `hosted_direct_booking.py` 的简化计数器就断言 GO 没有逐日库存。
- `application/src/go_hotel/flight/service.py` 所抽查搜索路径仍生成固定工程航班，并输出 SIMULATION / external_live=False；另有改签、退票、恢复和统一账本衔接。此观察不否定其他连接器或候选已有工作。
- `application/src/go_hotel/mobility/rental/service.py` 所抽查搜索路径是两类工程车辆及按天计价；已经对接订单、售后、履约和统一资金桥。不能把这个入口当成真实车队可售库存证明。
- `application/src/go_hotel/attractions/service.py` 所抽查商品为工程目录，但已包含预订条款绑定、日期/场次、容量申请、改期、退款和核销时间窗。
- `application/src/go_hotel/services/vertical_capacity.py` 具有数据库行锁、占用/释放、改期双资源和历史订单检查。外部状态未知时保留占用。未来替换必须保留这些行为。
- `application/src/go_hotel/connectors/base.py` 已有硬锁库存、释放、幂等释放、价格锁等能力声明。新引擎需按实际支持情况声明，不能默认全部支持。

未执行 GO 全量测试，未执行任何上游项目运行验收，未计算新的模块完成率。

## 4. 上游证据与具体风险
### QloApps / HotelDruid
QloApps 固定审阅分支 head：`d8cf510fe5c55abae5f612f8ecd608ec2c182416`（develop；并非部署版本）。
仓库当前未归档，许可证元数据为 OSL-3.0。官方 release 页面列出 PHP/MySQL 兼容与房型、高级价格规则等能力。
适合对标：房态日历、房型/房间、价格限制、前台运营。
GO 适配需单独证实：多商户隔离、同房型多价格计划共享库存、接口原子占用、退款/账本映射、历史订单迁移。
HotelDruid 官方说明其核心为 AGPL；booking engine 和 channel manager 为 hosting 上的 proprietary modules。不能据核心开源承诺所有渠道同步免费可用。
许可证核对是接入清单，不是对所有衍生作品义务的法律结论。独立部署/API 通信也不自动免除许可证要求。

### BookCars
固定审阅 head：`344b8d9d007bdd5808ca0c067d2af5632ecbcd7f`；仓库未归档；MIT。
检查：
- `backend/src/controllers/bookingController.ts`
- `backend/src/controllers/carController.ts`
- `backend/src/models/Booking.ts`
- `backend/src/routes/bookingRoutes.ts`
- `backend/__tests__/booking.test.ts`
- `backend/package.json`

源码初审发现：
1. checkout 中 paymentIntent.status 非 succeeded 时调用 res.status(400).send(...)，但此分支没有 return/throw；后续仍设置 booking 状态并继续 save。属于可定位的控制流风险，尚未运行复现，不推断所有支付路径都有该问题。
2. 查询车辆路径有 overlappingBookings 过滤，但抽查 create/checkout 的写入与 Booking schema 未见与同车辆时间段占用一体化的原子排他机制。搜索过滤不能证明同时结账不会双订；需完整复核和并发试验。
3. 所检模型/控制器使用 Mongoose，整套引入将增加与现有 PostgreSQL 的集成及运行复杂度。
结论：功能覆盖可借鉴，交易核心替换暂不通过。不能为了减少 GO 的 bug 而直接导入未经验证的资金/库存行为。

### pretix
审阅 head：`2af8d29ca99510612fdb005d4ec7d39d83aed6ba`（master 开发头，仅作来源标识）；仓库未归档。
官方称已用于数千场活动、累计数百万票；这属于上游声明，不是 GO 的负载实测。
核心具有配额、订单、子场次、cart reservations、核销等 API。许可证以仓库 LICENSE 为准，主要为 AGPL v3 加额外条款，部分代码另有许可。
官方 custom checkout 文档明确：
- API 创建订单默认检查配额、重复座位和已用兑换券，但不自动校验所有销售时间窗和商品/活动最小最大数量；
- 套餐附属商品、费用不会全部自动生成；
- 通过 consume_carts 转订单可消费已有保留配额；不能把查询余量等同于硬锁；
- GO 自管支付需要自行处理相应确认/退款整合，不能认为自动继承 pretix 所有支付保障。
结论：值得优先试点，但自定义结账适配层仍有明确责任。

### 机票
- `amadeus4dev/amadeus-python` API metadata archived=true；官方页面显示 2026-07-17 归档。
- `duffelhq/duffel-api-python` archived=true；官方页面显示 2024-09-12 归档，README 明示不再支持。
- Duffel 当前官方 API 文档包含搜索/订单/改签/取消和 webhook，但商业 API 不等于开源库存引擎；本轮未确定 GO 采用 Duffel。
优先顺序：GO 既定供应商方案的接口契约和中国业务覆盖 -> 当前维护 SDK/直接标准 API -> 适配与沙箱验证。不能为复用某 SDK 改变供应商商务决策。

## 5. 同题对照验收与采用条件
两套方案使用相同输入、期望结果与可追踪记录。结果必须区分 NOT_RUN / PASS / FAIL / NOT_SUPPORTED。

共同必验：
1. 100 个并发请求抢 1 份库存，最多 1 个有效占用；不足库存无负数。
2. 同幂等键同请求重复返回同订单；同键不同内容拒绝。
3. 供应商处理成功但响应丢失，不重复下单；查单恢复。
4. 保留到期与支付回调竞态，不产生“收款成功但无票/无房”静默成功。
5. 取消、超时、退款、重复回调各自只释放一次；未知外部结果先查明。
6. 断电/进程退出后的持久占用和恢复；重启不清空已售库存。
7. 商户 A 无法读改商户 B 的库存、订单、旅客资料。
8. 金额、币种、订单、乘客/游客与支付事实匹配；浏览器回跳不作付款依据。
9. 对账差异能定位到原始事件并修复，不建立平行资金账本。
10. 迁移保留已有未完成订单；切换和回滚只允许一个库存写入权威。

品类必验：
- 酒店：跨多晚原子占用；多价码共用房型；停卖/维修；最短最长连住；多人/多房；改期保留原订单；no-show 和离店释放规则。
- 机票：报价过期再验价；多人多航段；部分乘客退改；PNR 与电子票事实；出票未知查单；航变；供应商退款与资金退款区分。
- 租车：同车重叠租期、相邻租期缓冲、延迟还车、维修停用、异地还车、车型转实车、押金解冻、损伤争议。
- 门票：按日期场次配额、家庭套票共享容量、儿童资格/实名、销售与核销时间窗、重复扫码、离线核销回传、部分退票、取消票失效、跨时区。

采用必须同时满足：目标能力相对 GO 有可验证收益；不回退现有强约束；上游版本与许可证固定；迁移/运维成本可接受。无证据不打高分。
测试所述并发数是用例设计，不是已运行或容量承诺。

## 6. 整合方式
优先在隔离环境以 pretix 的稳定发布版作首个比较对象，固定版本后重读该版本 API，而非直接用开发版。
映射建议：GO supplier -> organizer，product -> event/item/variation，visit date/session -> subevent，容量 -> quota，临时占用 -> cart，履约 -> order position/check-in。
GO 保持统一用户、订单索引、Trips 和已确定资金规则；票务引擎负责被委派的库存/票码权威。同一资源不允许 GO 和 pretix 各自独立扣减再“最终同步”。
超时后的重试策略必须根据上游实际幂等/查单保证设计；仅写入 api_meta 的 GO ID 不等于唯一约束。
先只读对照，再隔离写入验证，再形成可审阅接入候选。真实运行切换须通过现有审核发布流程。
如新引擎增加服务/数据库，后续实现需声明 TOPOLOGY/BUILD/MIGRATION 等真实变更类型。

## 7. 完成状态
已完成：官方项目检索、维护状态核对、GO 四品类关键路径抽查、BookCars 交易路径初审、pretix API 适配边界核对、候选取舍与验收清单。
未完成：安装上游软件、运行对照试验、性能/故障实测、许可证部署方案评审、供应商沙箱联调、源码整合。
未操作：真实库存、真实支付、生产或香港部署。本报告没有声称软件已接入或已替换 GO。

## 8. 来源（2026-09-27 检索）
- https://github.com/Qloapps/QloApps
- https://github.com/Qloapps/QloApps/releases
- https://www.hoteldruid.com/en/
- https://github.com/aelassas/bookcars
- https://bookcars.github.io/
- https://github.com/aelassas/bookcars/blob/344b8d9d007bdd5808ca0c067d2af5632ecbcd7f/backend/src/controllers/bookingController.ts
- https://github.com/aelassas/bookcars/blob/344b8d9d007bdd5808ca0c067d2af5632ecbcd7f/backend/src/controllers/carController.ts
- https://github.com/aelassas/bookcars/blob/344b8d9d007bdd5808ca0c067d2af5632ecbcd7f/backend/src/models/Booking.ts
- https://github.com/pretix/pretix
- https://github.com/pretix/pretix/blob/master/LICENSE
- https://docs.pretix.eu/dev/api/guides/custom_checkout.html
- https://docs.pretix.eu/dev/api/resources/quotas.html
- https://docs.pretix.eu/dev/api/resources/carts.html
- https://docs.pretix.eu/dev/api/resources/orders.html
- https://docs.pretix.eu/dev/api/resources/checkin.html
- https://github.com/amadeus4dev/amadeus-python
- https://github.com/duffelhq/duffel-api-python
- https://duffel.com/docs/guides/getting-started-with-flights
- https://duffel.com/docs/api/order-changes
- https://duffel.com/docs/api/order-cancellations
- https://duffel.com/docs/guides/receiving-webhooks
