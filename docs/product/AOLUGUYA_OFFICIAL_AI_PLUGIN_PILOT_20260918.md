# GO 官方旅行插件：敖麓谷雅首店样板

状态：IMPLEMENTATION_BRIEF / REAL_BOOKING_BLOCKED_PENDING_EVIDENCE
分类：DOCUMENTATION（本 PR）；后续实现需分类 PRODUCT_FEATURE / TEST_ONLY，涉及迁移或拓扑时另行分类。
固定检查基线：dc34ee5cabed7c6e93507d178fdd3a62a426399e
发起依据：用户在本轮明确要求先实现真实搜索、报价、官方预订承接和状态回读；只有连接真实可订资源并取得确认凭据才算预订闭环。

## 1. 目标与范围

第一阶段只覆盖哈尔滨敖麓谷雅，不扩供应商、不扩品类、不声称已在任何 AI 平台正式上架。
复用 application/ 现有 Agent Gateway、Hosted Direct、库存、身份授权和供应商证据；不新增第二套订单/支付真源。
先以 MCP 接入一个可控测试客户端，协议兼容性、授权、真实供给与平台上架分别验收。
开发和模拟验证可在隔离环境完成；模拟结果永远不能替代真实供应商结果。
本文件不派发签名任务，不改变香港/生产权限，不授权真实扣款或创建会占用真实库存的测试订单。

首个验收查询：
- property：哈尔滨敖麓谷雅；现有 slug：aoluguya-harbin
- check_in：2026-10-01；check_out：2026-10-03；Asia/Shanghai
- rooms：1；adults：2；bed：KING；room name：卧云
- 不预设含早、不预设套餐、不预设库存/价格，不以历史套餐价报价。
- 卧云的 canonical room ID 必须从当前权威目录核准，不猜测英文名或复制错房型。
- 两晚无房也是合法真实查询结果，不能为了验收虚构可售；改日期/房型需用户明确选择。
- 最终真实订单验收必须另绑定用户认可的报价、取消条款、入住人及必要交易授权。

## 2. 本轮源码核查事实（非运行验收）

| 路径 | 已观察内容 | 实施含义 |
| --- | --- | --- |
| application/src/go_hotel/agent_gateway/runtime.py | 安装 REST / MCP / A2A 网关 | 复用入口，不新建平行交易系统 |
| application/src/go_hotel/agent_gateway/mcp.py | offer.search / reserve / payment.prepare / commit / order.get 等工具 | 存在工具定义不等于已接真实酒店 |
| application/src/go_hotel/agent_gateway/real_core.py | HOTEL search 调 booking_service.search；Offer 中默认 official_direct=True；machine_bookable 由库存可用性推导；evidence 外部 live 默认为 false | 新公共样板不得从缺省值或库存数字推断官方可订；必须增加可信供给判定和明确来源 |
| application/src/go_hotel/connectors/registry.py | default() 返回 conn_mock_hotel；注册 mock_connector | 不允许样板回落此默认路径后声称真实搜索或成交 |
| application/src/go_hotel/services/aoluguya_supply_truth.py | 官方 feed/console/API 供给快照、时效检查及投影；保留 RESERVATION_REQUEST_ONLY、payment_available=False | 官方资料或快照不自动等于指定入住日库存、报价、交易确认 |
| application/src/go_hotel/api/routes/hosted_direct_booking.py | /v1/direct/{slug}/catalog、/availability、/reservations、/v1/direct/reservations/{id} | 现有首店接入路径；状态接口已有 created_by 归属校验，应保留 |

源码核查没有访问香港数据库或读取真实供应商凭据；不据此推断今天现场已连接/未连接。
README/GO_CURRENT_STATE/HOTEL 状态页仍标注9月14日 checkpoint；不能直接代替当前运行事实。
EASON D:\Code\GO-BOSS 本地 HEAD 为 9645c6f522544d0751ee658e0ab9f131043e7df2；
git fetch origin main 失败，提示 cannot prompt / unable to get password。未改该工作区。
本 PR 基线通过现有 GitHub Connector 独立核准。

## 3. 最小产品切片与接口映射

以下为待实施的契约，不是已注册的工具名称。

| 操作 | 复用基础 | 必须满足 |
| --- | --- | --- |
| resolve_hotel_and_room | 当前 canonical 酒店/房型目录 | 酒店及卧云大床唯一ID、媒体对应、官方身份来源；无法确认则返回待核准 |
| quote_stay | Hosted Direct 按日 availability + 当前供给权威 | 每晚库存/价格、入住人数、房间数、税费总额、早餐权益、取消规则、币种、来源时间、有效期 |
| prepare_official_checkout | 现有授权及预订流程 | 服务端持久化 quote 与用户会话绑定；跳转不丢日期/人数/房型；重新校验报价；不在模型上下文传入住人隐私 |
| get_booking_status | 已有预订/订单事实与归属校验 | 认证、对象归属、数据最小化、最新供应商确认事实；未知状态持续核对，禁止盲目重发 |

报价身份必须绑定 hotel_id / room_id / rate_plan_id / check_in / check_out / rooms / occupancy / currency /
per-night breakdown / total / cancellation terms / source version / valid_until。
报价签名/哈希仅校验完整性，不替代来源真实性。缓存过期或价格变化需重报价、重新确认。
查询不承诺库存；进入预订需遵守原有 Reserve/Commit/Release/Expire 原子性及幂等规则。

状态语义必须明确：
- NOT_CONNECTED：没有受信任可订连接；不得显示无房。
- SOLD_OUT：来源已核实该日期无房。
- ROOM_UNAVAILABLE：指定房型/床型不可售。
- QUOTE_UNAVAILABLE：上游失败或事实过期；不得回落模拟报价。
- HANDOFF_READY：已准备官方承接入口，不代表下单。
- REQUEST_SUBMITTED / PENDING_SUPPLIER：请求已接收，待确认。
- CONFIRMED：供应商已接受这一个订单，且确认凭据经受控入口核验并绑定订单/酒店/日期/房型。
- UNKNOWN：结果未知，先 reconciliation，禁止超时后盲目重发。
- REJECTED / EXPIRED / CANCELLED：按已有交易事实对外映射，不改写历史。

预订状态与支付状态分离。有效到店付政策下可以供应商确认但未付款；
要求预付的报价必须满足对应支付规则。回读真实 CONFIRMED 不等于支付已成功或已结算。

## 4. 外部 AI 与数据主权

所有对外结果走字段白名单及数据分类策略。公开目录与公开报价允许按政策输出；
个人行程/身份/联系方式/完整确认凭据/内部日志/账本/供应商机密不直接返回外部模型。
私人步骤在 GO 第一方安全页面或私有推理通道完成。
对外只返回政策允许的最小状态及受控承接信息；若现行政策不允许该状态披露，则仅提示在 GO 查看。
不能简单把现有 AgentEnvelope/evidence 完整序列化给外部 AI。
禁止消费者插件调用商家库存改写、管理员决定、支付密钥或内部运维工具。
所有订单读取校验用户、客户端、授权目的和对象归属；猜测订单ID不能读取他人订单。
交接引用短时有效、限定用途，不包含原始 PII，不授予通用账户权限。

## 5. 真实闭环准入资料

这些资料必须来自受控系统或酒店授权运营者，不能由模型填写“已验证”替代：
1. 当前部署 artifact/source identity 与可复现实测入口。
2. 敖麓谷雅官方供应商身份及有效操作授权；酒店管理台也可作为授权供给通道，不强制引入 PMS。
3. 当前 canonical 卧云大床 ID、rate plan ID、房型媒体映射。
4. 指定入住两晚的有效库存、报价、税费、权益和取消规则。
5. 官方承接主体、可用预约/预订能力、库存扣减/释放机制及幂等查询能力。
6. 供应商确认回执的可信获取、验真与订单绑定路径（受控酒店员工确认或真实接口，不接受任意客户端自报）。
7. 需要支付时，当前 PSP 环境及能力证据；没有真实支付能力不得声称已支付。
8. 合法的真实端到端验收授权与可控退出方案。

该首店不以“取得外部 PMS API”作为唯一通路，但必须有酒店真实授权、真实资源控制与真实确认机制。

## 6. 验收顺序及证据

A. 内部实现：真实源/未连接/模拟源严格分离；先测未连接时 fail-closed。
B. 搜索报价：样板查询匹配唯一酒店和房型；两晚计算、人数/间数、价格变化、停售、过期报价验证。
C. 承接：手机端保持上下文；授权与幂等；重复提交不能重复占房；超时不能误报失败或重发。
D. 状态回读：供应商回执匹配；回执重复/乱序/伪造/订单不匹配被拒；跨用户越权被拒。
E. 真资源闭环：绑定同一部署、同一报价、同一订单和经核准的供应商确认凭据；重登后状态一致。
F. 平台接入：协议握手、工具 schema、鉴权及平台审核单独记录；不把内部工具测试当成目录上架。

每份证据记录 UTC 时间、固定源码 SHA、运行 artifact、测试环境、用例ID、原始日志/回执摘要及校验值。
凭据与私有原件留在受控证据存储，对外/仓库只保存按政策允许的脱敏摘要与引用。
测试夹具必须明确 TEST_FIXTURE。没有真实供给及确认凭据，REAL_BOOKING_CLOSED_LOOP 一律 NOT_PROVEN。
本 PR 验收状态：代码核查完成；实现、自动化测试、实时供给、真实预订、平台上架均未完成。

## 7. 下一实施动作

在可执行的当前源码工作树上，将敖麓谷雅 Hosted Direct 的受控查询/报价路径接入既有 Agent Gateway，
先落地“无真实来源时拒绝可订声明”的合同与负向测试；随后接通第一方安全承接和最小化状态回读。
不得将原 conn_mock_hotel、静态图片目录、旧套餐价或 request-only 请求单包装为已完成样板。
真实供给资料与供应商确认路径核准前，保持公开可订/真实交易发布关闭。
