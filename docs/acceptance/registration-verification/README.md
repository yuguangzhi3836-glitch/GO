# 注册资料同步与邮箱验证候选（2026-09-27）

## 用户要求与范围

沿用已有企业资料、`postmaster@goaidirect.com` 发信配置，补齐资料同步与注册验证程序。基于 #267 固定 `679f56e71d9aa5d7cb9205eb55bd1a277225c21e`；单独 Draft，#267 不改写。不合并、不部署、不发真实邮件、不读取现场密码。

变更分类：PRODUCT_FIX、PRODUCT_FEATURE、MIGRATION、TEST_ONLY、DOCUMENTATION。没有服务拓扑、签名/执行权限、真实支付或供应商连接变更。

## 完成的程序

- C/B 注册共用 `/v1/registration/challenges`：已生效条款及明确同意后才发验证码；邮件只用于此次验证。
- 消费者和供应商注册均要求挑战 ID 与 6 位验证码。绑定规范化邮箱、consumer/supplier 用途及条款版本/正文摘要；10分钟有效，最多5次错误尝试，重发替换旧挑战。
- 仅保存服务端 HMAC 摘要；验证码与地址不进入业务数据库、日志、错误响应；既有账号审计保留验证挑战 ID 与 email_verified。
- 验证码消费、账号和同意审计在同一事务中提交；失败回滚；并发消费只成功一次。数据库持久限流：邮箱每60秒一次、每小时5次；网络来源每小时20次、全局每小时500次。网络来源为应用看到的 transport peer；需按现有代理信任配置验证，不能凭客户端任意 X-Forwarded-For 扩大额度。
- C/B 页面增加获取验证码、发送中、重发倒计时、错误提示；改邮箱使旧挑战失效，异步返回不能覆盖新邮箱。SMTP失败不会生成可用挑战。
- 新增 migration 0142，两张表；有数据时拒绝降级。过期 rate 在下次发送清理；到期超过24小时的 challenge 在下次发送清理，永久审计只保存关联ID。低流量时该清理是惰性的，不是硬删除SLA。

## 沿用现场配置的适配契约

已知交接：2026-09-19 邮件账号已安全配置，真实发送和收件测试通过。没有重新要求采购邮件服务；没有在此次工作中重复证明现场现状。

程序不假设此前根目录中的秘密文件可被业务容器直接访问。由现有运维配置提供只读映射：

- `REGISTRATION_EMAIL_CONFIG_PATH`：非秘密邮件描述文件，内容字段 `sender`（固定 postmaster@goaidirect.com）、`credential_reference`（固定 hk-staging-registration-email）、`host`、整数 `port`、`tls`（SSL/STARTTLS）、`username`、`password_file`。
- `password_file` 指向同一现有凭据的只读秘密挂载；不复制到 GitHub，不通过API传递，不记录内容。描述文件与挂载由既有配置管理控制，客户端不能指定。
- `REGISTRATION_VERIFICATION_ENABLED` 保留环境开关。仅开开关不足以启用：描述文件、密钥引用、TLS、秘密可读、现有 JWT key 非开发值且不少于32字符均需满足。
- `REGISTRATION_TERMS_VERSION` 选择版本化条款包，缺省仍是现有草稿。哈希、批准记录、企业事实、收件验证与生效时间均合格后，C/B readiness 每次请求自动计算，页面重新读取规则即可开放，无需在前端另改开关。

“配置可读”不是实时送达证明；SMTP接收也不等于用户收件。每位用户持有验证码的成功注册才完成其邮箱验证。首次正式环境接入仍需使用现有账号完成真实端到端验证。

## 企业资料同步

`scripts/sync_registration_profile.py` 从已有、非秘密企业资料JSON生成一个新的可审核草稿包。输入字段：`legal_name`、`registration_address`、`unified_social_credit_code`、`privacy_email`、`source_reference`；可附 `delivery_evidence_ref` 与 `handling_evidence_ref`。检查已确认公司/邮箱一致、统一社会信用代码格式和校验位。拒绝密码等无关字段、现有输出目录、路径穿越和源正文篡改。

已确认主体：构行人工智能（黑龙江）有限公司。地址和信用代码原始值尚未在本次可访问材料中找回；不能把 registry 空值解释成用户未提供。本次没有猜填、没有把邮件发送成功等同于隐私申请处理流程已核验、没有伪造条款批准。同步工具清除已落实的缺项，保留尚未落实的审核项；任何内容变化都产生新摘要并清空旧批准。

同步后仍需按既有审核流程确认条款。工具输出不是法律审核结论，更不会写 live 配置。

## 验收与未完成现场项

PostgreSQL CI 修复：`fcc7faae` 的手机旅程通过，但注册、票务和租车/景点工作流中的5个任务失败；回溯定位到验证码 upsert 后依赖 INSERT rowcount，导致有效请求误报限流。改为 `RETURNING challenge_id` 验证实际写入结果，保留条件更新与事务；本地17项验证码测试通过（`upsert-junit.xml`），PostgreSQL 修复效果以新 head CI 为准，不能用 SQLite 结果替代。

2026-09-27 追加整合前修复：旧 `PUT /v1/supplier/go-identity/programs/{program_type}` 现在与批量配置入口一致要求 `supplier:fare-rules`，关闭独立预检复现的 READ_ONLY 写入漏洞。真实登录与 CSRF 回归覆盖只读拒绝且无写入、有权限供应商正常保存；手机业务与权益服务合计18项本地通过，证据为 `permissions-junit.xml`。此追加修复在 #268 中，#267 固定提交未改变；不是正式 C13 通过结论。

本地隔离 SQLite/API：74项通过；Node逻辑31项通过。覆盖邮箱/用途/条款绑定、错码锁定、重放、过期、重发、并发发送/消费、限流、账号失败回滚、C/B租户边界、既有秘密适配/TLS、草稿阻断、资料同步与迁移降级保护。

新增 GitHub 隔离 PostgreSQL 18.4 验证工作流；部分继承夹具明确使用 SQLite。既有 mobile 工作流增加消费者和供应商验证码注册的 Chromium/WebKit 手机尺寸旅程，邮件由隔离进程写入本机临时测试邮箱文件，绝不向真实邮箱发送；不等于现场或真机验收。

待现场事实接入：已有企业资料非秘密原件的定位/同步、已有 SMTP 描述与只读秘密映射、经批准生效的条款版本、迁移0142、正式 C14/C13 和部署流程、真实手机与邮件收发端到端验收。此候选不解除这些状态，不声称正式注册已开放。
