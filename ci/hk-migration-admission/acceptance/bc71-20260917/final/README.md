# Issue #103 香港部署收口归档

本归档保存 2026-09-17 香港 Staging 部署、中央自动派发的独立 VERIFY、现场回读及指挥中心状态同步修复记录。用户已明确授权将这些记录归档至私库 `yuguangzhi3836-glitch/GO`。

## 已核验结果

| 项目 | 结果 |
| --- | --- |
| 产品源码 | PR #183，`edd3500575d2f2b81298cc9273025e0a3b734897` |
| 部署 | `DEPLOY_OK`，2026-09-17 15:38:25 UTC |
| 独立 VERIFY | `VERIFY_OK`，2026-09-17 15:41:28 UTC |
| 现场回读 | 2026-09-17 15:55:55 UTC；八个业务服务运行同一候选镜像，API healthy，重启次数均为 0 |
| 数据库迁移 | `0133_flight_change_plan` → `0137_hosted_unknown_episode`；原始迁移记录哈希与签名部署 Evidence 一致 |
| 非目标容器 | Redis / Caddy 的容器身份与镜像保持一致 |
| 指挥中心 | 状态周期 2026-09-17 16:09:51 UTC 恢复 `OK`；本次 VERIFY 显示 `PROVEN / COMPLETE` |

## 状态同步修复

现场投影器已经安装已独立验收的 PR #187 源码 `bc71a91bff31a092aae003e061622878b8ef4bf6`，但安装记录仍引用旧版 projector SHA256，导致定时周期从 14:44 UTC 起报 `projector_integrity=MISMATCH`。

修复前，逐字节核对两个现场 Python 文件与该固定 Git commit，确认 Git blob 和 SHA256 一致。随后备份并原子更新安装记录中的 revision / hash，保留原有完整性校验，恢复原定时器。没有修改投影器源码，也没有再次部署香港业务。修复回执与随后的真实状态发布结果见 `PROJECTOR_INSTALL_RECEIPT.json`、`CONTROL_STATE_READBACK.json`。

## 文件与来源

- `SUMMARY.json`：完整收口摘要、范围、授权及此前归档阻断历史。
- `DEPLOYMENT_CLOSEOUT.json`：独立本地验签与现场绑定核对结果。
- `*_TASK.json`、`*_EVIDENCE.json`：CANARY、preflight、DEPLOY、独立 VERIFY 的已有原始签名记录；未重新签名。
- `REFERENCES.json`：原始私库、固定 commit 和路径；此前安装及 C14/C13 评审归档位于 [e88cd5d9](https://github.com/yuguangzhi3836-glitch/GO/tree/e88cd5d9488fa08bd9715cbab2b7c459bd01a295/ci/hk-migration-admission/acceptance/bc71-20260917)。
- `HK_HOST_READBACK.json`：按固定字段采集的现场观测，包含既有部署/迁移记录原始字节及哈希；它本身是未签名的操作观测。
- `task.pub`、`evidence.pub`、`identities.json`：已发布的验签公钥与身份映射，不含私钥。
- `verify_closeout.py`：离线验证 Ed25519 签名、任务/镜像/合同绑定、原始记录哈希、迁移结果、八服务、非目标容器与单次执行证据。运行需要 Python 和 cryptography。
- `repair_projector_installation.py`：已执行安装记录修复的归档源码。旧哈希前置条件现已消耗，不能重放。
- `PROJECTOR_PREFLIGHT.json`、`REVIEWED_SOURCE_BINDING.json`：修复前状态与固定源码身份。
- `SHA256SUMS`：本目录其他全部文件的确定性校验清单，排除清单自身。

## 范围

本次归档不创建新的 Task、不重放部署、不合并产品 PR，也不修改 canonical main 的运行指针。记录是所列时间点的证据，不是持续健康保证。

`application_health_proven=false` 保持原始语义；这里没有声称消费者/供应商/管理员的完整业务旅程通过。真实供应商连接、Final Release、Production 继续 HOLD。
