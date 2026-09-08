# GO DEPTH17 工程复核包

本包将已核验的 DEPTH16 与 GitHub 保存的两条并行修订合并：持久任务执行和酒店目录建库。修复了新资格规则与旧执行器的衔接、执行中资格失效回滚，以及演示环境任务入口。工程与最终发布均仍有未完成项，未部署。

两条 GitHub 历史修订也使用 DEPTH08、DEPTH09 编号，但与 DEPTH16 内的酒店结算同编号迭代并非同一条分支。它们的原报告单独保存在 `verification/current_build/depth17/imported_branch8`、`imported_branch9`，不覆盖此前验收记录。

## 恢复方式

若使用累计 WORK，沿用 `scripts/assemble_review_copy.py`，输入锁定父包与本轮 WORK 即可。若使用紧凑 DELTA，先取出其中 `payload/scripts/assemble_depth17_review.py`，执行：

```bash
python3 assemble_depth17_review.py \
  --parent GO_WAVE07_FRG02_PARENT_CP11_RECONCILED_20260906.zip \
  --base-work GO_CP11_DEPTH_16_CURRENT_AUTONOMY_AUTHORITY_WORK_20260907.zip \
  --delta GO_CP11_DEPTH_17_DURABLE_CATALOG_CONSOLIDATION_DELTA_20260908.zip \
  --output GO_DEPTH17_REVIEW
```

父包 SHA256：`8fccf16481e886f0e2925b727be3a35be41a53a8334bf95c7047e26176f746eb`。

DEPTH16 WORK SHA256：`e776e941d7cc1cc64b98bf4e02b538d5f1cf44a53e418c04962b65bcfc646025`。

脚本核验这两个输入、增量逐文件指纹及合成后的完整清单，只写新目录。Linux x86_64 可直接使用内置 Python 3.13；其他平台需兼容的独立运行环境。

## 隔离复验

```bash
cd GO_DEPTH17_REVIEW
gate_runtime/python/bin/python scripts/verify_delivery.py
gate_runtime/python/bin/python scripts/run_local_demo.py --check --data-dir /tmp/go_depth17_demo
gate_runtime/python/bin/python -m pytest -q
node --test tests_frontend/*.test.mjs
```

演示启动使用 `scripts/run_local_demo.py`，打开 `/go-app/`。`--check` 是接口和页面资源检查，不能代替浏览器视觉检查。演示环境中的新任务归入 TEST，不获得生产执行资格。

数据库新增 `0124_autonomy_durable`，前 123 个迁移保持原文件。升级从本线 `0123_catalog_credit_exclusion` 向前追加。另一个分支的 `0116_autonomy_durable` 不应直接导入或 stamp 为本线版本；如已运行那条分支的数据库，先保留备份并另做跨分支数据迁移核验，本包不宣称兼容该现存数据库的直接升级。已有任务或资格证据时，0124 的回退会拒绝删除其表。

新接口为 `/internal/v1/autonomy`：读取要求 GO 管理身份及 admin:read，操作另需 admin:rules。`/observe` 只提交 14 个单元的业务状态汇总任务；工作进程为 `python -m go_hotel.workers.autonomy_worker --once`。启动 worker 时必须使用与应用相同的隔离 DATABASE_URL、APP_ENV 和 PYTHONPATH。任务支持租约、检查点、有限重试、暂停、恢复及取消。未知外部结果只查询核对，不自动重发。

当前注册的业务适配器只生成运营观察和异常清单，不自动退款、订票、授予资格或发布生产系统。酒店目录增加事实与媒体发布门禁，但通用建库尚未全部接入这套持久执行器。完整范围及未完成项见 `acceptance/GO_DEPTH17_REVIEW.md`；最终实测见 `verification/current_build/depth17/CURRENT_BUILD_STATUS.json`。
