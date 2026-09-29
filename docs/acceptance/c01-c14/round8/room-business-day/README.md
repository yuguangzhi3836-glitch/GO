# 接外部支付前：房池与完整营业日修复

产品提交 d838f05d0d180a621f8e4cbd7b23074c9cd71e4d；application tree 8a5b54d10a7df6b8ca04d27076b80a3f2ea09024；1552 文件，SHA256 30b78e8f1f8020388103a494e06a698d5fce69f5f0366cf9964fe6b89fe73511。

当前结论：PENDING_CURRENT_CANDIDATE_CI_AND_FULL_SCOPE_REVIEW。不得以局部PASS称全范围100%。

- 物理房号必须登记、属于本酒店及订单房池、ACTIVE；入住重验，规范化同房号防重复占用。
- 合成登记仅工程授权root、SIMULATION酒店、isolated://来源；版本CAS、同酒店行锁、审计原子写入；不能签发真实酒店确认。
- 旧SQLAlchemy identity-map缓存缺陷已修；保留独立失败记录，等待实际PG同version并发检查。
- 50房池先由49个实际订单消耗，再两个餐别竞争最后一间；20项独立营业日原断言从旧硬编码路径重绑当前源码。
- 本地86项回归全PASS；C13自编7项权限/在住保护HTTP全PASS。CI新增独立PG18.4 job执行93项，不挤占原C11过程恢复任务；所有旧门禁保留。

测试数据不代表敖麓谷雅真实确认库存/房号/价格。外部支付、真实资金、供应商写入、部署、合并均未执行。真实验证仍须余总单独授权。
