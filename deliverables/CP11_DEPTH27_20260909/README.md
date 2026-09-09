# GO DEPTH27 — 会话隔离与加号定位修正

父版本：cfc8e07192fc6842e066ec17f960f6492e75864c（DEPTH26）。最终 Release Gate = HOLD，未部署香港。

本轮修复 C 端与后台 Cookie/CSRF 串用、错误平台登录覆盖会话、后台标签页账号切换、续期并发和退出失败误报。预览补齐 BFF/internal 转发，并支持无 randomUUID 的隔离 HTTP 预览。Logo 的 + 改在 DIRECT 右上方；G/O 等大与中央红色块保持原样。英文文字已转为矢量路径，字体替换不会挤动加号。

验收：59 项受影响 Python 测试与 130 项 Node 22.22.0 前端逻辑测试通过，0 失败、0 跳过。这不是重新执行全系统回归，也不与 DEPTH23/25 或 DEPTH26 的独立 PostgreSQL 结果相加。保留旧代码复现的 8 个失败场景，以及首次受影响回归中旧时间戳断言失败的原始证据。该断言已改成真正请求并验证所有页面脚本/样式；未插回旧版本字串。

当前仍缺三端登录后真实浏览器旅程、手机多尺寸、全六品类完整 E2E、完整密封 Node Gate、香港真实只读签名证据回流及全部母版需求关闭。页面公开访问和登录接口测试不能代替这些门禁。库存/房价/支付仍按明确标识的隔离测试范围验收，不要求生产资金交易。

## 文件
- source_changes/：可直接审阅的 19 个修改/新增文件。
- SOURCE_MANIFEST.json：父版本、逐文件前后 SHA256 与源码树范围。
- GO_CP11_DEPTH27_DELTA_20260909.zip：同一组源码与恢复清单。
- evidence/：原始 XML、日志、浏览器记录、Logo 实景与放大图、当前 Gate 状态。
- restore_depth27.py：只向新目录还原，先检查 DEPTH26 父指纹和每个修改前哈希。

还原：python restore_depth27.py --parent /path/to/unpacked-reviewed-DEPTH26 --delta GO_CP11_DEPTH27_DELTA_20260909.zip --output /path/to/new-DEPTH27

保留原父目录与原包；校验失败即停止。不会执行 CI、迁移或部署。详见 RESTORATION_VERIFIED.json。
