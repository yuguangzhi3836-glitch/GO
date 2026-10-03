# GO FULL AUDIT — EVIDENCE PACKAGE

**Date**: 2026-10-03
**Mode**: READ ONLY。本目录只含审计过程产物，**不含任何产品源码改动**。

## Baseline（本包所依据的审计基线）

| Item | Value |
|---|---|
| GitHub main | `7e7aedd556eac986210f1a5474c7b31e04d37a29` |
| HK runtime image | `sha256:01632507d0d3b60054c1d9e56c5338b51085a69094b9beb4773e330c21191754`（= `go-hk-test-pr:9f889acfcd36a82c7565b723261ee046c2615314`，PR #376 head） |
| HK services | 8/8 业务服务同一镜像 |
| HK alembic | `0145_source_latest_index (head)` |
| HK public tables | 564 |
| HK OpenAPI | 1065 paths / 1101 ops |

## 内容

| 文件 | 是什么 | 支撑报告里的哪些数字 |
|---|---|---|
| `api_routes.json` | 1082 条路由声明：method / path / 鉴权依赖集合 / 源文件 / router 变量 | 1082、`/internal/*`=710（65.6%）、`admin_principal`=558（51.6%）、写 742 / 读 340、66 条无显式依赖、治理族 union 305 |
| `db_tables.json` | 563 个 model class → table 名 + 应用引用数 / service 引用 / route 引用 / worker 引用 / 测试引用 | 563 models、564 tables、560 应用引用、1 TEST_ONLY、2 ORPHAN |
| `surface-results.json` | 4 个现场 surface 的浏览器渲染结果（标题 / h1 / 可见文案 / 按钮 / 输入 / 滚动高 / 横向溢出 / 请求状态 / 控制台错误） | C 端与运营端现场行为、`/`=404、`/go-app/` 与 `/go-admin/` 内容 |
| `unauth_raw.json` | 66 条无显式鉴权路由的原始列表（method / path / 源文件 / handler 签名） | 66 条原始枚举 |
| `unauth_signals.json` | 对上述 66 条逐个扫描 **handler 函数体内**鉴权信号的中间结果（用于区分"没写依赖"与"写了但写法不同"） | `AUTH_ENFORCED_IN_BODY`=2、`MACHINE_AUTH_IMPLEMENTED`=5 的判定依据 |
| `shots/` | 现场截图（root-404 / consumer-desktop / consumer-mobile / admin-desktop，各含 fullPage） | C 端与运营端外观、无统一前门 |
| `inv_api2.py` | 路由枚举脚本（三处鉴权来源合并） | 复核 1082 / 依赖统计 |
| `inv_db.py` | model→table 引用分析脚本 | 复核 563 / 560 / 1 / 2 |
| `surf.mjs` | 现场浏览器探针脚本（playwright-core + 系统 Chrome） | 复核 `surface-results.json` |
| `classify.py` | 66 条路由提取脚本 | 复核 `unauth_raw.json` |
| `signals.py` | 函数体鉴权信号扫描脚本 | 复核 `unauth_signals.json` |
| `secret_scan.py` | 本目录的 secret 扫描器 | 见下 |

> **逐条分类表不在本目录**，位于上一级：
> `docs/audits/2026-10-03-go-full-audit/UNAUTHENTICATED_ROUTE_CLASSIFICATION_20261003.md`
> （METHOD / PATH / SOURCE / CURRENT_AUTH / CALLER / CLASSIFICATION / RATIONALE / REAL_FAILURE_IF_LEFT_OPEN / RECOMMENDED_ACTION）

## Secret scan 结果

对包内全部文本/二进制文件执行 `secret_scan.py`（模式：Firecrawl key、通用 `api_key/secret/token/password` 赋值、`Bearer`、`Set-Cookie`、PEM 私钥、AWS AK、JWT、`sk-` 前缀）：

```
FILES SCANNED: 28   (本归档目录全部文件)
SECRET-LIKE HITS: 0
RESULT: CLEAN (no secret-like pattern found in text evidence)
```

**明确不含**：secret / cookie / token / password / API key / 私人业务数据 dump。

## 可复现方式（只读）

```bash
# 0) 取基线
git fetch origin main && git rev-parse origin/main            # 应为 7e7aedd5…

# 1) 复现被审源码树（PR376 head，只读）
git fetch origin pull/376/head:refs/remotes/origin/pr376
git worktree add --detach /tmp/pr376 refs/remotes/origin/pr376   # 9f889acf…

# 2) 复算路由统计（脚本内的 ROOT 需指向该 PR376 检出）
python evidence/inv_api2.py      # 输出 ROUTES / AUTH DEPS / NO-AUTH ROUTES
python evidence/classify.py      # 输出 unauth_raw.json
python evidence/signals.py       # 输出 unauth_signals.json

# 3) 复算表引用
python evidence/inv_db.py        # 输出 db_tables.json

# 4) 复现现场 surface（匿名只读）
node evidence/surf.mjs

# 5) 本包 secret 扫描
python evidence/secret_scan.py
```

> 脚本内含**审计当天的本地绝对路径**（如临时检出目录）。这些路径不是证据指针，仅为复现方便；**不需要**按原路径摆放，改 `ROOT` 常量即可。

## 边界声明

- 全部现场交互为**匿名只读 GET** + 浏览器渲染。**未调用任何 POST/PUT/PATCH/DELETE**（包括匿名可达的写路由），未创建任何业务数据、订单、支付、通知或账号。
- 未修改产品源码、未 commit、未 push、未 deploy、未 restart、未改数据库。
- 现场凭据类信息**不入包**。审计过程中一个第三方 credential 的值曾进入本地命令输出（非本包内容），已在报告中作为 `CREDENTIAL_EXPOSURE_SCOPE_INCREASED` 记录，建议动作 = `ROTATE`。
