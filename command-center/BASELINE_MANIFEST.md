> **HISTORY / BREAK-GLASS REFERENCE**
>
> This document is not the normal current operating path.
>
> Normal deployment and inspection are defined by [`/AGENTS.md`](../AGENTS.md) and use GO Forge.
>
> Do not issue `HK_STAGING_*` requests unless the Owner explicitly authorizes Old Command Center fallback mode.

---

# Command Center archive manifest — 2026-09-11

- Host role: GO Command Center
- Live application path: `/home/goadmin/go-ai-command-center`
- Web systemd unit: `go-ai-command-center.service`
- Gunicorn bind: `127.0.0.1:8080`
- Bridge executable: `/usr/local/libexec/go-boss-request-bridge`
- Bridge version: `1.2.0`
- Bridge revision: `V2-persistent-verify-channel-r1`
- Bridge SHA-256: `3a23d4fb5ab7946fc6dcca15fb3450d14f6f896f6c2289ad3a0aa0e8bf0fc129`
- Bridge channel mode: `PERSISTENT`
- Boss Request action exposed at snapshot time: `HK_STAGING_VERIFY`
- Boss Request environment: `HK-STAGING-01`
- Runtime mutation performed while collecting this archive: `NO`
- Command Center service restart performed while collecting this archive: `NO`

See `SOURCE_SHA256SUMS.txt` for hashes of the observed server source/configuration files and `../docs/control-plane/command-center/CURRENT_RUNTIME_BASELINE_20260911.md` for runtime details.
