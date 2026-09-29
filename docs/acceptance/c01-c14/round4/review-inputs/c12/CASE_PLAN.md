# Round 4 C12 验收增量计划（接口冻结前）

参考基线 cb8928f；本轮新候选全部 PENDING，不继承上轮 PASS。保留原26条 journeys、原9项 mocked widget tests、原六域退款/酒店/租车运营 SQL 检查。原 operations.rentals 两订单及其严格数量不变，新增补偿独立订单与独立结果结构/SQL审计。

|ID|真实角色与动作|必需验证|状态|
|---|---|---|---|
|R4-C12-01|消费者页面创建独立 RENTAL→明确接受押金；maker 授权；消费者取还车；maker 开案；消费者回应；checker 裁决4000分；maker执行结算|原授权、CAPTURE4000分、RELEASE剩余，保存原movement IDs、金额币种与ledger快照；只真实UI写入|PENDING|
|R4-C12-02|同一消费者在已结算订单申诉；maker及原checker均不得复核；appeal_checker（第三管理员）减至1000分|申诉期间显示HOLD，不把申诉当补偿完成；独立复核版本与decision hash；原4000扣收/释放尚未改动|PENDING|
|R4-C12-03|有权运营者查看最新来源、明确确认并点击补偿3000分|body仅来源版本/hash等权威绑定，不手填金额；同一原capture追加COMPENSATION；当前net1000，原capture/release不变|PENDING，C11已确认接口，待冻结|
|R4-C12-04|刷新/离开重入；检查消费者金额说明；补偿成功后禁止再次主动执行|幂等重放作为明确标注的负面API补充或后端并发测试，不伪装UI动作；独立SQL只有一补偿，原根/原账不改|PENDING|
|R4-C12-05|readonly管理员看到无可执行动作；无权调用同一补偿路径|HTTP403且所有资金movement/ledger不变；角色、失败request ID、安全日志绑定|PENDING|
|R4-C12-06|来源过期版本、同源重复、UNKNOWN/不一致资金状态|后端真状态拒绝+独立widget只读禁动作检查分别标scope；无可信回执不执行恢复、不把缺事实写成成功|PENDING，UNKNOWN由真实后端拒绝证据覆盖，不新增伪恢复fixture|
|R4-C12-07|独立只读SQL审计新增订单|原根/payer/payee/currency一致；原AUTH/CAPTURE/RELEASE ID和数值不变；COMPENSATION parent指向原CAPTURE；正金额≤扣收；补偿DEBIT业务账户/CREDIT清算账户各一、金额币种一致、总4条资金分录；版本与源decision关联；无额外副作用|PENDING|

实现范围：拟新增 ci/journey-v2/compensation-depth.mjs 与 compensation-ledger.py；operations-depth仅追加hook并传既有真实UI helpers；run.py新增独立SQL且exit纳入。可能新增独立 mocked finance widget test 明确区别真实HTTP。业务/app文件不由C12修改，若需fixture先通知root。

UI等待沿上一批修复：精确查询单次auto-mount→目标order业务/资金GET→ready；填表后核值与原生checkValidity；失败截图取实际操作者页面。不得force click、缩减断言或用API写入替代裁决/补偿按钮。

环境：既有隔离SQLite HTTP Chromium，真实PG沿现有C11 job运行当前全部新增模块；保留PG205基线与35新增历史范围，不把旧计数硬编码为当前清单上限。C12只建议增量测试模块，root统一整合workflow。无真实供应商/PSP、无外部网络或香港部署；本地不绕过浏览器socket限制。
