# GO Control Plane connection and identity runbook

Verified on 2026-09-12 from workstation `Eason-8845`. This is a metadata-only inventory for recovery and automation. It is not Execution Authority: live state, Human Approval, Signed Tasks, installed artifacts, and Signed Evidence remain authoritative.

Never add a private-key body, PEM body, token, password, cookie, credential-manager secret, or runtime `.env` value to this document or its JSON companion.

## Workstation: Eason-8845

- Windows user/profile: `Eason-8845`, `C:\Users\Eason-8845`
- Operating system: Windows 11 Enterprise LTSC
- GO working copy: `C:\Users\Eason-8845\Documents\Code\GO-BOSS`
- Git remote: `https://github.com/yuguangzhi3836-glitch/GO.git`
- Git remote access: HTTPS, using the local Git credential helper (`manager`); credentials themselves were not inspected or recorded.
- Browser required to read the local GO source: **NO**.
- Codex GitHub plugin/app integration on `Eason-8845`: **UNAVAILABLE / unresolved as of 2026-09-12**. This is a workstation integration limitation, not a GO repository access failure. Routine recovery should use the local `GO-BOSS` working copy over HTTPS Git and should not spend time repeatedly attempting to install the Codex GitHub plugin unless that limitation is intentionally being re-investigated.

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

## Workstation direct SSH identities

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
 |                       |
 |                       +-- Tasks Reader --> chenzhenxi1-sudo/go-control-tasks (read-only)
 |                       +-- Evidence Writer --> chenzhenxi1-sudo/go-control-evidence (read/write)
 |                       +-- GO Source Reader --> yuguangzhi3836-glitch/GO (read-only)
 |
 +-- SSH + local key --> GO Command Center (root@47.242.94.212:22)
                         |
                         +-- Tasks Writer --> chenzhenxi1-sudo/go-control-tasks (read/write)
                         +-- Evidence Reader --> chenzhenxi1-sudo/go-control-evidence (read-only)
                         +-- PR Resolver --> yuguangzhi3836-glitch/GO (read-only)
                         +-- Task Signer --> HK Signed Task
```

Each edge records source, destination, protocol, credential path, permission, and purpose in `connection-identities.v1.json`.

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

## Second workstation

`Eason-13490`: `NOT_YET_DOCUMENTED`. Do not infer its user name, repository path, SSH configuration, or identity locations from this workstation.
