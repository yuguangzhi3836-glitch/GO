# 香港产品部署盘点与统一候选准备 — 2026-10-07

状态：PREPARED / NOT ADMITTED / NOT DEPLOYED。只集成现有成果，不新增产品开发任务。Persistent Runtime 按 #556 保持 DELIVERED / LIVE / FROZEN。

## 关键结论
不能直接用 main 覆盖香港。读取 main@13c78ce531c8afd7cbfb738f99a65732e50e5e01 与 #376@9f889acfcd36a82c7565b723261ee046c2615314 的完整非截断 Git trees，application 分别为 1378 / 1640 个 blob；#376 独有 274，main 独有 12，共同路径内容不同 237。这是文件差异统计，不是缺陷数量。
#376 独有内容包括注册邮件/条款/验证码、酒店资料审核、单日历以及 0135—0145 迁移链。main 的 0135_supplier_onboarding 不能覆盖香港的 0145 链。
本候选以已部署记录绑定的 #376 为保留基线；#385 两个文件已在该基线且与原 PR blob 完全一致，本候选 diff 包含 #477/#543/#548 的六个原始产品/测试文件，以及 C13 失败后补充的一项测试夹具修复；不把整棵 main 合入香港。PR 是 stacked candidate，base 为 #376 原分支，不修改/合并 #376，也不把该历史分支的 Runtime 当成当前安装源。

## 盘点
| 成果 | 证据与当前状态 | 本候选处理 |
|---|---|---|
| #376；内含 #365、#374/#375 注册语义与早期保留成果 | 已读 2026-10-03 原始部署记录；DEPLOY_SUCCESS / VERIFY_OK；当天八服务同镜像，0145 未迁移 | 完整保留；今日现场需重新确认 |
| #378 | 香港指针对账 PR 尚未合并；main 指针仍停在 #320 | 不修改指针，不把旧指针当今天实测 |
| #385 邮箱配置错误安全处理 | open Draft；精确 SHA b51f2f9edbd0b30c396cfd2c2136fa22899da67c；CI 37160966061 已读 success；独立服务级审核评论，非正式 C13/C14 | #376 保留基线已含相同两个 blob；不属于本候选 diff。SMTP 运行配置与真实收信仍待现场确认 |
| #477 连接器入驻权限 | open Draft；精确 SHA d76196883b19ac02385c85d845916fcadb3c953d；评论记录 C14/C13 PASS_SCOPED + ACCEPT，5 项机器测试 | 纳入；本轮未重新下载该封存包，不转授新候选 PASS |
| #543 本次认证事实绑定 | merged；精确原候选 3db4f74e25de09167e462537f68c42b6010f0517；前轮正式审核 8 项 PASS | 纳入；不是 B/C 注册完成证明 |
| #548 酒店硬保留释放恢复 | merged；精确原候选 24d458aaf7474ba2f88d637bda015d3a3db788f1；前轮正式审核 8 项 PASS（SQLite/mock） | 纳入；真实供应商仍未验收 |
| #523–#527、#505、#509、其他仍开放业务候选 | 不因 open/已有局部测试自动入选 | 本轮不混入 |
| #529/#531 UNKNOWN 与 #533 补证 | 无新正式完整 C13 PASS；隔离支付/完整营业日仍未收口 | 不追加补丁；同时完整保留 #376 已有 UNKNOWN 能力，不删减现场代码 |
| #217 | 已废弃 | 不恢复；保留 #376 内的 #365 现行修复 |
| 高并发/ABBA 候选 | 暂停 | 不追加；保留 #376 已有代码 |
| Runtime 与控制面成果 | #556 最终冻结 | 不部署 rt01、不追加 Runtime 工程 |

## 已完成的候选检查
- #477/#543/#548 三组候选差异补丁依次 git apply --check 均成功；#385 两个文件在 #376 保留基线已字节一致，不重复应用。
- 本候选 diff 的六个原始 Python 文件逐个 git hash-object，全部等于对应原始 PR 的 blob SHA；另有一个测试夹具文件仅补齐隔离签名密钥，不改产品代码；#385 两个保留文件另行验证等于原 PR blob。
- 七个候选差异 application Python 文件及两个 #385 基线保留文件的 Python AST 检查通过。
- 邮件配置 9 个 unittest 方法通过，全部 SMTP mock，无发送邮件。
- 静态解析全部 146 个迁移 revision，唯一 head 为 0145_source_latest_index；候选未更改任何迁移文件。
- application 预计 1643 个 blob（原1640 + 三个新增测试）；除七个候选差异 application 文件外必须与 #376 字节一致；其中一个仅为 C13 测试夹具修复，#385 两个文件作为基线保留项单列核对。
- 沿用既有 HK unified registration acceptance workflow，只新增此候选分支触发、补齐五份定向测试、保存 JUnit；原 PostgreSQL18.4、0145/legacy supplier 检查和六份回归全部保留。不修改 Runtime/审核工作流或预算。
- C14 R3 已对 `89df1b6d2c98a0e71f6bf6a491c04d0ca75395d5` 给出 PASS_SCOPED；随后 C13 run 37741868917 在 PostgreSQL 18.4 执行 148 项，144 PASS、4 FAIL，首错为测试夹具未提供非开发 JWT 签名密钥。当前补丁仅修复该隔离测试依赖；新 SHA 的 CI 与 C14→C13 均须重新绑定，旧 PASS 不转授。

## 发布前必须补齐
1. 通过已有正式只读通道读回今日香港八服务 image/source、DB revision、健康、邮件配置 readiness 与 secret 挂载是否有效（不输出值）。桌面连接器本轮无在线设备；此事实不代表香港宕机。
2. 新候选完整 PostgreSQL18.4 定向清单成功，检查 JUnit、exit、候选 SHA。原有审核只绑定各自原 SHA。
3. 对组合候选独立审核，再做 exact-source build / TEST_PR / admission / canary。镜像 digest 尚未生成，不能标可部署。
4. 原始 #376 Evidence 明确其 GO-FORGE 部署未创建 Command Center DEPLOY record，不能据此宣称 Command Center 自动回滚可用。下一次发布需确认当前正式路径和可用恢复记录，不照抄历史 helper 或修补 Runtime。
5. 取得精确候选的部署授权并完成受控发布后，实际浏览器验收：B/C 注册与再次登录 → 一家酒店资料/认证/认领/审核/合同/经营后台 → C端展示 → 库存/价格/订单闭环。

详细 Git blob、源 SHA、全部路径差异与状态见同目录 manifest.json。旧证据未重签、未继承，未合并、未部署、未迁移、未访问真实支付。
