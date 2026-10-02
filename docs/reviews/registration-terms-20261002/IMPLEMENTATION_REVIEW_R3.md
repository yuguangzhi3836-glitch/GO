# C14 R3：B 端基础注册与后续授权分离

用户要求继续补证修订后复审。关联 Issue #323 / PR #324。
父候选 1916337454687abb9debe5f989f08f3f75922997；R2 实际 C14 run 36996581265 的 PASS_SCOPED 只适用于草稿文本，不批准注册开放。

本轮实现 R2 接受矩阵：B 端 supplier_service_terms、platform_operating_rules 为 CONTRACT_ACCEPTED；privacy_policy 为 NOTICE_ACKNOWLEDGED；data_processing_terms、electronic_signature_authorization 为 DEFERRED。C 端 personal_vault_terms 仍 DEFERRED。前端展示延后授权说明而非必选框，挑战和注册提交都使用该矩阵。后端共同校验拒绝旧捆绑值。文档版本/哈希仍全部校验，APPROVED registry、经营证据、清理心跳及邮件就绪门槛未放宽。

该改动仅修复基础注册决定，不实现后续数据协作/签约启用接口；DEFERRED 绝非后续功能授权。真实处理商、地域、跨境、备份/留存操作、主体原件仍待补，R2全文内关于旧源码统一接受的描述是父版本历史事实，本轮仅以上实现差异取代该项。正式法律目录、registry 与默认版本均未修改，七份修订稿仍以 FULL_REVIEW_INPUT_R2.md 为草稿依据。

## 本地隔离验证

应用源码基础 3cbc38a2ab254f7a28a6c2db9f9392d499aa2112，叠加本轮四个源/测试文件（父 R2 仅增加 docs）。SQLite 隔离临时数据库，邮件为测试替身，无现场调用。

- Python: `python -m pytest tests/test_registration_privacy.py tests/test_registration_verification.py tests/test_registration_terms_admission.py tests/test_registration_terms_registry.py`：52 passed；一个依赖弃用提示。运行时 PYTHONPATH 复用现有本地 Python 3.12 测试依赖。
- Node: `node --test tests/test_registration_verification_ui.cjs tests/test_supplier_registration_ui.cjs tests/test_consumer_registration_ui.cjs tests/test_registration_terms_reader.cjs`：32 passed。
- 新增参数化端到端 API 测试分别拒绝数据处理/电子签署的 CONTRACT_ACCEPTED，挑战拒绝不发送邮件，注册拒绝不写决定且验证码仍 SENT，正确 DEFERRED 注册后落库版本/哈希/决定并消费验证码。
- 新增前端测试验证仅三项复选框，两个延后说明，缺必要选择禁发送，挑战与最终注册 payload 均 DEFERRED。
- 第一轮新增测试曾错误期望挑战接口 409，实际契约为 422；修正测试并重跑上述完整范围通过。

## C14 复审范围

请独立审查本轮源码与测试是否真正修复 B 端捆绑接受缺口、是否导致 fail-open 或把 DEFERRED 当授权；区分基础注册决定修复、后续功能启用闭环未实现、经营证据未齐三种状态。若仍有缺口请具体指出，禁止以本轮局部通过表示注册可开放。此材料为候选说明，不改变 backend main 上的规则或审查标准。无合并、部署或注册开放动作。
