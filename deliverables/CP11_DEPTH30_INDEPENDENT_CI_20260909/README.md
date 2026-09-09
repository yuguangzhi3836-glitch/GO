# DEPTH30 独立验收证据

2026-09-09 23:45:59（北京时间），GitHub Actions 34372130831 完成，Job 102535715178 全部步骤成功。候选 `c495ca6547a667b9a4eb94a02e296231f9b88e79`；验收工具提交 `880bdc94d74b4bbf67b1448dceb04642ea0078e1`，草稿 PR #6 未合并。

直接检查原始 Job 日志及从日志导出的字节一致 JUnit：Python 3.13.5 后端 172 项、Node 22.22.0 前端／原生逻辑 194 项通过，无失败、错误或跳过。源码树 `f576c976bfe8f34d3182ba232fe1290c374346106c602a4fffe4935366f7a961` 的 1222 个文件在还原后及测试后均一致。

`backend.xml`、`frontend.xml`、`source-lineage.json` 由 CI 逐字节编码到原始日志，再由 `verify_exports.py` 解码并核对 SHA256。它们不是人工重写的测试摘要。GitHub Artifact 的 ZIP 仅核对了接口元数据与日志给出的摘要一致，未下载或独立校验 ZIP 全包。

环境为一次性 Ubuntu 22.04 runner、SQLite TestClient、VM／纯函数与标准输入输出接口桥接。原生业务函数确实参与六品类建单／模拟支付／退款接口验证；React Native 界面、原生构建、真机、三角色浏览器及香港现场并未执行。GitHub Action 自身的宿主 Node 24 与测试进程明确安装的 Node 22.22.0 分开记录。

此记录使 DEPTH30 的上述限定范围获得独立 CI 证据；不修改封存候选内生成于 CI 之前的 HOLD 记录。其他模块缺口、三端真实 UX／登录、六品类真实 E2E、完整密封 Node 和最终发布继续 HOLD，部署前完成率不宣称 100%。

原始来源：https://github.com/yuguangzhi3836-glitch/GO/actions/runs/34372130831
