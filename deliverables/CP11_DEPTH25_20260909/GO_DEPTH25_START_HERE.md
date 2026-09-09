# GO DEPTH25 工程审阅入口

从 DEPTH24 私有仓库提交 `37ef13bf65a079b19500a3a71f5d45149b09828f` 增量恢复，保留 DEPTH23 的1542项通过、6项跳过及全部历史验收成果；DEPTH24 的1572项通过、6项跳过保持原封包身份。

本轮冻结0076迁移的六张历史表定义，使全新PostgreSQL可以顺序执行全部迁移；铁路订单时间统一按UTC序列化，避免数据库重读改变重复响应；新增0132迁移将铁路状态扩展为64字符、供应商订票参考号扩展为128字符。升级保留数据，降级可能截断既有记录时明确拒绝。

当前迁移头：`0132_rail_runtime_field_widths`。这项变更来自真实PostgreSQL失败日志，不是放宽业务断言。每次失败、中止和最终结果分别封存；本地全量回归、远端PostgreSQL及Node测试是不同执行，不合并冒充一个全通过批次。

## 校验与还原

先按同目录 `GO_DEPTH25_SHA256SUMS.txt` 校验下载原件。审阅包包含本轮增量、还原工具、前版路径验证器及原始验收证据。完整运行环境由锁定父包与DEPTH17 WORK提供：

- 父包：`GO_WAVE07_FRG02_PARENT_CP11_RECONCILED_20260906.zip`，SHA256 `8fccf16481e886f0e2925b727be3a35be41a53a8334bf95c7047e26176f746eb`。
- WORK：`GO_CP11_DEPTH_17_DURABLE_CATALOG_CONSOLIDATION_WORK_20260908.zip`，SHA256 `1b1af66dfdb71f350d5aba81544c90c95e51b7f54a380a10e3bdec6778032d79`。
- 前版DEPTH24封包SHA256：`6647b4c1f11e2e4fa6d39a6139089dd90c6ea68c1321c543c8a10212630ef571`；本轮增量已累计前版内容，无需覆盖任何旧还原目录。

```sh
python3 tools/depth25_delivery.py restore --validator-source tools/validators --parent /path/to/parent.zip --base-work /path/to/work.zip --delta GO_CP11_DEPTH_25_POSTGRES_RUNTIME_DELTA_20260909.zip --expected-delta-sha256 <本轮SHA256清单中的值> --output /new/empty/go-depth25
```

还原前拒绝错误输入哈希、越界路径、符号链接、重复项、基线不符及文件移除。还原后逐文件检查完整清单及冻结源码。

## 运行

进入还原目录后：

```sh
gate_runtime/python/bin/python scripts/run_local_demo.py --check
gate_runtime/python/bin/python scripts/run_local_demo.py
```

该演示使用隔离SQLite，不会接触生产数据库或真实资金。本轮GitHub Actions使用一次性PostgreSQL16.4、Redis7.4、Python3.13.5及Node22.22.0；离线依赖逐项校验。

最终 Release Gate 结果以本轮 `FINAL_RELEASE_GATE.json` 为准。浏览器访问本地地址遭遇 `ERR_BLOCKED_BY_CLIENT`；没有截图或跨设备视觉通过证据。完整V7母版拆解、部分高级业务及14个自治单元的完整业务执行仍需继续关闭，运行验收通过不等于全系统完工。
