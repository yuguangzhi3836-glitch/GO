# 已有酒店内容批准权限风险：只读定位

状态：SOURCE_CONFIRMED_CONTROL_GAP；尚未执行HTTP复现，不声明已发生真实越权操作。

调用链：

- application/src/go_hotel/api/routes/hosted_direct_booking.py:71 POST /internal/v1/hosted-direct/content-snapshots/{snapshot_id}/approve 使用 Depends(admin_principal)，将p.user_id传给service。
- application/src/go_hotel/security/deps.py:35 admin_principal确实先通过current_principal/authenticate验证真实登录会话，再要求actor_type==GO_ADMIN；没有检查admin:approve、admin:rules或酒店归属。
- application/src/go_hotel/security/rbac.py 中 GO_READ_ONLY 只有admin:read。
- application/src/go_hotel/services/hosted_content_acceptance.py:approve 只要求body.approver_role=='HOTEL_AUTHORIZED_OPERATOR'、decision在APPROVE/REJECT、evidence_reference非空及snapshot存在，然后写入审批行；没有核验该actor实际酒店授权关系。
- main.py:Sprint1USecurityMiddleware提供cookie CSRF/session校验，不补充此路由的审批权限判断。

结论必须精确：这是“已认证GO_ADMIN细分权限和酒店授权绑定缺失”的风险，不是匿名接口、消费者可直接批准或已证明真实供应商被篡改。字符串角色不能作为下一批容量政策的批准依据。

最小无业务写的隔离HTTP验证设计：

1. 使用测试身份服务创建GO_READ_ONLY管理员并真实登录获得测试token；只使用隔离数据库/fixture，不读取真实凭据。
2. 带该token对上面approve路由发送一个保证不存在的snapshot_id，body={approver_role:'HOTEL_AUTHORIZED_OPERATOR',decision:'APPROVE',evidence_reference:'isolated://negative-probe'}。
3. 权限正确实现应在对象查找前返回403。当前源码预计409 CONTENT_SNAPSHOT_NOT_FOUND，表示readonly已穿过权限门到达审批service。assert数据库approval行前后不变；该请求不可能创建审批行。
4. 匿名401、消费者/供应商403作为对照。若需证明存在对象的写风险，只能进一步在隔离fixture已有snapshot上运行并事务回滚，禁止对真实环境尝试。

下一批最小修复顺序：路由明确审批权限→服务复核已认证actor/当前权限→验证server-held酒店授权关系与snapshot对象所属权→审批内容版本绑定与审计→容量政策消费。权限字符串、任意evidence URL或自报HOTEL_AUTHORIZED_OPERATOR都不能替代前两项。修复前该批准链不可被新容量功能当权威源。
