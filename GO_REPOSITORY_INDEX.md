# GO 候选归档索引

用户于 2026-09-07 指定后续 GO 工作优先保存到 yuguangzhi3836-glitch/GO。

当前候选：[DEPTH09 · 酒店建库准确性与复制复核](deliverables/CP11_DEPTH09_20260907/README.md)。

上一冻结候选：[DEPTH08 · 14 单元持久执行与恢复](deliverables/CP11_DEPTH08_20260907/README.md)。

DEPTH09 在 DEPTH08 上增加酒店身份、明确官网房型关系采集、逐房型照片核对、可靠页面版本切换、
批次真实完成统计和管理写权限。更广一键建库流水线仍待完成。

FINAL_RELEASE_GATE=HOLD；HOTEL_REPLICATION_GATE=HOLD。以上均为工程复核归档，未部署香港。

## GO Command Center

2026-09-11 现役 Command Center 源码与运行配置归档：[`command-center/`](command-center/)。

该目录包含 Web Command Center 源码、现役 Boss Request Bridge 1.2.0、去敏配置、systemd/nginx 基线与源文件 SHA-256；不包含私钥、`.env` 实值、数据库、Token 或密码。

## HK-STAGING operations

Before any HK-STAGING deployment planning or execution, read
[`docs/control-plane/hk-staging/HK_STAGING_DEPLOY_RUNBOOK.md`](docs/control-plane/hk-staging/HK_STAGING_DEPLOY_RUNBOOK.md).
Do not reconstruct the deployment procedure from AI memory or prior chats.
