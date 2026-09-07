# GO DEPTH08 review package

本候选继承已核验的 DEPTH07，范围为 14 个自运营单元的持久执行、中断恢复与防重复执行。`FINAL_RELEASE_GATE=HOLD`。

## 复核入口

- [候选增量 ZIP](GO_CP11_DEPTH_08_DURABLE_EXECUTION_DELTA_20260907.zip) 与 [SHA256](GO_CP11_DEPTH_08_DURABLE_EXECUTION_DELTA_20260907.zip.sha256)
- [工程复核报告](acceptance/GO_DEPTH08_REVIEW.md)
- [源码变更清单](acceptance/DEPTH08_SOURCE_CHANGES.json) 与 [完整源码差异](acceptance/DEPTH08_SOURCE_CHANGES.patch)
- [恢复与隔离运行说明](GO_DEPTH08_START_HERE.md)；[独立恢复脚本](assemble_depth08_candidate.py)
- [最终回归状态](verification/current_build/depth08/CURRENT_BUILD_STATUS.json)、[完整 JUnit](verification/current_build/depth08/full_regression.xml)、[新增测试记录](verification/current_build/depth08/targeted.xml)
- [封包恢复验证](evidence/GO_DEPTH08_SEALED_VERIFICATION.json) 与 [恢复后 JUnit](evidence/GO_DEPTH08_SEALED_TESTS.xml)
- [增量内部清单](DEPTH08_DELTA_MANIFEST.json) 与 [本目录文件校验清单](ARCHIVE_FILES.json)

完整 Python 回归：1026 项，1020 通过、6 项原隔离 PostgreSQL 检查跳过、0 失败、0 错误。本批新增 57 项通过。封包恢复后 77 项通过，无跳过、失败或错误。本次归档复用已完成的验证证据，没有重跑 DEPTH07。

## 恢复依赖

增量内含 13 个变更源码文件的完整替换内容，以及复核证据。恢复需要保留以下两个已验证原件，无需重做 DEPTH03–06。

| 文件 | SHA256 | 来源 |
| --- | --- | --- |
| `GO_WAVE07_FRG02_PARENT_CP11_RECONCILED_20260906.zip` | `8fccf16481e886f0e2925b727be3a35be41a53a8334bf95c7047e26176f746eb` | 已交付的 CP11 原件 |
| `GO_CP11_DEPTH_07_DIRECT_MONEY_LEDGER_WORK_20260907.zip` | `25e92a436ecd811794cbe90b1e000f9cfe71eeca8b420eaeff151e62ae61b808` | [已归档 DEPTH07](https://github.com/chenzhenxi1-sudo/go-control-tasks/tree/34b80961ee11b282a642e3e3722233dd6bd8120b/deliverables/CP11_DEPTH07_20260907)，按该目录恢复说明组合分片 |
| `GO_CP11_DEPTH_08_DURABLE_EXECUTION_DELTA_20260907.zip` | `e6446a852d1806cc4afe0ae0ec88a79e228484518dcf21039fea551342507c0a` | 本目录，209363 字节 |

```bash
python3 assemble_depth08_candidate.py \
  --parent GO_WAVE07_FRG02_PARENT_CP11_RECONCILED_20260906.zip \
  --depth07-work GO_CP11_DEPTH_07_DIRECT_MONEY_LEDGER_WORK_20260907.zip \
  --delta GO_CP11_DEPTH_08_DURABLE_EXECUTION_DELTA_20260907.zip \
  --output GO_DEPTH08_REVIEW
```

恢复脚本核对依赖、增量文件与最终源码树。最终源码树 SHA256 为 `c4c00f4476a3c7041ae7ed10a10bef60dc2efcf8c56e86c83d35ca24748310ea`。构建回执中的绝对路径是构建时记录，下载后按本目录文件名执行。

14 单元当前接入受控运行观察任务；更广业务写操作、生产自治资格、真实 PostgreSQL、浏览器、移动端、冻结 Node 22.22 及继承的高级售后边界仍待验收。本候选未部署。
