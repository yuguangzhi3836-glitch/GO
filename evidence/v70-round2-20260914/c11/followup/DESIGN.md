# V70-R2-C11-02 — 可评审的最小修复设计

本次完成静态分类与修复设计，**没有修改冻结源码，也没有关闭原 C11 故障**。
37处调用已逐处分类（34个 operation、9个路由文件）；原两项故障注入仍是 FAIL。
审阅对象是从 `fef9c748adb77d37ba5d4dc4fa4662eb668303a1` 延续的冻结第二轮候选，
每个实际读到的文件由 `SOURCE_SHA256.json` 绑定，不把候选修复冒充原始 main 字节。

## 应先做的两个接点

| 接点 | 已经存在的持久事实 | 最小恢复方案 |
| --- | --- | --- |
| FLIGHT_CHECKOUT | order_id、FLIGHT_ORDER支付根、固定 checkout/auth/cap key | 绑定HTTP claim到order_id；出错后查同一支付根、付款尝试和资金回执；只恢复已知未完成步骤，核验金额/币种/付款人及capture后投影订单 |
| FLIGHT_EXECUTE_CHANGE | quote_id、冻结改签计划、AUTHORIZATION_PENDING、FLIGHT_CHANGE资金根、固定change-intent/auth/cap/release key | 绑定claim到quote_id；恢复同一改签报价与authorization；保留PENDING_SUPPLIER。最终capture/release继续由有供应商证据的既有resolution执行 |

这两个接点已有订单/报价身份，不需要为了本次修复创建新订单或重写费用规则。
`IdempotencyRow.resource_id` 已存在，可用于持久绑定。当前仓库没有
`bind_idempotency_resource` 或显式失败分类接口；下列均是待实现设计，不能当作现有功能。

## 1. 先保存可恢复身份

新增一个小型 repository 操作，暂名 `bind_idempotency_resource`：

1. 以 operation + key 锁定102状态的同一 claim，校验原 payload hash。
2. 在调用业务 callback 之前，将已知 order_id（checkout）或 quote_id（change）写入
   现有 resource_id 字段；已有不同绑定必须冲突，不能覆盖。
3. 绑定失败时禁止开始业务副作用；不得删除不能确认归属的 claim。
4. 恢复时，从持久 order/quote 与不可变计划读取 owner、amount、currency、operation
   事实。resource_id本身不授予权限，必须重核actor/owner与该claim请求的约束。

当前claim只保存请求hash，不保存完整请求。因此后台恢复不能从hash“还原”请求或
payment_method。能够从现有持久订单/计划证明的步骤才可恢复；缺少请求绑定事实的
情况保持HOLD，等待同一请求重放或补充受控持久上下文。不得写入原始付款token。

## 2. 显式表示失败发生的边界

只给上述两个operation启用新的内部 outcome policy；其他35处先保留已分类的
待办和风险，不在同一个补丁内更改全部异常语义。

建议由callback的内部执行上下文记录以下结果。它不能来自HTTP请求、不能仅按
异常类型推断，也不允许调用者用一个布尔参数声明“安全”。

| 分类 | 必须成立的事实 | claim处理 |
| --- | --- | --- |
| PROVEN_NO_EFFECT | 校验在任何业务写入/外部调用前失败，或全部本地写入已确认回滚；同一已绑定资源没有本次或先前已开始的对应操作 | 释放，保留原先安全校验失败可以重试的行为 |
| RESULT_UNKNOWN | 已进入可能提交的事务、调用过外部执行器、提交确认丢失，或任一事实不确定 | 保留102+resource_id；拒绝同key第二次mutation，进入恢复 |
| EFFECT_COMMITTED | 原操作/回执已存在，而后续投影、审计或响应失败 | 保留claim；用原记录补齐投影/结果，成功后complete，不重新执行原副作用 |
| COMPLETED | 已核验完整业务结果和原请求身份 | 原子记录可重放响应；随后同key返回相同结果 |

在第一次可能的提交或外部操作**之前**进入RESULT_UNKNOWN；只有明确证明没有
产生任何相应副作用时才降为PROVEN_NO_EFFECT。这样进程中断或finally失败不会
把结果不明的操作降为安全重试。保留原始异常与原因链。

HTTP `wrap()` 把ValueError转换成HTTPException时，不得丢弃执行上下文。特别是
`FLIGHT_CHANGE_AUTHORIZATION_RELEASED_REQUOTE_REQUIRED` 出现在首个commit及
adjustment检查之后；它不是“校验异常所以无副作用”的证据。

## 3. 最小恢复动作和禁区

**Checkout**：先核对付款人、订单金额/币种、payment intent状态及已确认的auth/cap。
有UNKNOWN_EXTERNAL_STATE时查询和对账；不能直接execute。存在一笔合法capture时
只补齐同订单状态、证据和HTTP完成记录。供应商未确认则保持等待供应商，不能凭
付款成功把订单写成TICKETED。

**Change**：从同quote读取冻结计划、同FLIGHT_CHANGE根和authorization；校验
amount/currency/owner与plan一致。AUTHORIZATION_PENDING可以在已知状态恢复到
PENDING_SUPPLIER；已经pending的请求只返回已有状态。已release的authorization
返回原确定结果/重新报价要求，保留原历史，不创建替代授权。供应商确认或拒绝
仍由既有`flight_change_resolution.reconcile`核验后capture/release。

**补偿**：网络或响应错误本身不构成退款、取消、释放库存或释放授权的理由。
只使用既有、已证明的失败/供应商决议对应的恢复接点。错误修复不改变任何退改
费用、365天期限、较低差价不退或库存唯一真源规则。

## 4. 其余调用如何接续

- FLIGHT/RIDE/RENTAL/HOTEL建单：随机新order_id与HTTP claim没有原子绑定，必须先
  解决生成身份与creation操作绑定。按相似用户/时间/金额搜索不能代替唯一键。
- RAIL/ATTRACTION建单：已存在consumed prebook→order映射；优先复用该映射并补齐
  晚到的source/evidence。vault release本身也可能已提交，不应重复披露。
- 退款、现金退改、StayCredit：已有冻结操作、报价、资金分配或租约；恢复原操作，
  不换quote、refund key、allocation或payment root。
- 单事务状态迁移：回滚已确认才安全释放；提交确认丢失仍需根据原事件/动作身份
  证明已完成。单看“当前状态已经改变”不足以证明对应本次请求。
- supplier_unable_to_fulfill：登记case已持久化后审计可能失败。补审计，不执行
  原请求未授权的赔付或退款。

建议实施顺序：本设计两条flight路径 → 建单身份绑定 → 复用已有退款/额度恢复 →
单事务状态变更的精确重放。当前37处分类完成度37/37；运行修复完成度仍为0/37。
两条优先路径只有代码、故障注入、C14和独立C13证据齐备后才能关闭。
