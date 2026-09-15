# DEPTH41 新父包已生成并永久归档

**CP11_DEPTH41_UNIFIED_PARENT_V1_20260912** 已完成构建和 Git 分卷回读，包大小 235,693,775 bytes（约 236 MB）。

- [完整父包下载](https://github.com/yuguangzhi3836-glitch/GO/actions/runs/34670014293/artifacts/10289943544)
- [准确版本与实际验收记录](ACCEPTANCE_RECORD.json)
- [分卷及完整包校验清单](PARENT_PARTS.json)
- [永久保存收据](ARCHIVE_RECEIPT.json)

完整 ZIP SHA256：`9f631cd819e4091ddec74fa2a812d96eafabcda0127e4c76633c58482291e1b8`。
源码提交：`62fdde3cabe72b92fa5dc1b37b7652395fe3aba5`；源码 SHA256 树：`928468ed31550195dfa8f121832e91b8d08aa9d5c15cef1381d903f76c9f97b3`。

本次实际检查：Python 1,704 通过、6 项 PostgreSQL 跳过、0 失败；前端 244、兼容 34、隔离 HTTP 148 检查通过；手机类型/原生模块连接通过。新镜像的源码、依赖版本、导出重新加载和 ZIP 独立恢复通过。12 卷均写入 Git 并逐卷回读核验。

原始浏览器 ZIP 已按原哈希保存于包内，仍绑定 PR48 的 c8d2b802；未逐张重新审阅截图，也不转移旧候选 PASS。完整跨端 UX、六品类最终资金闭环、原生设备、Sealed Node 与最终发布仍 HOLD。

构建 Run 34670014293 的应用检查和父包构建通过，首次归档因漏配 PR 读取权限返回 403；Run 34670940480 已修复归档并通过。修复只保存同一个已验证 ZIP。包内文档保留构建时点的记录，之后的检查和归档结论由本目录 ACCEPTANCE_RECORD.json 与仓库证据索引补充。

---

# DEPTH41 统一新父包

名称：`CP11_DEPTH41_UNIFIED_PARENT_V1_20260912`。

这是完整父包：1,300 个统一源码文件、与这些源码一致的新运行镜像、19 个原样保留的部署兼容文件、冻结的 Python 依赖、PR41 治理规则、逐文件对齐表、历史原始证据和剩余验收缺口。解压和离线核验不需要旧父包或补丁叠加。

旧父包 `CP11_DEPTH40_P03_COMPAT_V2_PARENT_20260912` 原归档保留。新镜像以其已校验的兼容镜像为底，复制完整统一源码，并仅重新绑定 preflight 的源码指纹与文件数量。兼容检查、配置检查、数据库只读检查、固定八服务和运行身份均保留。构建使用 `--network none`；镜像检查只执行 `source-check`、依赖版本核对和文件摘要，不连接业务数据库、不启动支付或部署服务。

`PARENT_MANIFEST.json` 给出源码提交、应用 Git tree、SHA256 树、镜像 ID、镜像归档摘要和构建 Run。`PARENT_BUILD_REPORT.json` 记录实际完整性、镜像加载和 ZIP 恢复结果。文件名不代表验收已通过：完整三端 UX、六品类资金闭环、真机、Sealed Node 和最终发布仍为 HOLD。香港当前运行版本与本包不同。

## 下载与核验

优先从 PR47 所列 Actions Run 的 `GO-DEPTH41-UNIFIED-PARENT-*` Artifact 下载完整 ZIP。该下载有保留期限；永久副本位于同一 PR47 的 `deliverables/CP11_DEPTH41_UNIFIED_PARENT_V1_20260912/`，其中的分卷保存在 Git 对象中。

下载该目录所有 `.partNNN`、`PARENT_PARTS.json` 和 `reconstruct_parent.py` 后：

```sh
python3 reconstruct_parent.py --directory . --output CP11_DEPTH41_UNIFIED_PARENT_V1_20260912.zip
```

使用 PR47 中公布的完整 SHA256 作为外部核验依据：

```sh
python3 verify_parent.py --zip CP11_DEPTH41_UNIFIED_PARENT_V1_20260912.zip --sha256 <PR47公布的SHA256> --restore-to new-parent
```

核验和恢复只读包并复制到不存在的新目录；不加载镜像、不安装、不部署。原始 PR48 浏览器 ZIP 如本轮成功读取，会原字节归档并登记收据；这只完成保存，不将旧候选测试改写为新候选 PASS。

## 后续开发

唯一待验源码位于 PR47 的 `application/`，固定源码提交见包内清单。先集中完成 `docs/canonical-baseline/REMAINING_GAPS.md`；PR48 保留为历史来源。审查通过且获得合并授权后，再从合并后的 main 创建短期功能分支，按 PR41 的提交、测试、PR、审查流程继续。代码合并与部署分别授权。

本包不携带新的站点绑定、签名任务或部署权限。源码保留、自动回归、镜像完整性与最终业务验收分别判断。
