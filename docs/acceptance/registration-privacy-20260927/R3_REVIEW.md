# R3 集成与权限整改

## 范围与分类

本轮合并 #273 的完整注册/手机端候选 a2f1f5e58ab0cf44affe5441ddd430ce64a182ed 与集成分支 95c1c56e5ab92947ecd38366d9930ddcb14ac56f，共同基线为 1960b51e86acefa45d0eacfce22e2b6a6245adcf。历史 CI/C14 不向新树转移；等待新固定候选的独立复审。

适用分类：PRODUCT_FIX、PRODUCT_FEATURE、MIGRATION、BUILD、INFRASTRUCTURE、TEST_ONLY、DOCUMENTATION。

- BUILD：新增/调整隔离 CI 工作流、依赖安装、固定源码检出及证据打包。
- INFRASTRUCTURE：条款目录/版本、SMTP 凭据引用、验证密钥和只读隐私证据文件的配置契约，以及现有 reconciliation worker 的清理职责。未改变线上配置。
- MIGRATION：0142/0143 候选迁移，未在香港执行。
- TEST_ONLY 仅描述合成数据与验收脚本，不表示产品改动是测试专用。
- TOPOLOGY 不适用：没有增删服务角色、镜像族或保护对象，清理复用既有 reconciliation worker。
- CONTROL_PLANE 不适用：没有修改指挥中心、Task/Evidence、签名和执行授权。

## 集成处理

三方合并覆盖集成分支 18 个代码/测试/工作流文件，保留其其他文档与历史证据 Git blob。两个文件存在等价实现冲突：

1. dashboard.py：保留严格 SupplierVertical 枚举筛选，同时保留景点 CONFIRMED/CLOSED_BY_SUPPLIER 回执及 voucher_code。
2. transaction_order_view.py：保留 UNSUPPORTED_VERTICAL 拒绝和 SQL 品类过滤；完整保留六品类订单与退款的租户隔离。

其余自动合并包括景点正常运营/凭证可见性、嵌套同意界面、供应商筛选及对应回归。无整文件选边覆盖。新提交保留两边为 Git 父提交，GitHub 可验证与集成分支的合并关系；最终是否可合并须读回。

## IAM-001 可执行证据

权威源码为 application/src/go_hotel/security/rbac.py 的 PERMISSIONS：只有 GO_TRUST 和 GO_GOVERNANCE 具有 admin:trust。registration_privacy.privacy_operator 先通过 admin_principal 要求 GO_ADMIN，再检查 admin:trust。身份和权限来自 IdentityService.authenticate 查询的现有数据库用户/会话，不接受请求 body 中的角色。

新增 tests/test_registration_privacy_admin.py 使用实际数据库用户、会话与 JWT，通过完整 HTTP 路由验证：

- 所有其他管理角色，以及所有供应商角色和消费者，不能读取队列或处理请求；即使错误配置供应商/消费者拥有 GO_TRUST/GO_GOVERNANCE 角色，仍被 actor_type 边界拒绝。
- GO_TRUST 与 GO_GOVERNANCE 可受理、审核和登记结果；状态前置、证据必填、拒绝理由、受限保留范围/复核日、重复完成拒绝均验证。
- 用户只能看到自己的申请及结果；管理审计保留操作者、角色、前后状态及证据引用。
- 降级角色即时生效；撤销会话拒绝；cookie 写入要求当前会话 CSRF；审计插入失败时业务状态原子回滚。

这些证明源码权限边界，不证明线上账号分配、值守或真实请求已完成。登记 COMPLETED 仍不是下游删除证明。

## 已找回事实与不能推断的事实

沿用已确认名称“构行人工智能（黑龙江）有限公司”和邮箱 postmaster@goaidirect.com。2026-08-10 用户历史确认注册地址为“黑龙江省哈尔滨市松北区创新三路788号”；这次检索找回了该确认，但没有获得受控原始企业资料文件。

历史检索中的信用代码归属存在冲突：同一值同时被旧助手记录关联到 GO 主体和“一研一号”。未取到原始执照，不把它同步为 GO 的信用代码。原始章程/执照的文件检索未获得匹配文件。现有 sync_registration_profile.py 继续要求完整受控源并阻止猜填。

9月19日用户交接的邮件配置及真实收件成功记录保留为发信可用性来源；它没有说明 SMTP 处理者合同、日志保留、存储地区或隐私请求收件值守，因此不将这些项目设为已验证。

## 未解决的正式证据

以下均为待取得的事实，不是要求重新配置原有系统：

| C14 项 | 需要读回的已有记录/决定 | 当前状态 |
| --- | --- | --- |
| REG-001 | GO 受控企业资料/执照；有效协议及隐私正文、版本摘要和批准记录；SMTP/云/日志/备份/运维地区与角色、合同及跨境判断 | 名称、邮箱、地址已有来源；信用代码原始归属和其余材料未取得 |
| REG-002 | 隐私邮箱收件与值守、受理责任分配、身份核验程序；跨表/供应商访问、更正、删除、注销和受限保留处置凭证 | API/权限/审计已测；现场与下游完成证据未取得 |
| REG-003 | 运营批准的分类期限、实际日志/SMTP/备份设置、删除核验、告警接收、恢复删除清单重放记录 | 源码定期清理已测；外部与现场记录未取得 |
| REG-004 | 独立账号注册年龄范围的业务决定与相应正式条款；支持未满14岁时的监护人机制 | 未找到既有决定，本轮不代替负责人决定，也不声称已实现监护人机制 |

建议提交材料使用受控文件引用、摘要和脱敏配置，只需现有材料位置，不上传密码、SMTP凭据、个人信息样本或签名私钥。C14 仍应依据缺口作真实结论，不得因本轮权限测试通过就关闭其他事项。

## 顺序

新固定候选 → 隔离 CI → C14；仅新候选 C14 PASS 后执行 C13。无合并、部署、真实邮件发送或生产注册开放。
