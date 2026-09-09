# DEPTH29 独立隔离验收记录

2026-09-09 20:43:54（北京时间），CI 34352506603 完成。固定候选 `0451fb095c6fe4a185dcf30931166cebdf27e381`，工具提交 `72fc4bd9533377b4be6ebdaed52ca950daf05fe0`。

直接检查原始工作日志：1207 个源码指纹一致；Python 3.13.5 / 临时 SQLite / TestClient 后端 171 项通过；Node 22.22.0 前端与原生纯函数 158 项通过，0 失败、0 跳过。后端出现 25 条 Alembic 配置弃用警告。以上为隔离组件验收，不是浏览器、原生设备、香港 RDS/Redis 或部署验收。

GitHub 返回证据包编号 10104378355、SHA256 `a4a94df08fec65ddb608fac54e7861de4ce5b57b467177a57e902aa7928314a2`；下载地址返回 HTTP 403（1010），因此尚未独立读取包内 JUnit 或计算下载包 SHA256。该限制单列，未把服务端陈述写成独立字节校验。

原始日志保持原样，校验见 SHA256SUMS；详细事实/陈述分离见 INDEPENDENT_CI_REVIEW.json。

三端真实 UX/登录、六品类真实闭环 E2E、封存 Node 与最终发布仍 HOLD。全系统未达到 100%；原生 V14 接入、原生完整操作、专业机票条件、完整高级售后、供应商及其他模块的剩余项见候选清单。没有合并、部署或生产改动。

[运行](https://github.com/yuguangzhi3836-glitch/GO/actions/runs/34352506603) · [草稿 PR #4](https://github.com/yuguangzhi3836-glitch/GO/pull/4) · [候选与剩余清单](https://github.com/yuguangzhi3836-glitch/GO/tree/0451fb095c6fe4a185dcf30931166cebdf27e381/deliverables/CP11_DEPTH29_TRIP_REENTRY_20260909)
