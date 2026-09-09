# GO DEPTH26：连接工程、售后完整性与等大 G/O 品牌

本轮为可还原的工程增量，**最终 Release Gate = HOLD**。未部署香港，未操作真实订单或生产 RDS。

- 保留 DEPTH23 的 1542 项通过记录、DEPTH24 与 DEPTH25 的全部封存成果。DEPTH25 完整回归为 1577 通过、6 项本地隔离，隔离用例在原 PostgreSQL 验收中通过。
- 本轮 72 项受影响后端测试、115 项前端逻辑测试通过；不把多次运行的数量相加成一次全量回归。
- 新增 8 项景点售后完整性用例在独立 PostgreSQL 16.4 中通过；控制模块 24 项用例通过。原始 XML 与 SHA256 已封存。
- 新增只读控制桥、服务入口和节点客户端，支持任务签名、限时租约、持久任务/回执、断线重试和重启恢复。香港真实链路尚未配置。
- G/O 使用相同外径与笔画宽度，中间保留红色块连接；同步消费端主标志、GO AI/Offer、小标志及 B/G 平台标志。
- 首页图片中的旧文字和固定评分已移除，改用干净示意背景与可访问的真实网页文字。表单标签可被屏幕阅读器识别，查询结果明确说明演示数据。

本轮远程运行：
https://github.com/yuguangzhi3836-glitch/GO/actions/runs/34310908873

## 仍需闭合

香港端缺少 CONTROL_API_ENDPOINT、NODE_TOKEN、TASK_HMAC_KEY、CA_PEM、GO_CP_NODE_ID 与批准的目标配置。RDS 只读探针包装器也未接入，因此不能声称香港直联打通，更不能以此重新部署生产。

实际浏览器已验证消费端首页、酒店入口、铁路/景点查询、未登录预订拦截以及合作伙伴/管理平台登录页。当前浏览器未提供设备视窗调整能力；嵌入页面又被现有 CSP/X-Frame-Options 拒绝，手机多尺寸与完整登录后跨端验收保持 HOLD。

此前全系统需求登记仍有 30 项关键需求未完全验收、725 段原文未完成逐项分解。高级售后、历史容量对账及自主执行等范围不能由本轮的小范围修复替代。VI 没有被宣称为“大师级 10 分”。

## 使用与还原

安装现有 Python 项目后使用 `python -m go_hotel.control_plane.worker --check`；源码目录未安装时添加 `PYTHONPATH=src`。配置说明在 `governance/control_plane_1_2/README.md`。缺少配置会输出 HOLD 并退出，不会无限等待。

本轮源码包附独立 SHA256 文件清单。完整断点还原使用锁定的父包、DEPTH17 WORK、DEPTH25 DELTA 与本轮 DELTA，命令由 `scripts/build_depth26_delivery.py restore --help` 提供。还原到新目录，逐文件核对；原目录与历史包均保留。

网页检查使用现有 Python 应用的隔离预览适配器，依赖在 package-lock.json 中锁定。`npm run dev` 仅用于本地验收，不是香港部署入口；临时数据库和运行环境均不进入交付包。
