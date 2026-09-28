# Round4 C11 限定实现

基线 PR246 cb8928f2ce915825f7c95321a0fc26ed0b5530e6。
本批实现 C11-21/C04-22 内已结算租车押金独立申诉降额/撤销补偿，沿原 RENTAL_DEPOSIT 钱根、原 CAPTURE 父项追加 COMPENSATION 与反向双分录。C04 提供最新独立受权决定及历史决定 lineage；C11 服务端计算差额。连续减收只补净额差，零差额只读 no-op；新目标高于当前净收 HOLD，不新增扣款。原 capture/release 不变，补偿不会恢复授权余额。

UNKNOWN 成功恢复本批不实现：现隔离 writer 原子同步产生 CONFIRMED，无独立持久化模拟收据可证明未知操作。缺可信收据、坏根/绑定/parent/ledger继续 HOLD，管理员无手填成功通道，不伪造 PSP。C11-07/08 全义务继续未完成。

只读兼容的 legacy BUSINESS:RENTAL_DEPOSIT 完整旧账户码不直接补偿，避免新 RD 账户反冲错位；旧账需要另行受权处理，保持历史未改。

测试义务：授权角色、当前来源版本、pending申诉、降额与全撤销、零差额、累计差额、上调HOLD、同键并发幂等、事务失败回滚、原资金图/分录不变、未知/腐败拒绝、legacy账户HOLD、界面明确确认与服务端读回。C13独立审核及PG/真实API点击是额外必要证据。
