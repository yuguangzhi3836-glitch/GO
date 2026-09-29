# C13 round7 实现预审：FAIL，等待修复及最终冻结候选

2026-09-26。本报告只针对 `implementation-preview/`、`IMPLEMENTATION_PREVIEW.json` 的不可变预审快照，非远端最终候选。基线 PR246 为 `3fc5b59e6c3703d94462f763bd22db2bf8315651`。168 个快照文件逐一 SHA256 验证无不符。未读取运行中的 GO-round7 作为执行来源；未修改产品；未合并、部署、使用真实支付或真实客人。

方法：独立全新 SQLite，合成酒店/客人、原 IdentityService 登录/MFA/JWT/持久会话、原 FastAPI router，dependency_overrides 为空。复用开发 fixture 只建立明确工程隔离资格和原始媒体文件，不改要测的业务逻辑。此报告不把 fixture 当真实商业授权。三个独立探针与结果均放在本目录。

## PRV-01 — P1：有规则的未收费确认申请仍没有取消出口（HTTP已复现）

已批准工程酒店，消费者正常下单，酒店不经 checkout 直接 CONFIRM。reserve 200、confirm 200；消费者普通 cancel 409 `CONFIRMED_CANCELLATION_FARE_QUOTE_REQUIRED`，报价 409 `KNOWN_FROZEN_FARE_AUTHORIZATION_REQUIRED`。数据库订单 CONFIRMED、有真实退改快照，资金状态仍 `ALIPAY_APPLICATION_PENDING_NO_CHARGE`。

原因：`hosted_reservation_operations.action` 对有规则快照的确认单一律要求报价；`hosted_fare_rules.eligible` 又要求存在冻结授权。新开发完整旅程测试增加 checkout，只覆盖有资金授权的分支，没有覆盖原来的未收费申请旅程。

要求：既然当前是 RESERVATION_REQUEST_ONLY，为无资金且未入住的已确认申请定义可执行退出路径，正确释放库存/更新Trips/通知；有授权、扣款、UNKNOWN、已入住等必须保留资金与售后保护，不得据此免费绕过。也可以在确认前明确拒绝不满足商业条件，但不能让新订单确认后陷入死路。

证据：`preview_independent_probe.py`、`preview-independent-result.json`。

## PRV-02 — P1：财务相邻入口遗漏酒店范围校验（HTTP已复现）

仅有酒店 A 根授权的合法 GO_GOVERNANCE JWT，对酒店 B 普通改价返回 403；同一 JWT 对 B 的 fault-finance 返回 200，对 fault-mandates 返回 200，真实新增 B 酒店 ACTIVE mandate，registered_by 为 A 操作者。

原因：`api/routes/hosted_direct_booking.py` 404–468 的 11 个 supplier disruption / fault mandate / recovery / finance 路由仍只使用 `require_permission('admin:finance')`；新 `hosted_admin` 的范围解析并未被调用。服务只收到 user_id 或没有 actor，不能补充范围。三条内容入口有独立 binding 校验，不与这 11 条混为一谈。

要求：所有等价财务操作读取/写入均使用统一资源归属校验。核对多资源关系，防止 hotel_id 与 reservation_id 不同范围；普通业务权限不能变成全局全酒店能力。为全局列表/任务定义明确允许范围或拒绝策略，并防止响应从未过滤的分支泄露资料。

证据：`preview_crosshotel_finance_probe.py`、`preview-crosshotel-finance-result.json`。

## PRV-03 — P1：媒体提交者能够自己批准新媒体，独立审核名实不符（HTTP已复现）

content maker 为 A，checker 为 B。已有发布后，B 通过实际 media-assets 接口登记另一张 HERO 的权利声明，再由 B 自己 publication-review APPROVE：媒体登记 200、审核 200、公开 page 200，新增媒体在 page 中可见。

原因：publication 只拒绝 reviewer 等于 content_snapshot 的 maker。HostedMediaAssetRow 没有提交者字段/可信提交主体绑定；本次被批准的媒体可以由 reviewer 自己刚刚登记。原始字节存在和 SHA 匹配只能证明文件完整，不能证明独立审核。

要求：持久记录并验证媒体提交主体及酒店授权来源，发布 manifest 纳入每个媒体的可信提交绑定。审核者不得审核自己提交/变更的媒体；历史无来源记录保持未核验。提交者必须由服务端当前 Principal 得出，不接受 caller 伪造字段。真实媒体权利仍保持单独 HOLD。

证据：`preview_media_selfreview_probe.py`、`preview-media-selfreview-result.json`。

## 资金与恢复专项复跑结果

实际复跑 51 例：50 通过、1 失败、0 跳过。包括开发侧新酒店旅程15例、维持减额5例及既有补偿/授权回归。日志 `preview-test.log`、JUnit `preview-junit.xml`。

唯一失败：`test_historical_compensation_authority_survives_later_pending_and_upward_review`。历史8000→3000→5000，现在历史补偿授权多返回一项，旧断言只期待3000对应授权。新契约相对原已扣金额仍是减额；这可能是有意契约改变，不能仅据旧断言判资金错账。实现者需明确更新历史授权的语义与测试，并保留“3000已补后上调5000不能自动补扣”“未补则仍补至最新目标”两组资金对照。

新执行恢复将批准事实与执行成功分离，并将订单/库存/通知与成功结果放入同一业务事务；本次已执行的业务失败/两个注入中断测试通过。未独立执行 PostgreSQL 并发，不把 SQLite 线程用例称PG证据。未运行浏览器、物理真机或全应用旅程。

## 当前判断

预审发现的三项P1必须修正。限定测试通过不是完整旅程通过，不给予最终C13 PASS。主代理已获逐项反馈；待新远端候选SHA与源码清单冻结后再定向复验。固定305义务/1009场景分母不变；未扩大本轮检查清单。
