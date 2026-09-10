# DEPTH37：外部验收输入与关闭条件

本次开发、构建修复和隔离验收由 GO Command Center 负责。香港负责已批准产物的服务器部署；本记录没有发出部署任务。

## 供应商真实认证

当前可用环境缺少以下输入。隔离 CI 运行 34478027432 也已按既定 Secrets 名称进行预检，八项均为空；该运行没有选择部署 Environment，因此此结论不涉及仅存放在特定 Environment 中的配置。输入预检只记录名称和错误代码，不记录凭据值，也不会发出网络请求。当前 GitHub 接口不提供 Secrets 读取能力，不能据此推断私有仓库中一定没有这些凭据。

| 用途 | 输入名称 |
| --- | --- |
| Stripe 测试模式凭据 | `STRIPE_TEST_SECRET_KEY` |
| SiteMinder 已确认的测试环境地址 | `SITEMINDER_CHANNELS_PLUS_BASE_URL` |
| SiteMinder 测试身份 | `SITEMINDER_CHANNELS_PLUS_API_ID`、`SITEMINDER_CHANNELS_PLUS_API_KEY` |
| 测试库存查询条件 | `SITEMINDER_CERT_PROPERTIES_QUERY_JSON` |
| 可用于认证的测试酒店 | `SITEMINDER_CERT_PROPERTY_UUID` |
| 供应商认可的锁定、确认请求样本 | `SITEMINDER_CERT_LOCK_BODY_JSON`、`SITEMINDER_CERT_CONFIRM_BODY_JSON` |

凭据应通过受控测试环境注入，不写入源码、报告或聊天。地址、账号和测试库存须有供应商沙箱依据；HTTPS 或名称校验不能证明它是真实沙箱。

输入就绪后，先执行 `scripts/provider_certification_preflight.py --evidence <output>`。其 `INPUTS_READY_NOT_CERTIFIED` 只表示输入结构可用。真实认证需执行既有命名供应商流程并取得外部引用、请求/响应指纹和实际结果；回调、结算、银行及 PostgreSQL 证明仍按原规则单列。

27 项适配器合约检查和新增输入校验测试属于本地/隔离验证，不能作为供应商认证回执。

## 原生设备与发布配置

隔离构建使用开发 API 配置。生成 APK 或模拟器应用不意味着已经连接部署后的服务，也不是应用商店发布包。

物理设备验收仍需要 Android/iOS 设备、可访问的测试 API、测试账号，以及适用于该设备的安装或签名环境。原生验收应保存产物指纹、设备型号与系统版本、安装/启动结果、权限结果、深链与通知结果、崩溃日志及网络/会话检查证据。缺少这些实际结果时保持 `NOT_RUN`。

对外 staging/production 构建必须显式提供 `EXPO_PUBLIC_API_URL`（兼容别名 `EXPO_PUBLIC_API_BASE_URL`），使用可部署 HTTPS 地址。保留现有 `EXPO_PUBLIC_ENV`、`EXPO_PUBLIC_EAS_PROJECT_ID`、`IOS_BUILD_NUMBER`、`ANDROID_VERSION_CODE` 入口。EAS/App Store 的项目及账号占位符必须由相应已授权配置替换后才能执行对应发布流程；本次未提交应用商店。

## 用户已决定的验收阶段

消费者、供应商、管理员的真实浏览器操作，以及六品类真实操作闭环，保留为部署后验证：不阻塞部署前检查，未标记为通过，仍阻塞正式业务验收关闭。该决定不自动延期物理设备或供应商认证。
