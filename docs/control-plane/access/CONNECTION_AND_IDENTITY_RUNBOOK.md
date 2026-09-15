# GO Control Plane connection and identity runbook

Verified on 2026-09-12 from the two fixed operator workstations used for GO work; **refreshed 2026-09-15** against canonical `main` `8610a4d`. On `Eason-13490` the verified primary ECS path changed from Alibaba Cloud Workbench CLI to **direct SSH key access** (Workbench CLI retained as fallback) - see the changelog in `connection-identities.v1.json`. This is a metadata-only inventory for recovery and automation. It is not Execution Authority: live state, Human Approval, Signed Tasks, installed artifacts, and Signed Evidence remain authoritative.

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
- GO working copy: `D:\Code\Workbuddy\GO` (canonical WorkBuddy working copy; branch `main`, re-verified at `8610a4d` on 2026-09-15). The earlier temporary-looking path recorded on 2026-09-12 is superseded and must not be treated as the canonical clone.
- Git remote access: HTTPS, using Git Credential Manager configured by PortableGit. Credentials themselves were not inspected or recorded.
- Browser required for normal GO source access: **NO**. HTTPS `git ls-remote` succeeded.
- Codex GitHub plugin/app integration: **UNAVAILABLE** in this Codex session. Normal work does not require it because local HTTPS Git access is available.

### Primary ECS access: direct SSH key access

For `Eason-13490`, the verified primary operational path to both ECS hosts is **direct SSH key access**. This was established and verified on 2026-09-15, replacing the earlier Workbench-CLI-primary conclusion.

- SSH config: `C:\Users\Eason\.ssh\config`
- Aliases: `hk-staging` -> `47.239.57.40`, `go-cc` -> `47.242.94.212`
- Local identity: `C:\Users\Eason\.ssh\id_ed25519_workbuddy` (ED25519, no passphrase, owner-only file ACL)
- Public key fingerprint: `SHA256:BhBEojejK53/yjbihKppoQQs1LJje/nLcIBensKUqBc`
- Public key deployed to `/root/.ssh/authorized_keys` on both hosts
- Server side: `pubkeyauthentication yes`, `passwordauthentication no` on both hosts
- Egress: the local Clash configuration maps both instance IPs to `DIRECT`, so SSH does not traverse a proxy
- Interactive authentication requirement for the existing Codex invocation: **NO**

| Target | ECS identity | Standard command | Verified probe |
| --- | --- | --- | --- |
| HK-STAGING-01 | instance `i-j6ccs8t04f1p4d8pe69z`, region `cn-hongkong`, `root`, target `47.239.57.40 / go-nexus-hk-stg-01` | `ssh hk-staging` | **PASS** - `iZj6ccs8t04f1p4d8pe69zZ` on 2026-09-15 |
| GO Command Center | instance `i-j6c7k6k01biwlbnwutu5`, region `cn-hongkong`, `root`, target `47.242.94.212 / GO-AI指挥中心` | `ssh go-cc` | **PASS** - `iZj6c7k6k01biwlbnwutu5Z` on 2026-09-15 |

Verified capabilities: interactive login, non-interactive invocation (`ssh <alias> <command>`), and `scp` upload with remote read-back.

This is a real local key path, not remote command execution through a cloud credential profile. It is still **capability, not authorization**: SSH access to a host does not grant deployment, migration, signing or Production authority.

### Fallback ECS access: Alibaba Cloud Workbench CLI

Alibaba Cloud Workbench CLI remains available on this workstation and is retained as the **fallback** path, not the primary one.

- Executable: `C:\Users\Eason\.workbench\bin\workbench.exe`
- Version: `workbench v1.0.1 (commit: 86c0aff, built: 2026-08-24T07:12:39Z)`
- Credential mechanism: existing **AK profile**; credential values are not read or recorded here

| Target | ECS identity | Workbench command |
| --- | --- | --- |
| HK-STAGING-01 | instance `i-j6ccs8t04f1p4d8pe69z`, region `cn-hongkong`, `root` | `workbench exec --instance-id i-j6ccs8t04f1p4d8pe69z --region cn-hongkong --command "hostname; whoami"` |
| GO Command Center | instance `i-j6c7k6k01biwlbnwutu5`, region `cn-hongkong`, `root` | `workbench exec --instance-id i-j6c7k6k01biwlbnwutu5 --region cn-hongkong --command "hostname; whoami"` |

**Why it is no longer primary.** Two account-level constraints were reproduced in practice on 2026-09-15:

1. The Workbench **session manager can be disabled wholesale by account risk control**. When that happens the CLI reports a *fixed-delay connection timeout* ("请检查安全组规则或网络连通性") rather than a permission error, so it reads like a security-group or network fault and sends diagnosis in the wrong direction.
2. **Concurrent sessions are capped**, and the CLI cannot list or close its own historical sessions (its session-listing call is denied). Once the cap is reached there is no self-service recovery — only waiting for idle reclamation.

Neither constraint applies to direct SSH key access. Workbench CLI is therefore demoted to fallback.

### Direct SSH status on Eason-13490

Direct SSH is the **primary** path on this workstation and is verified for both targets.

| Target | SSH target | Local identity / alias | Host-key configuration | Probe result |
| --- | --- | --- | --- | --- |
| HK-STAGING-01 | `root@47.239.57.40:22` | alias `hk-staging`; key `C:\Users\Eason\.ssh\id_ed25519_workbuddy` | `C:\Users\Eason\.ssh\config` + default `known_hosts`; `IdentitiesOnly=yes`, `StrictHostKeyChecking=yes` | **PASS** - hostname `iZj6ccs8t04f1p4d8pe69zZ`, 2026-09-15 |
| GO Command Center | `root@47.242.94.212:22` | alias `go-cc`; key `C:\Users\Eason\.ssh\id_ed25519_workbuddy` | same config; `IdentitiesOnly=yes`, `StrictHostKeyChecking=yes` | **PASS** - hostname `iZj6c7k6k01biwlbnwutu5Z`, 2026-09-15 |

Public key fingerprint on both edges: `SHA256:BhBEojejK53/yjbihKppoQQs1LJje/nLcIBensKUqBc`.

Historical note: at the 2026-09-12 inventory this machine had no working direct SSH to either host - HK was `CONFIGURED_AUTHORIZATION_FAILED` with a passphrase-protected key, and Command Center was `NOT_CONFIGURED`. The former key (`C:\Users\Eason\.ssh\go-nexus-hk-stg-01`, fingerprint `SHA256:jIcdy7HEdhsBREuoECUOrnLbLR51oqLS46lF4/jEPk4`) has since been archived locally and its `authorized_keys` entries removed from both hosts. See `connection-identities.v1.json` for the recorded previous state.

### Quick recovery commands

```powershell
cd D:\Code\Workbuddy\GO
git status --short --branch
git remote -v

# Preferred HK-STAGING-01 access from Eason-13490 (direct SSH key)
ssh hk-staging
ssh -o BatchMode=yes hk-staging "hostname; whoami"

# Preferred GO Command Center access from Eason-13490 (direct SSH key)
ssh go-cc
ssh -o BatchMode=yes go-cc "hostname; whoami"

# File transfer
scp local.file hk-staging:/tmp/

# Fallback only - Alibaba Cloud Workbench CLI, subject to account-level session limits
& "C:\Users\Eason\.workbench\bin\workbench.exe" exec --instance-id i-j6ccs8t04f1p4d8pe69z --region cn-hongkong --command "hostname; whoami"
& "C:\Users\Eason\.workbench\bin\workbench.exe" exec --instance-id i-j6c7k6k01biwlbnwutu5 --region cn-hongkong --command "hostname; whoami"
```

## Eason-8845 direct SSH identities

| Target | SSH target | Local identity | Public fingerprint | Verified |
| --- | --- | --- | --- | --- |
| HK-STAGING-01 | `root@47.239.57.40:22` | `C:\Users\Eason-8845\Downloads\go-nexus-hk-stg-01-direct-20260903.pem` | `SHA256:4wJ+PlUHmNCf+YcOYytYPmcz1g9v8+WHtuP/3HMbofA` (RSA 2048) | YES — 2026-09-12 probe; re-confirmed 2026-09-15 by the `Accepted publickey` fingerprint recorded in HK-STAGING-01's own sshd log |
| GO Command Center | `root@47.242.94.212:22` | `C:\Users\Eason-8845\.ssh\go-command-center-codex-root-ed25519` | `SHA256:MN3etVe4N91QpsfZkhZECi5YbW6XocZ0tB8LmVebBTU` (ED25519) | YES — 2026-09-12 probe; re-confirmed 2026-09-15 by the `Accepted publickey` fingerprint recorded in the Command Center's own sshd log |

**Naming discrepancy — RESOLVED on 2026-09-15.** The HK-STAGING-01 `authorized_keys` entry carrying fingerprint `SHA256:4wJ+PlUHmNCf+YcOYytYPmcz1g9v8+WHtuP/3HMbofA` is annotated `skp-j6cdb9zcrqzwjcb4uug3`, while the entry annotated `go-nexus-hk-stg-01-direct-20260903` carries a different fingerprint (`SHA256:Aweiz/cEV850c2AfKMQ8htAnLb8xnZUO41uOBH41GTs`).

This was settled by using the local private key and reading the fingerprint the server itself recorded for that login, rather than by comparing names:

```text
2026-09-15  -i C:\Users\Eason-8845\Downloads\go-nexus-hk-stg-01-direct-20260903.pem  root@47.239.57.40
            -> login succeeded
            -> HK-STAGING-01 sshd logged:  Accepted publickey ... ssh2: RSA SHA256:4wJ+PlUHmNCf+YcOYytYPmcz1g9v8+WHtuP/3HMbofA

Conclusion  the local file name and fingerprint 4wJ+PlUH... belong together
            the server-side annotation `skp-j6cdb9zcrqzwjcb4uug3` is a stale free-text label, not this key's name
            `go-nexus-hk-stg-01-direct-20260903` on the server is a DIFFERENT key (SHA256:Aweiz/cEV850c2AfKMQ8htAnLb8xnZUO41uOBH41GTs) that merely shares the name
            => server-side annotations are labels, not identity. The fingerprint is authoritative.
```

Do not infer key identity from a local file name or from a server-side annotation. Compare fingerprints.

The Command Center SSH alias is defined in `C:\Users\Eason-8845\.ssh\config`. That file contains exactly one `Host` entry — `go-command-center-root` — with:

```text
HostName             47.242.94.212
User                 root
IdentityFile         C:/Users/Eason-8845/.ssh/go-command-center-codex-root-ed25519
IdentitiesOnly       yes
StrictHostKeyChecking yes
UserKnownHostsFile   C:/Users/Eason-8845/.ssh/go-command-center-root-known_hosts
```

There is **no** HK-STAGING-01 alias, so that edge is always invoked with an explicit `-i` argument. Do not copy either private key to a server or into this repository.

### Eason-8845 key inventory (observed 2026-09-15)

```text
C:\Users\Eason-8845\.ssh\
  config
  go-command-center-codex-root-ed25519 (+ .pub)   -> root@GO Command Center        IN USE  (ED25519)
  go-command-center-root-known_hosts              -> dedicated known-hosts for the alias above
  go-nexus-hk-stg-01-direct-ed25519 (+ .pub)      -> fingerprint not yet captured
  go-nexus-hk-stg-01-ed25519 (+ .pub)             -> fingerprint not yet captured
  goai-command-admin                              -> fingerprint not yet captured (superseded predecessor?)
  goai-command-admin-v2 (+ .pub)                  -> goadmin@GO Command Center     WITHDRAWN 2026-09-15
  known_hosts, known_hosts.old

C:\Users\Eason-8845\Downloads\
  go-nexus-hk-stg-01-direct-20260903.pem          -> root@HK-STAGING-01            IN USE  (RSA 2048)
```

**Authorization withdrawn 2026-09-15.** The private-key body of `goai-command-admin-v2` (`SHA256:aOQ54zqSVfF1KlZtpYOswGGxk2rGUBxHmSzi9P6VUqM`, used as `goadmin@47.242.94.212`) was accidentally printed to a terminal by a mis-pasted multi-line command and is treated as exposed. Its `authorized_keys` entry was removed from `/home/goadmin/.ssh/authorized_keys` the same day, so `goadmin` currently has **no** SSH authorization on the Command Center. The `root` identities above are unaffected, and the account is unchanged — it can still be reached from the Command Center host via `su - goadmin`.

Only paths and fingerprints are recorded in this section. No private-key body, token, password, AccessKey or session value appears in this document or its JSON companion.

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

Eason-13490 / WorkBuddy + Codex
 |
 +-- HTTPS Git --> yuguangzhi3836-glitch/GO
 |                 credential: Git Credential Manager; plugin not required
 |
 +-- SSH key (direct) --> HK-STAGING-01     alias: hk-staging
 |                                           instance: i-j6ccs8t04f1p4d8pe69z
 |                                           user: root
 |
 +-- SSH key (direct) --> GO Command Center  alias: go-cc
 |                                           instance: i-j6c7k6k01biwlbnwutu5
 |                                           user: root
 |
 +-- (fallback) Alibaba Cloud Workbench CLI --> both hosts
                                               subject to account-level session limits

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
