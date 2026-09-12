# GO Control Plane connection and identity runbook

Verified on 2026-09-12 from the two fixed operator workstations used for GO work. This is a metadata-only inventory for recovery and automation. It is not Execution Authority: live state, Human Approval, Signed Tasks, installed artifacts, and Signed Evidence remain authoritative.

Never add a private-key body, PEM body, token, password, cookie, credential-manager secret, Alibaba Cloud AccessKey value, or runtime `.env` value to this document or its JSON companion.

## Workstation: Eason-8845

- Windows user/profile: `Eason-8845`, `C:\Users\Eason-8845`
- Operating system: Windows 11 Enterprise LTSC
- GO working copy: `C:\Users\Eason-8845\Documents\Code\GO-BOSS`
- Git remote: `https://github.com/yuguangzhi3836-glitch/GO.git`
- Git remote access: HTTPS, using the local Git credential helper (`manager`); credentials themselves were not inspected or recorded.
- Browser required to read the local GO source: **NO**.
- Codex GitHub plugin/app integration on `Eason-8845`: **UNAVAILABLE / unresolved as of 2026-09-12**. This is a workstation integration limitation, not a GO repository access failure. Routine recovery should use the local `GO-BOSS` working copy over HTTPS Git and should not spend time repeatedly attempting to install the Codex GitHub plugin unless the limitation is intentionally being re-investigated.

### Quick recovery commands

```powershell
cd C:\Users\Eason-8845\Documents\Code\GO-BOSS
git status
git remote -v

# HK-STAGING-01 direct SSH connection
ssh -o BatchMode=yes -o StrictHostKeyChecking=yes -i "C:\Users\Eason-8845\Downloads\go-nexus-hk-stg-01-direct-20260903.pem" root@47.239.57.40

# GO Command Center (preferred: Windows SSH alias; alias carries its dedicated host-key configuration)
ssh go-command-center-root

# GO Command Center raw target/key diagnostic fallback.
# This still enforces StrictHostKeyChecking; the alias remains preferred because its exact dedicated UserKnownHostsFile path is not yet recorded here.
ssh -o BatchMode=yes -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes -i "C:\Users\Eason-8845\.ssh\go-command-center-codex-root-ed25519" root@47.242.94.212
```

## Workstation: Eason-13490

`Eason-13490` is the fixed logical workstation ID used in this runbook. Its actual Windows hostname is `EASON`; this mapping was confirmed by the user on 2026-09-12 and the Windows hostname does not need to be changed.

- Windows hostname: `EASON`
- Windows user/profile: `EASON\Eason`, `C:\Users\Eason`
- Operating system: Windows 10 Enterprise LTSC 2021, 21H2, build 19044.7725.
- GO working copy currently observed: `C:\Users\Eason\Desktop\1\go-ai-webapp\.tmp-pr5-20260909\repo`. It was the only clone found within the approved search scope whose `origin` is `https://github.com/yuguangzhi3836-glitch/GO.git`; it tracks this PR branch. This is a temporary-looking path and should not be assumed to be a permanent canonical clone without a later intentional cleanup.
- Git remote access: HTTPS, using Git Credential Manager configured by PortableGit. Credentials themselves were not inspected or recorded.
- Browser required for normal GO source access: **NO**. HTTPS `git ls-remote` succeeded.
- Codex GitHub plugin/app integration: **UNAVAILABLE** in this Codex session. Normal work does not require it because local HTTPS Git access is available.

### Primary ECS access: Alibaba Cloud Workbench CLI

For `Eason-13490`, the verified primary operational path to both ECS hosts is Alibaba Cloud Workbench CLI, not direct SSH.

- Tool: `Alibaba Cloud Workbench CLI`
- Executable: `C:\Users\Eason\.workbench\bin\workbench.exe`
- Version: `workbench v1.0.1 (commit: 86c0aff, built: 2026-08-24T07:12:39Z)`
- Credential mechanism: existing **AK profile**; credential values were not read or recorded.
- Interactive authentication required for the existing Codex CLI invocation: **NO**.
- Codex can invoke the existing Workbench CLI path directly: **YES**.

| Target | ECS identity | Workbench command | Verified probe |
| --- | --- | --- | --- |
| HK-STAGING-01 | instance `i-j6ccs8t04f1p4d8pe69z`, region `cn-hongkong`, `root`, target `47.239.57.40 / go-nexus-hk-stg-01` | `workbench exec --instance-id i-j6ccs8t04f1p4d8pe69z --region cn-hongkong --command "hostname; whoami"` | **PASS** — `iZj6ccs8t04f1p4d8pe69zZ / root` on 2026-09-12 |
| GO Command Center | instance `i-j6c7k6k01biwlbnwutu5`, region `cn-hongkong`, `root`, target `47.242.94.212 / GO-AI指挥中心` | `workbench exec --instance-id i-j6c7k6k01biwlbnwutu5 --region cn-hongkong --command "hostname; whoami"` | **PASS** — `iZj6c7k6k01biwlbnwutu5Z / root` on 2026-09-12 |

Workbench access is remote command execution through the existing Alibaba Cloud credential profile. It must not be confused with a local SSH key path. Future recovery on this workstation should try the verified Workbench CLI path before spending time diagnosing or creating direct SSH identities.

### Direct SSH status on Eason-13490

Direct SSH is secondary/non-primary on this workstation and is not required for normal Codex ECS operations while Workbench remains available.

| Target | SSH target | Local identity / alias | Host-key configuration | Probe result |
| --- | --- | --- | --- | --- |
| HK-STAGING-01 | `root@47.239.57.40:22` | `C:\Users\Eason\.ssh\go-nexus-hk-stg-01`; no alias or SSH config entry | Default `C:\Users\Eason\.ssh\known_hosts`; probe used `IdentitiesOnly=yes` and `StrictHostKeyChecking=yes` | **NO** — existing key was rejected with `Permission denied (publickey)` on 2026-09-12. Fingerprint: `SHA256:jIcdy7HEdhsBREuoECUOrnLbLR51oqLS46lF4/jEPk4`. This does not block Workbench access. |
| GO Command Center | `root@47.242.94.212:22` | **NOT_CONFIGURED** — no dedicated local identity, alias, or SSH config entry found | Default `C:\Users\Eason\.ssh\known_hosts` exists, but no Command Center-specific mapping is configured | **NO** — no direct identity is available; a bounded probe timed out during banner exchange on 2026-09-12. This does not block Workbench access. |

### Quick recovery commands

```powershell
cd C:\Users\Eason\Desktop\1\go-ai-webapp\.tmp-pr5-20260909\repo
git status
git remote -v

# Preferred HK-STAGING-01 remote execution from Eason-13490
& "C:\Users\Eason\.workbench\bin\workbench.exe" exec --instance-id i-j6ccs8t04f1p4d8pe69z --region cn-hongkong --command "hostname; whoami"

# Preferred GO Command Center remote execution from Eason-13490
& "C:\Users\Eason\.workbench\bin\workbench.exe" exec --instance-id i-j6c7k6k01biwlbnwutu5 --region cn-hongkong --command "hostname; whoami"

# HK direct SSH diagnostic only. It was verified to fail authorization on 2026-09-12.
# Do not create a replacement key or copy a key from another workstation merely to replace the working Workbench path.
ssh -o BatchMode=yes -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile="C:\Users\Eason\.ssh\known_hosts" -i "C:\Users\Eason\.ssh\go-nexus-hk-stg-01" root@47.239.57.40
```

## Eason-8845 direct SSH identities

| Target | SSH target | Local identity | Public fingerprint | Verified |
| --- | --- | --- | --- | --- |
| HK-STAGING-01 | `root@47.239.57.40:22` | `C:\Users\Eason-8845\Downloads\go-nexus-hk-stg-01-direct-20260903.pem` | `SHA256:4wJ+PlUHmNCf+YcOYytYPmcz1g9v8+WHtuP/3HMbofA` | YES, strict-host-key connection probe on 2026-09-12 |
| GO Command Center | `root@47.242.94.212:22` | `C:\Users\Eason-8845\.ssh\go-command-center-codex-root-ed25519` | `SHA256:MN3etVe4N91QpsfZkhZECi5YbW6XocZ0tB8LmVebBTU` | YES, alias `go-command-center-root`, strict-host-key connection probe on 2026-09-12 |

The Command Center SSH alias is defined in `C:\Users\Eason-8845\.ssh\config`. It sets `IdentitiesOnly yes`, strict host-key checking, and a dedicated known-hosts file. The exact dedicated `UserKnownHostsFile` path is **NOT_YET_RECORDED**; capture it later from this workstation's SSH config rather than rediscovering server credentials. Do not copy its private key to a server or repository.

## Codex access map

```text
Eason-8845 / Codex
 |
 +-- HTTPS Git --> yuguangzhi3836-glitch/GO
 |                 credential: local Git credential helper
 |                 permission: developer access; browser not required
 |                 Codex GitHub plugin: unavailable on this workstation; local Git is the supported recovery path
 |
 +-- SSH + local PEM --> HK-STAGING-01 (root@47.239.57.40:22)
 |
 +-- SSH + local key --> GO Command Center (root@47.242.94.212:22)

Eason-13490 / Codex
 |
 +-- HTTPS Git --> yuguangzhi3836-glitch/GO
 |                 credential: Git Credential Manager; plugin not required
 |
 +-- Alibaba Cloud Workbench CLI --> HK-STAGING-01
 |                                  instance: i-j6ccs8t04f1p4d8pe69z
 |                                  user: root
 |
 +-- Alibaba Cloud Workbench CLI --> GO Command Center
                                    instance: i-j6c7k6k01biwlbnwutu5
                                    user: root

HK-STAGING-01
 |
 +-- Tasks Reader --> chenzhenxi1-sudo/go-control-tasks (read-only)
 +-- Evidence Writer --> chenzhenxi1-sudo/go-control-evidence (read/write)
 +-- GO Source Reader --> yuguangzhi3836-glitch/GO (read-only)

GO Command Center
 |
 +-- Tasks Writer --> chenzhenxi1-sudo/go-control-tasks (read/write)
 +-- Evidence Reader --> chenzhenxi1-sudo/go-control-evidence (read-only)
 +-- PR Resolver --> yuguangzhi3836-glitch/GO (read-only)
 +-- Task Signer --> HK Signed Task
```

Each edge records source, destination, protocol, credential path/mechanism, permission, and purpose in `connection-identities.v1.json`.

## Command Center server identities

All paths below are server-local paths on GO Command Center. The filesystem metadata was verified on 2026-09-12; no private material was read or copied.

| Identity | Purpose and repository | Permission | Private path | Public path | Owner / mode | SHA-256 fingerprint |
| --- | --- | --- | --- | --- | --- | --- |
| Tasks Writer | Publish formal tasks to `chenzhenxi1-sudo/go-control-tasks` | read/write | `/etc/go-command-center/keys/github-tasks-writer` | `/etc/go-command-center/keys/github-tasks-writer.pub` | `root:root`, `0600` private; `root:root`, `0644` public | `SHA256:lbORd4Kax3TYUswvLhk7pUU9Iz608MrlFIA1JoSnurQ` |
| Evidence Reader | Read signed evidence from `chenzhenxi1-sudo/go-control-evidence` | read-only | `/etc/go-command-center/keys/github-evidence-reader` | `/etc/go-command-center/keys/github-evidence-reader.pub` | `root:root`, `0600` private; `root:root`, `0644` public | `SHA256:+bWFnClf++LZHvzUcGN/2Q2lrhPdWUi0/TtpyIg6DXo` |
| GO PR Resolver | Resolve `refs/pull/<N>/head` to an immutable SHA in `yuguangzhi3836-glitch/GO` | read-only | `/etc/go-command-center/keys/github-go-pr-resolver` | `/etc/go-command-center/keys/github-go-pr-resolver.pub` | `root:root`, `0600` private; `root:root`, `0644` public | `SHA256:0lB7R/eqKeGnXeJyrBWpLIp/d1l1tpHmaH4GHtIi6Dw` |
| Task Signer | Sign Command Center task manifests for HK verification | signing only | `/etc/go-command-center/keys/task-manifest-signing.pem` | no separate local public file observed | `root:root`, `0600` private | `SHA256:bkwH368MFv+n+18Pca6MB1jV4jZtBbsn8yjC1bf/hns` (verified by HK task verifier) |

The PR Resolver has GitHub Deploy Key title `GO Command Center PR Resolver` and is expected to authenticate as `yuguangzhi3836-glitch/GO`. Its most recent verified result was `CC_GO_READ_ACCESS=PASS`, resolving PR #42 to `b5732c02dd95092a63def7eaa0d2cf332b1e2996`.

```bash
# Run on GO Command Center: PR ref resolution with only the resolver key.
GIT_SSH_COMMAND='ssh -o BatchMode=yes -o IdentitiesOnly=yes -o IdentityAgent=none -o ControlMaster=no -o ControlPath=none -i /etc/go-command-center/keys/github-go-pr-resolver' \
  git ls-remote git@github.com:yuguangzhi3836-glitch/GO.git refs/pull/42/head
```

### Retired Command Center identity

`github-go-source-reader` with fingerprint `SHA256:Zvv0eA2aKm3HiTuV7MrWrnPBbVolPBrNjTI1q2s57CA` was retired and deleted on 2026-09-12. It belonged to the abandoned direct-GO-repository-read design. **DO NOT RECREATE. DO NOT USE.** The fingerprint remains as historical audit evidence only.

## HK-STAGING-01 server identities

All paths below are server-local paths on HK-STAGING-01. The Agent configuration at `/etc/go-hk-agent/agent.json` was targeted-checked on 2026-09-12 for its task, evidence, verifier, and signer bindings.

| Identity | Purpose and repository | Permission | Private path | Public path | Owner / mode | SHA-256 fingerprint |
| --- | --- | --- | --- | --- | --- | --- |
| GO Source Reader | Fetch immutable GO commits from `yuguangzhi3836-glitch/GO` | read-only | `/etc/go-hk-agent/keys/github-go-source-reader` | `/etc/go-hk-agent/keys/github-go-source-reader.pub` | `go-hk-agent:go-hk-agent`, `0600` private; `go-hk-agent:go-hk-agent`, `0644` public | `SHA256:XvbkNhs8HWFzkrZrvQFXAEAtBEdnzI0O7Y0nNpO7gLs` |
| Tasks Reader | Read formal tasks from `chenzhenxi1-sudo/go-control-tasks` | read-only | `/etc/go-hk-agent/keys/tasks-read` | no separate public file observed | `go-hk-agent:go-hk-agent`, `0600` private | `SHA256:ONnJNvzDHi9q7JWcoPrYI/Hiw+pzT3kd/Xfht1liYGY` |
| Evidence Writer | Publish signed evidence to `chenzhenxi1-sudo/go-control-evidence` | read/write | `/etc/go-hk-agent/keys/evidence-write` | no separate public file observed | `go-hk-agent:go-hk-agent`, `0600` private | `SHA256:Pibr/vn6nLpTgk9mN4Anb5vjDkXTyDKuQyxRHYtxQ5c` |
| Task Verify | Verify Command Center signed tasks | verification only | none | `/etc/go-hk-agent/keys/task-verify.pub` | `root:go-hk-agent`, `0640` public | `SHA256:bkwH368MFv+n+18Pca6MB1jV4jZtBbsn8yjC1bf/hns` |
| Evidence Signer | Sign HK execution evidence | signing only | `/etc/go-hk-agent/keys/evidence-signing.pem` | `/etc/go-hk-agent/keys/evidence-signing.pub` | `go-hk-agent:go-hk-agent`, `0600` private; `root:go-hk-agent`, `0640` public | `SHA256:WZ2gG4WHnO5zmijyK8TSOHFpY+EBkk8TWbSbfbRjFNw` |

The HK GO Source Reader Deploy Key title is `HK-STAGING-01 GO source reader`. Its known verified result is `GO_SOURCE_READ_ACCESS=PASS` as `yuguangzhi3836-glitch/GO`.
