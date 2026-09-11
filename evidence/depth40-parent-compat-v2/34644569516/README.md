# 新父包交付记录

已生成：**CP11_DEPTH40_P03_COMPAT_V2_PARENT_20260912**。

- 完成时间：2026-09-12 04:31:37 +08:00。
- [打包 PR #44](https://github.com/yuguangzhi3836-glitch/GO/pull/44)，源提交 `4c9d24ee37cef02cfef026c41db3dfb38d09b9f0`，草稿、未合并。
- [独立 CI Run 34644569516](https://github.com/yuguangzhi3836-glitch/GO/actions/runs/34644569516)，Job 103412134995，SUCCESS。
- [下载父包及校验文件（Artifact 10281491262）](https://github.com/yuguangzhi3836-glitch/GO/actions/runs/34644569516/artifacts/10281491262)。

## 精确身份

真正的父包文件：`CP11_DEPTH40_P03_COMPAT_V2_PARENT_20260912.zip`，187168614 bytes。

父包内层 ZIP SHA256：

```text
421b11f95d0400bdfc69d4053a6d3b54599fa791a0d6b43311b83094bcd51c6a
```

GitHub Artifact 是包含父包 ZIP、校验文件及报告的外层包装，SHA256 **不同**：

```text
sha256:3a727c72cfe7d0894936bb066a71abf522a14a6a05943c8f4dc62b4f45cbcfe8
```

镜像 config ID：`sha256:cba95a5ac6f061b8196f953f181952fdad94ab520a12cbeb0e7ee49d9a6de150`。

镜像归档 SHA256：`edca0c20cac07950b79814ef2e5ec56d3551430a02ff6943532a9009538395a5`。

1271 个业务源码文件的树 SHA256：`64f5d78a17b2fa2194b18f9bc1ba0cafbf0f2547f0171a859dd4300c75e37667`，与旧父包完全一致。

## 已直接核验的原始输出

本目录保留原始 CI 日志，以及从该日志完整 JSON 行提取的 PARENT_BUILD_REPORT 和 PARENT_MANIFEST。14 项工具防护测试通过；1319 项整包文件校验、固定兼容 Artifact ZIP 校验、源码/执行器/镜像身份、目录恢复和 ZIP 恢复均 PASS。未在本工作站再次下载重算整个 ZIP；这里的外层摘要同时与 GitHub Artifact 元数据一致。

包内已有完整 application、修订镜像、执行器、工程源码与原始兼容验收记录。下载这个父包后，离线恢复不依赖历史 Artifact 或 Overlay。镜像沿用先前已验收字节，未重新构建或加载；历史业务测试未重跑。报告中的 network_used=false 是离线校验函数的输出，不代表 CI 获取固定输入或上传产物时未联网。

## 保存与运行边界

Artifact 按 90 天保留，当前到期时间 **2026-12-10T20:30:21Z**。GO 中的代码、清单和日志长期保留；需要长期离线使用时应保留下载后的父包 ZIP 及完整校验文件。

新 ID 是总包身份，包内业务候选仍为 CP11_DEPTH40_P03_PARENT_20260911，旧封存包不覆盖。SITE_BINDING=UNBOUND；本次没有香港安装或部署，未合并 PR #42/#43/#44，未重发 VERIFY，未启动 TEST_PR。三端、六品类、Sealed Node 和最终发布没有因打包转为 PASS；Production 继续 HOLD。
