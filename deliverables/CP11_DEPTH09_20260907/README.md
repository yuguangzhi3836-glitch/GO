# GO DEPTH09 · 一键建酒店库准确性复核候选

**HOTEL_REPLICATION_GATE=HOLD；FINAL_RELEASE_GATE=HOLD。未部署。**

本批针对“快速准确复制酒店”的要求补齐关键准确性缺口，继承 DEPTH08 原件。
完整一键建库与真实跨酒店复制仍有未闭合环节，不能据此宣布功能齐全。

- [详细复核报告](acceptance/GO_DEPTH09_REVIEW.md)
- [功能完整性矩阵](verification/current_build/depth09/CAPABILITY_MATRIX.json)
- [恢复与隔离验证说明](GO_DEPTH09_START_HERE.md)
- [源码变更清单](acceptance/DEPTH09_SOURCE_CHANGES.json) 与 [源码差异](acceptance/DEPTH09_SOURCE_CHANGES.patch)
- [当前完整回归状态](verification/current_build/depth09/CURRENT_BUILD_STATUS.json) 与 [原始 JUnit](verification/current_build/depth09/full_regression.xml)
- [新增功能测试](verification/current_build/depth09/targeted.xml) 与 [官网实际采集探测](verification/current_build/depth09/live_official_probe.json)
- [封包恢复验证](evidence/GO_DEPTH09_SEALED_VERIFICATION.json)
- [增量 ZIP](GO_CP11_DEPTH_09_HOTEL_REPLICATION_DELTA_20260907.zip) 与 [SHA256](GO_CP11_DEPTH_09_HOTEL_REPLICATION_DELTA_20260907.zip.sha256)
- [所有归档文件校验清单](ARCHIVE_FILES.json)

最终完整 Python 回归：1063 通过、6 项 PostgreSQL 检查跳过、0 失败。新增 43 项通过；封包恢复后 59 项通过。

## 原件与恢复

本目录的 src/frontend/tests/scripts 文件是变更文件的完整内容；ZIP 内有相同文件与验证证据。
它们按 DEPTH08 原件恢复为完整候选。准备 CP11、DEPTH07 WORK、[DEPTH08 增量](../CP11_DEPTH08_20260907/README.md)及本批增量；
下载本目录的 assemble_depth08_candidate.py 与 assemble_depth09_candidate.py，并按恢复说明执行。
各依赖精确 SHA 与文件谱系由恢复脚本检查。无需重做 DEPTH07/08 已通过的开发工作。

当前一键建库仍需补齐截图入口、官网模板与全量房型目录核验、自动媒体流水线、区域任务持久恢复、
到直订房型池的通用映射，以及真实跨酒店速度、浏览器和香港验收。
