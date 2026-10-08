> **HISTORY / BREAK-GLASS REFERENCE**
>
> This document is not the normal current operating path.
>
> Normal deployment and inspection are defined by [`/AGENTS.md`](../../../AGENTS.md) and use GO Forge.
>
> Do not issue `HK_STAGING_*` requests unless the Owner explicitly authorizes Old Command Center fallback mode.

---

# main 收敛装机记录 · 2026-09-19

`main` = `71b9fb3a3bc97f77b86e4e1b958c557d58389d46`（由 #220 与 #232 两次 merge 构成）。

本文件记录把两台主机的控制面从外部候选（PR #201 head `9b9327456`）换成上表 `main` 的那一次装机，
以及装机后当场测到的东西。**它替代不了现场实测**：任何"现场现在跑什么"的判断仍然要重新读盘。

## 装机范围

| 主机 | 目标 | 装了几个 | 结果 |
|---|---|---|---|
| GO Command Center | 控制面 5 个文件 | 5 替换 | 全部 = `main` blob |
| HK-STAGING-01 | deployctl 启动器 + runtime 模块 + agent 包 + agent 入口 | 21 目标（8 替换 / 9 新建 / 4 本来已同字节） | 全部 = `main` blob |

未被触碰：业务容器、compose、env 文件、数据库、媒体目录、Production。

## 装机后必须一起改的两处

### 1. 单元必须点名计划目录

`command-center/systemd/go-boss-request-bridge.service` 的 `ReadWritePaths` 少了
`/etc/go-command-center/deployment-plans-v1`。单元被 `ProtectSystem=strict` 罩着，
而这个目录正是 `plan_derivation.register()` 写派生计划的地方，于是每一次 DEPLOY 都会走
`plan_derivation.py` 里那段 `except OSError -> Reject('plan_store_unwritable')`，
被**干净地拒绝**——不报错、不中断 tick，只是没有任何部署能成功。

这段 fail-closed 是**对的**（一个处理不了的 DEPLOY 不该停掉 VERIFY / TEST_PR / CANARY / HEALTH）；
错的是单元。而且这个失败模式只在宿主侧可见：代码里加了 fail-closed，单元却一直没补，
所以**用这个仓库装出来的主机，每一次 DEPLOY 都会被拒**。本 PR 把这一行补进仓库，
并加测试把单元和 `gate.STORE` 绑在一起（见 `ShippedUnitTests`）。

装机时这条已经在现场单元上（来自更早的宿主侧修正），装机后实测：

```text
systemd-analyze verify /etc/systemd/system/go-boss-request-bridge.service      rc=0
systemd-run -p ProtectSystem=strict -p ReadWritePaths=/etc/go-command-center/deployment-plans-v1 ...
                                                                              SANDBOX_WRITE_OK
目录前后对比                                                                  leftover=0
```

### 2. 事实导出必须认识金丝雀与回滚

`control-plane/command-center-request-visibility-v1/command-center/go-request-fact-export`
在 `main` 里由 `18e3cdca2` / `81c02f94d` 补齐，导出的 action 词表覆盖
`HK_STAGING_CANARY` / `HK_STAGING_ROLLBACK`；更早的版本只有 DEPLOY / TEST_PR / VERIFY。
装前装后按字节数：

| token | 装后（main） | 装前 |
|---|---|---|
| `HK_STAGING_CANARY` | 1 | 0 |
| `HK_STAGING_ROLLBACK` | 1 | 0 |
| `HK_STAGING_DEPLOY` | 1 | 1 |

## 装机后实测（两台主机）

```text
installed bytes vs main blobs                     CC 5/5 ; HK 21/21 相同
CC  journal Traceback                            0
CC  state-cycle                                  cycle OK / projector OK / projector_integrity OK
CC  installed_revision                           71b9fb3a3bc97f77b86e4e1b958c557d58389d46
CC  账本                                         285 条，published 283 / ignored 2，非终态 0
HK  environment_lock_regression                  33 checks, 0 failed（primitive=fcntl.flock）
HK  collector_runtime_regression                 23 checks, 0 failed
HK  rollback_runtime_regression                  31 checks, 0 failed
HK  合计                                         87 checks, 0 failed
HK  media_mount.verify() 对运行中的容器          {"MEDIA_MOUNT": "SUCCESS"}  8/8 services
HK  业务指纹 docker ps names|image              装前 == 装后
```

三条回归套件之所以是最强的证据，是因为它们核对的是
`LAUNCHER_STILL_PINS_*_BY_EXACT_BYTES` 与 `DEPLOYCTL_INTEGRITY_CHECK_IS_STILL_ENFORCED`：
它们等于在问"启动器钉住的字节和盘上的文件是不是 1:1 对得上"。

`media_mount.verify()` 读的是**实际运行的容器**（env + bind mount + 容器内可读性），
不是命令行，所以 `MEDIA_MOUNT=SUCCESS` 表示那 8 个服务确实从宿主的固定目录读写媒体，
而不是各自在容器里长出一个空目录。

## 没有做、也不要误读成做过了的事

- **没有真跑一次 DEPLOY。** 装机授权只覆盖控制面文件；且控制总线当时 320 个 task 全部终态，
  agent 一轮 `processed=0` 是正常的空转，不是失败。
- **`install_fact.py` 装了但在两台主机上休眠**：`install-fact-v1.json` 不存在，
  `verify_installed_files` / `installed_identity` 没有对象可校验。要启用得先产出这份文档（独立工作项）。
- **`candidate_contract_sha256` 是两侧共有协议字段**，`main` 里没有独立的
  `hk_candidate_contract.py` 模块 ⇒ 协议保留，少一层独立校验实现。
- 被替换掉的候选专属文件**留在盘上没删**（回滚就是换文件），并且已验证**没有任何已安装文件引用它们**。

## 回滚

- CC：`/var/lib/go-command-center/ccv1115-main-install-backup-20260919T141414Z/`
- HK：`/var/backups/HK-CHANGE-20260919T141548Z-ccv1115-main/`（`backup.tar.gz` + `state.before.tsv`）

回滚 = 停 timer → 还原文件 → 还原 `installed.json` 的 `projector_sha256` 与 `projector_revision`。
