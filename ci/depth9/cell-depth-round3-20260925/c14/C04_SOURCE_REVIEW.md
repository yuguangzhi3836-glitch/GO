# C04 Round3 限定规则源审

冻结文件全部SHA256匹配。限定隔离增量未发现新增规则阻断；此意见不授完整验收项PASS。

- statement_evidence由认证路由主体构造，actor/order/case/action/text共同hash且标ACTOR_STATEMENT_UNVERIFIED；没有伪造照片或供应商认证。
- 证据嵌入原damage/return domain事务；角色、expected_version、原幂等检查沿用，拒绝请求不先另写成功statement。
- 客户回应仍交独立裁决；owner/claim maker和原裁决者独立限制通过原服务执行。return-review只建立释放依据，不执行C11钱。
- widget要求明确确认，保留同actor/同订单pending key/body；请求返回后读取当前receipt，旧幂等结果不冒充当前状态。
- UI明示申诉不会自动撤销已有资金记录，陈述非验车认证，资金状态仍归C11。

限制：

- 7文件hash全部匹配；业务adapter/源码及测试case已阅读，未由C14运行测试。
- 浏览器脚本仅冻结文件身份，不能将其存在或adapter单测算作真实浏览器PASS。
- 撤销/已接受来源更正、重开、已结算申诉补偿等仍是未完成内部义务；真实证据/合同与部署维持HOLD。
- 非完整原子清单PASS、非正式C14组织运行/法律认证/部署许可；候选身份待最终绑定。
