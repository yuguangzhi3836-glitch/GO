# GO DEPTH08 · 自运营持久执行工程候选

继承已核验的 DEPTH07。`FINAL_RELEASE_GATE=HOLD`；没有部署或向香港投递任务。

本批完成持久任务、逐步检查点、租约恢复、防重复执行、暂停/恢复、权限撤销、
资格过期检查、外部未知结果核对，以及管理接口和独立 Worker。
14 个单元均接入了两步运行观察：读取其职责范围内的业务状态汇总，再保存需关注项。
观察任务不会执行退款、订单变更、供应商调用或发布批准。
它们是管理员授权的确定性任务，不被标成已经取得生产自主经营资格。
更多业务写操作必须通过各自的版本化适配器、原业务幂等约束与资格证据接入。

## 恢复新候选

保留三个原件：

- `GO_WAVE07_FRG02_PARENT_CP11_RECONCILED_20260906.zip`
- `GO_CP11_DEPTH_07_DIRECT_MONEY_LEDGER_WORK_20260907.zip`
- `GO_CP11_DEPTH_08_DURABLE_EXECUTION_DELTA_20260907.zip`

从 DEPTH08 ZIP 解出 `payload/scripts/assemble_depth08_candidate.py`，执行：

```bash
python3 assemble_depth08_candidate.py \
  --parent GO_WAVE07_FRG02_PARENT_CP11_RECONCILED_20260906.zip \
  --depth07-work GO_CP11_DEPTH_07_DIRECT_MONEY_LEDGER_WORK_20260907.zip \
  --delta GO_CP11_DEPTH_08_DURABLE_EXECUTION_DELTA_20260907.zip \
  --output GO_DEPTH08_REVIEW
```

程序要求新目录，先核对两个依赖原件 SHA256、ZIP 路径与 CRC、增量的每项文件，
再核对旧文件指纹与恢复后的源码树 SHA256。任何不符都停止。
只需 CP11、DEPTH07、本批增量，不用重做 DEPTH03–06。
Linux x86_64 可使用内置 Python；Windows/macOS 可恢复文件，但不能运行该 Linux Python。

## 隔离验收

在恢复目录执行：

```bash
gate_runtime/python/bin/python -m pytest \
  tests/autonomy/test_depth08_durable.py \
  tests/test_depth08_api_and_migration.py
```

该命令使用独立测试数据库，不应传入真实运行数据库。
独立进程测试会强制终止由测试自己创建的子进程，以验证崩溃恢复。

可对同一可靠性矩阵追加 PostgreSQL 验收：

```bash
GO_DEPTH08_TEST_DATABASE_URL='postgresql+psycopg://localhost/go_depth08_test' \
  gate_runtime/python/bin/python -m pytest tests/autonomy/test_depth08_durable.py
```

仅接受显式提供的本机 PostgreSQL、数据库名以 `_test` 结尾。
测试每项使用随机新 schema，并仅清理该 schema。凭证由本机环境配置，禁止填入交付包。
本批报告未把 SQLite 结果视为 PostgreSQL 通过。

## 运行接线

候选新增迁移 `0116_autonomy_durable`，父版本 `0115_rental_change_settlement`。
现有 115 个迁移文件未修改。迁移增加五张自运营表，不改变酒店、支付、租车业务字段。
Worker 不创建 schema，也不会由 API 启动自动开启。须先在新建或经备份验证的隔离副本
执行迁移，再验证权限和队列；本说明不授权对香港或生产执行迁移。

管理端已登录且具有 `admin:rules` 的管理员可通过现有认证向
`POST /internal/v1/autonomy/observe` 提交以下请求：

```json
{"idempotency_key":"review-cycle-001","cell_ids":["C01","C02","C03","C04","C05","C06","C07","C08","C09","C10","C11","C12","C13","C14"]}
```

重复提交同一键得到原任务；改变请求内容返回冲突。客户端不得提供任意能力、SQL、
导入路径、风险等级或执行环境。任务持久保存，独立 Worker 读取该队列：

```bash
PYTHONPATH=src gate_runtime/python/bin/python -m go_hotel.workers.autonomy_worker --once
PYTHONPATH=src gate_runtime/python/bin/python -m go_hotel.workers.autonomy_worker
```

使用明确指向隔离副本的 `DATABASE_URL` 和对应 `APP_ENV`。
`--cell C01` 可限制单个 Worker 的单元。SIGTERM/SIGINT 会在当前任务结束后退出；
强制终止后，由后续 Worker 在租约到期时恢复。该 Worker 持续消费队列，不自动生成定时任务。

管理查询入口：`GET /internal/v1/autonomy/cells`、`GET /internal/v1/autonomy/tasks`、
`GET /internal/v1/autonomy/tasks/{task_id}`。详情包含检查点哈希、顺序事件和阻塞原因。
暂停/恢复单元使用 `POST /cells/{cell_id}/control`，正文为 `paused` 与查询所得 `expected_version`。
任务暂停原因消除后可 `POST /tasks/{task_id}/resume`；可取消的本地任务用 `/cancel`。
`DEAD` 和 `UNCERTAIN` 不提供一键强制重跑。

## 回退与后续门禁

停止新增 Worker 可回到原有业务运行方式，五张表保留证据。
空表允许迁移回退；已有任务、资格或控制记录时，迁移回退会拒绝删除它们。
有数据的回退应使用经过验证的数据库备份恢复路径，不能清表冒充回退。

当前结论、继承门禁及实测数字见 `verification/current_build/depth08/CURRENT_BUILD_STATUS.json`。
PostgreSQL、冻结 Node 22.22、真实浏览器/真机、生产资格和更广业务适配仍按证据逐项验收。
