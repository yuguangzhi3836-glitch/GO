# GO 本地后端与 Android 测试 APK

> 本文说明本机 Docker Desktop / WSL2 后端、消费者注册联调和测试 APK 分发。它不授权或描述 HK-STAGING / Production 部署；远程环境按仓库根目录 `AGENTS.md` 的 GO Forge 流程处理。

## 1. 本机启动后端

前提：Windows 已安装 Docker Desktop，启用 WSL2 Engine，并且 Docker Engine 已启动。仓库根目录运行：

```powershell
.\application\scripts\start-local-wsl-backend.cmd
```

脚本会使用 `application/docker-compose.staging.yml` 加 `application/docker-compose.local.yml`，以 `go-hotel-staging` 为本机 Compose project，构建并启动本地 API、数据库、Redis、迁移和业务 worker；随后轮询 `http://127.0.0.1:8000/health` 并显示容器状态。`docker-compose.local.yml` 将应用环境切换到 `local`，并关闭本机管理端 MFA 要求。此脚本仅用于本机 Docker Desktop，不要在远程预发或生产主机上运行。

启动后检查：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
docker compose --project-name go-hotel-staging --file application/docker-compose.staging.yml --file application/docker-compose.local.yml ps
```

查看 API 日志：

```powershell
docker compose --project-name go-hotel-staging --file application/docker-compose.staging.yml --file application/docker-compose.local.yml logs --follow --tail 200 api
```

停止本机 Compose 服务但保留数据库卷：

```powershell
docker compose --project-name go-hotel-staging --file application/docker-compose.staging.yml --file application/docker-compose.local.yml down
```

不要给 `down` 添加 `--volumes` / `-v`，否则会删除本机 Compose 数据卷。

## 2. 消费者注册流程

APK 注册页在进入注册模式时，从后端读取 `GET /v1/consumer/auth/registration`。它使用该接口返回的 `versions` 和 `term_hashes`，展示条款文档；当前策略将 `personal_vault_terms` 列在 `deferred` 中，注册不会启用个人信息库。

用户勾选同意后，APK 调用 `POST /v1/registration/challenges` 请求邮件验证码。此操作会给输入的邮箱发送验证码，所以只有用户点击“发送邮箱验证码”时才会发生。注册提交 `challenge_id`、六位 `verification_code`、策略版本/哈希和逐项决定，再调用 `POST /v1/consumer/auth/register`。当前策略映射为：

| 条款 | 注册决定 |
|---|---|
| `consumer_service_terms` | `CONTRACT_ACCEPTED` |
| `privacy_policy` | `NOTICE_ACKNOWLEDGED` |
| 延期的 `personal_vault_terms` | `DEFERRED` |

服务端每次注册都会校验验证码，不能只在 APK 中隐藏验证码步骤来跳过验证。策略版本可能变化，客户端不再固定写入条款版本。

预发接口当前把账号注册阶段标记为可接受，但条款状态返回 `DRAFT` 且 `formal_approval_pending=true`。测试 APK 会向用户显示这一状态；这不表示条款已获正式审批。

## 3. 构建给测试者安装的 APK

APK 在构建时写入 API 地址。默认值是 `https://staging-api.goaidirect.com`；运行安装程序或安装 APK 的人不用输入网址。要创建可分享文件，在仓库根目录运行：

```powershell
.\application\mobile\go-app\scripts\build-install-android.cmd -NoInstall -OutputPath .\application\mobile\go-app\artifacts\GO-consumer-staging.apk
```

`-NoInstall` 表示只构建，不要求手机、ADB 或 USB 设备。脚本会生成 Debug APK，确认 APK 内含 `assets/index.android.bundle`，复制到指定路径，并打印文件大小和 SHA-256。产物位于：

```text
application/mobile/go-app/artifacts/GO-consumer-staging.apk
```

也可以显式指定 API 地址：

```powershell
.\application\mobile\go-app\scripts\build-install-android.cmd -ApiBaseUrl https://staging-api.goaidirect.com -NoInstall -OutputPath .\application\mobile\go-app\artifacts\GO-consumer-staging.apk
```

本机手机连接本地 WSL 模拟后端时，显式覆盖为本机地址并安装启动：

```powershell
.\application\mobile\go-app\scripts\build-install-android.cmd -ApiBaseUrl http://127.0.0.1:8000 -Launch
```

脚本会为 USB 连接的 Android 设备转发本机 API 端口。用这个本机地址构建的 APK 不要发给其他人：接收者手机上的 `127.0.0.1` 指向接收者自己的手机。

## 4. 接收者如何安装

把 `GO-consumer-staging.apk` 发送给测试者。对方在 Android 手机上打开文件并安装；如果系统提示，允许当前文件管理器或浏览器“安装未知应用”。随后联网即可访问 APK 中预先配置的预发 API。安装过程不需要填写 API 地址、ADB serial、Metro 地址或构建参数。

测试注册时，测试者需要能读取注册邮箱验证码。分享 APK 不会把验证码、账号或密码写入 APK。

当前脚本产出的是使用仓库 Debug 签名配置签名的测试 APK，适合开发/封闭测试安装，不是应用商店发布包。Android `release` build type 目前也指向 Debug 签名配置；正式发布前需要单独配置受控的 release 签名和版本号。不同签名的同包名 APK 不能直接覆盖安装。

## 5. 脚本参数

| 参数 | 用途 |
|---|---|
| `-ApiBaseUrl <url>` | 覆盖默认预发 API；本机联调使用 `http://127.0.0.1:8000`。 |
| `-NoInstall` | 只构建 APK，不要求连接手机。 |
| `-OutputPath <file.apk>` | 将 APK 复制到指定 `.apk` 文件，并输出 SHA-256。 |
| `-DeviceSerial <serial>` | 多台 ADB 设备连接时指定安装目标。 |
| `-Launch` | 安装后启动应用；loopback API 会配置 ADB 端口转发。 |
| `-Logcat` / `-LogcatSeconds <10–3600>` | 安装启动后采集 Android 日志。 |

APK 已包含 JS bundle，正常安装和启动不依赖 Metro。分享前不要将含有个人资料、验证码、令牌或其他敏感内容的 logcat 文件一并发送。
