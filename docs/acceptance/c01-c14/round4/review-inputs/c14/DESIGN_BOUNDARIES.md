# Round4 已结算租车申诉减收补偿：规则边界

基线cb8928f。设计方向可继续隔离实现；本文件不授新源码PASS、真实收费/法律批准或部署许可。以下为既有义务的本次验证场景，不改冻结305项/1009case分母。

- **R4-01 当前独立申诉决定来源**：C04返回原义务/合同hash、owner、case最新version/decision hash、独立reviewer、目标保留额及isolated来源；旧/held/无历史lineage拒绝。
- **R4-02 非客户端金额授权**：C11以当前C04决定与原root/capture决定差额；客户端只能传引用版本/摘要，无金额、payee、币种覆盖。
- **R4-03 仅减收不追收**：目标高于当前净收HOLD；等于净收返回只读no-op，不建零movement；更高决定不得回收已返补偿或新扣款。
- **R4-04 净收预算**：净收=原已确认capture−该capture已确认refund/compensation；多个申诉按当前净额，不能按原capture重复退。
- **R4-05 原资金图不改**：追加COMPENSATION/REFUND引用原capture并归同deposit root；原capture/release及accepted合同不改。
- **R4-06 账项严格反向**：新增反向分录对应原capture账户、币种和方向并同事务；legacy完整BUSINESS账户需匹配原账冲销，或受权治理前明确HOLD，不能误用RD账户冒充冲销。
- **R4-07 授权余额不复活**：补偿不增加remaining authorization；展示原扣款、累计补偿、净收、已释放分别计算，不让退款再次可扣。
- **R4-08 UNKNOWN不造可信回执**：存在未确认movement、独立receipt缺失、orphan或账图损坏时HOLD；新补偿不是修复原UNKNOWN的手段。
- **R4-09 当前版本和并发**：同order锁下重验source/case/graph；review→execute变更拒绝；同决定重复仅一次资金，旧决定不能在新申诉后补执行。
- **R4-10 幂等不冲淡权限**：相同业务决定key绑定原capture+case/version/hash；不同参数冲突。Generic money入口仍须本域verified scope，不凭幂等历史绕过新动作许可。
- **R4-11 原子恢复**：money movement/反向ledger/决定执行绑定同事务；故障/重启不留半确认或重复补偿。PG约束与锁需真实隔离PG举证。
- **R4-12 可用界面真实状态**：有权admin显式确认服务端只读差额，owner读真实money结果；丢回执先权威读回，未知不报已退，补偿完成不自动声称真实银行到账。
- **R4-13 独立权限维持**：供应商/owner/原裁决者不能自行产生所需独立申诉批准；C14/C13意见与admin按钮不替代来源及资金执行授权。
- **R4-14 既有来源过期处理**：已确认原capture的减收返还可以按明确安全释放规则处理已过期fixture，但不得因此允许新授权/正向扣款/复活撤销来源；历史合同绑定完整保留。

已把上述约束发送C04/C11。其中旧完整BUSINESS账户与新RD账户的反向一致性是当前源码发现的具体兼容风险。等待冻结代码后独立检查，不以通用资金服务已有COMPENSATION能力代替本域授权与恢复证明。
