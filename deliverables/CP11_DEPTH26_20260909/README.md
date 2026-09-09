# GO DEPTH26 交付入口

本轮包括只读控制连接工程、景点售后归属校验，以及 G/O 等大、红色连接块保留的网页品牌更新。最终 Release Gate 仍为 **HOLD**。

## 源码

下载 `GO_CP11_DEPTH26_SOURCE_REVIEWED_20260909.zip.part01`、`.part02`、`SOURCE_PARTS.json` 与 `join_source_parts.py` 到同一目录，执行：

```sh
python join_source_parts.py
```

脚本核对每片和合并包的 SHA256。合并后源码包 SHA256：

`7def8724d0bd5231fdd9b7ec8548951ed01a896d6b5d059d6d326d6bb252676a`

该包含 1,466 个有清单的文件，全部 1,077 个冻结源码文件保持原样。首次完整源码包上传被自动审批拦截，原因是历史 Staging 凭据相关文件可能包含敏感运行信息。本次包排除了 8 项历史环境关联、基础设施、凭据清单及本地状态记录；原文件及原包保留在工作区。排除明细在 `SOURCE_REVIEW_SCOPE.json`，独立还原结果在 `REVIEWED_SOURCE_RESTORATION.json`。分片仅用于满足连接器单次请求的大小限制。

## 验收与断点

- `GO_CP11_DEPTH26_REVIEW_BUNDLE_20260909.zip`：本轮原始测试、浏览器截图、品牌资料及还原证明。
- `GO_CP11_DEPTH26_DELTA_20260909.zip`：对锁定 DEPTH25 的 69 个文件增量，完整断点还原 1,961 个文件已逐项核对。
- `PUBLISHED_SHA256SUMS.txt`：本次实际发布包、分片和关键记录的校验值。
- `source_changes/`：便于评审的源码增量；完整源码使用上面的源码包。
- `evidence/`：本轮证据便于直接查看的副本。`home-desktop-final-cards.jpg` 与 `browser-layout-final.json` 是首页最终结果，其他截图保留定位过程。

72 项受影响后端测试、115 项前端测试通过。新增 8 项景点用例在独立 PostgreSQL 中通过；控制模块 24 项通过。历史完整回归保留，不将分批结果相加冒充一次全量回归。

远程验收：https://github.com/yuguangzhi3836-glitch/GO/actions/runs/34310908873

香港真实 HTTPS 端点、节点凭据、CA 与批准的目标配置仍未就绪，RDS 只读探针未接入。手机多尺寸、登录后跨角色验收和全系统需求闭合仍为 HOLD；未重新部署香港，也未声称 VI 达到大师级 10 分。
