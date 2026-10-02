# R4：修复只读候选下注册测试的缓存隔离

R3 C14 run 36998054803 对注册决定分离代码给出 PASS_SCOPED。R3 C13 run 36999318424 的机器阶段在两组测试的 client fixture 初始化时报 OSError errno 30：媒体服务尝试写 /srv/var/media_cache；C13 AI 未执行。不是注册断言失败，也不能记为通过。

本轮仅在 test_registration_privacy.py 增加 module-scope autouse fixture，在应用导入前用 GO_MEDIA_CACHE_DIR 指向 pytest 管理的独立临时目录，模块结束恢复环境变量。不更改注册业务、任何断言、测试选择、数据库、审核规则、只读候选挂载或正式注册门槛。

R3 的四个业务/测试文件与本轮小修叠加。B 端服务/运营规则合同接受，隐私告知确认，数据处理/电子签署 DEFERRED。后端捆绑拒绝及落库测试仍两组参数。

本轮本地重跑在 Starlette TestClient.__enter__/AnyIO portal 等待处停滞，已终止，未宣称本轮本地通过；R3 的 52 Python / 32 Node 仅是上一轮证据。正式 C13 将在 GitHub 隔离容器重跑同一库存 application/tests/test_registration_privacy.py::test_supplier_registration_rejects_bundled_authorization，并由独立 AI 判断范围与证据充分性。工作流提供 PostgreSQL 18.4 服务，但候选 conftest 未获 GO_TEST_DATABASE_URL 时实际使用 SQLite，因此不宣称 PostgreSQL 验收。

请 C14 审核本次测试隔离改动，R3 业务实现原有 scoped pass 仍绑定旧候选，本轮不继承成新候选通过。C13 必须配对本轮新 C14。仍无合并/部署/开放注册授权。Issue #323 已列经营证明、实际数据流、处理商、跨境、留存、备份、权利受理、正式条款批准及后续独立授权九项待补证。
