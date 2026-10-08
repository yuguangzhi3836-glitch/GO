> **HISTORY / BREAK-GLASS REFERENCE**
>
> This document is not the normal current operating path.
>
> Normal deployment and inspection are defined by [`/AGENTS.md`](../../../AGENTS.md) and use GO Forge.
>
> Do not issue `HK_STAGING_*` requests unless the Owner explicitly authorizes Old Command Center fallback mode.

---

# Command Center runtime baseline — 2026-09-11

## Web application

- Host role: GO Command Center
- Application path: `/home/goadmin/go-ai-command-center`
- systemd unit: `go-ai-command-center.service`
- service user/group: `goadmin:goadmin`
- Gunicorn bind: `127.0.0.1:8080`
- workers: 2
- worker class: `gthread`
- threads per worker: 16
- runtime env file exists outside this repository snapshot and its values are intentionally not archived here.

Observed Gunicorn workers started at `2026-09-04 22:05:53 +0800`.
Observed `app.py` mtime was `2026-09-04 22:05:52 +0800`, one second before those workers started.

## Boss Request Bridge

- executable: `/usr/local/libexec/go-boss-request-bridge`
- installed SHA-256: `3a23d4fb5ab7946fc6dcca15fb3450d14f6f896f6c2289ad3a0aa0e8bf0fc129`
- version: `1.2.0`
- revision: `V2-persistent-verify-channel-r1`
- channel mode: `PERSISTENT`
- current allowed action: `HK_STAGING_VERIFY`
- current allowed environment: `HK-STAGING-01`
- systemd timer cadence: approximately every 60 seconds (`OnBootSec=60s`, `OnUnitActiveSec=60s`)
- task signing key path remains server-only: `/etc/go-command-center/keys/task-manifest-signing.pem`

The archived timer unit's human-readable `Description=` still contains the old words `publish disabled`; that label is stale. The installed root-owned channel configuration has `publish_enabled=true`, and the persistent VERIFY E2E was separately proven. Treat actual configuration and runtime evidence, not the unit description string, as state.

## Current HK-STAGING verified baseline used by VERIFY Bridge

- image ID: `sha256:66c540878ff5dd8d2d089059288c3d9f0c45f880514f7b053bd50defb9e8c324`
- evidence task: `go-boss02-post-rollback-verify-20260911T071429Z`
- evidence commit: `2dbbdefaf7996e5f9222669929eee79eefabae56`

## Credentials

Private credential contents are deliberately absent.

Known public fingerprints are archived separately in `command-center/audit/20260911/KEY_FINGERPRINTS.txt`.

The `github-go-source-reader` key was generated during an abandoned direct-GO-repository-read design. It was not adopted as the intended DEPLOY_PR transport. Do not treat its presence on disk as architectural authority or as proof that it is authorized in GitHub.

## Mutability / authority note

This is an observed baseline and source archive, not a live execution gate. Runtime state can change after this timestamp; fresh live operations must still perform current drift/preflight checks.
