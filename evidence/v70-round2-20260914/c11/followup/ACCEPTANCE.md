# 实施后的验收条件（尚未执行）

下列是V70-R2-C11-02设计的验收工单，不是PASS记录。原C11两个red仍保留。
测试必须绑定最终候选源码，使用独立数据库、独立事务读回和固定业务key；保留
异常位置、HTTP/claim、业务操作、资金行、订单/报价状态与运行日志。

| 编号 | 注入/操作 | 必须证明的结果 |
| --- | --- | --- |
| C11-A01 | FLIGHT_CHECKOUT：订单不存在/不属于请求人，未触及任何mutation | 正确拒绝；无payment root/movement/订单修改；安全失败的重试行为保留 |
| C11-A02 | FLIGHT_EXECUTE_CHANGE：报价不属于订单、缺少确认、过期或hash不符 | 无授权/订单状态提交；安全校验失败仍可在合法新请求中重试；不同payload不能偷用旧key |
| C11-A03 | claim资源绑定事务失败 | 不运行callback；不创建payment root或改签授权；错误可追踪 |
| C11-A04 | 绑定已存在且resource_id或payload不同 | 409冲突；不覆盖原claim身份，不越权读回结果 |
| C11-A05 | checkout首个事务提交前、明确回滚的写失败 | 独立连接证明回滚、无既有对应支付操作；只有此正面证明允许安全释放 |
| C11-A06 | checkout首个commit后、bridge前抛异常 | claim保留且resource_id可恢复；第二次相同key不执行callback |
| C11-A07 | checkout intent创建后、auth后、capture后分别失败 | 每个注入点恢复后同一payment root、最多一笔对应auth/cap；金额/币种/付款人不变 |
| C11-A08 | money返回UNKNOWN_EXTERNAL_STATE或提交确认丢失 | 不再次execute/capture；保留未知状态并查询/对账，不把未知当失败退款 |
| C11-A09 | capture已确认但订单投影失败 | 仅补投影；不再次扣款；供应商未确认不得变TICKETED；完成claim后精确重放 |
| C11-A10 | change首个commit后抛ValueError并被wrap转成HTTPException | 仍保留claim；证明异常类型变化没有抹掉副作用边界 |
| C11-A11 | change intent/auth持久化后失败 | 恢复同quote、同FLIGHT_CHANGE root、同固定授权key，不另建quote/intent |
| C11-A12 | change报价已经PENDING_SUPPLIER；重试或响应丢失 | 返回该报价原有pending状态，不重复authorization、不伪造出票 |
| C11-A13 | change授权已release，再进入恢复 | 不复活已release授权；不换新key；保留历史与重新报价要求 |
| C11-A14 | change供应商确认/拒绝后resolution本地提交失败 | 固定quote决议与资金回执对齐，capture/release各按合法分支最多一次；不得并存相互矛盾决议 |
| C11-A15 | 成功mutation之后resource_id提取或complete_idempotency失败 | 继承第一轮保护：claim保留，副作用不重复 |
| C11-A16 | 两个进程对同operation/key并发；另一个不同key指向同order/quote | 同key只有一个执行者；不同key仍由业务root/quote锁防重复；分别保存PostgreSQL证据，SQLite结果不能替代 |
| C11-A17 | 进程在首个commit前后、provider返回前后被终止并重启 | claim不丢；仅通过持久身份和已知事实恢复；无法还原请求的字段明确HOLD，不从hash推算 |
| C11-A18 | classifier/恢复查询自身异常或数据库不可用 | 保留claim、保留原始错误；不能把分类失败降为安全重试 |
| C11-A19 | Web/mobile同业务操作重放、其他owner复用key、修改amount/currency/quote | 精确payload与权限隔离；原结果不泄漏，金额/业务规则不被改写 |
| C11-A20 | 既有16项幂等回归 + 两个原post-commit red | 原16项保持；将原两个red的故障场景复制到两个启用新合同的operation并转green，保留原始red原件；未启用新合同的通用wrapper仍HOLD，不能宣称全局修复 |

C14审阅：可恢复身份绑定、异常分类传播、未扩大runtime topology/费用规则、旧接口
兼容性、未知结果fail-closed、每个资金键/锁的实现及并发证据。C13独立复核原始
日志与独立SQL，确认失败注入实际位于声称的提交边界，而非仅mock返回值。

其余35个调用点不能因为这两条优先路径通过而自动PASS。按CALLBACK_INVENTORY
逐条补适合本域的建单绑定、退款/额度恢复或状态重放证据；每项保留明确分母。
