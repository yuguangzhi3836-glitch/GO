> **HISTORY / BREAK-GLASS REFERENCE**
>
> This document is not the normal current operating path.
>
> Normal deployment and inspection are defined by [`/AGENTS.md`](../AGENTS.md) and use GO Forge.
>
> Do not issue `HK_STAGING_*` requests unless the Owner explicitly authorizes Old Command Center fallback mode.

---

# GO Command Center — 2026-09-11 historical snapshot

> **HISTORICAL / LEGACY SNAPSHOT**
>
> This directory is the source/runtime archive collected on **2026-09-11** by PR #39. It is retained for provenance, recovery, and historical comparison. It is **not the current primary Command Center architecture or current capability inventory**.
>
> The current Command Center direction is **GitHub-native Control Plane + HK Agent**. Read [`../docs/control-plane/command-center/CURRENT_ARCHITECTURE.md`](../docs/control-plane/command-center/CURRENT_ARCHITECTURE.md) before doing any current CC design or implementation work.

This directory preserves the **actual source and runtime configuration observed on the live GO Command Center on 2026-09-11**. Source files are unpacked as normal Git files so ChatGPT/Codex can search and review that historical state directly.

Do **not** start new Command Center product design from `source/web/` unless a human explicitly asks to revive or maintain the legacy Web surface.

## Snapshot contents

- `source/web/` — Web Command Center source observed at `/home/goadmin/go-ai-command-center` on 2026-09-11. This Flask/Jinja UI is legacy/historical, not the current primary CC product surface.
- `source/bridge/go-boss-request-bridge` — exact installed Boss Request Bridge executable observed on 2026-09-11.
- `config/` — persistent VERIFY Request Bridge configuration and verified HK-STAGING baseline observed at snapshot time.
- `systemd/` — observed Command Center and Bridge systemd units, plus usage-report units.
- `nginx/` — observed Nginx configuration associated with the snapshot Web service.
- `audit/20260911/KEY_FINGERPRINTS.txt` — public fingerprints only; no private key material.
- `SOURCE_SHA256SUMS.txt` — SHA-256 hashes of the observed source/configuration files copied from the server.

The detailed historical runtime baseline is in [`../docs/control-plane/command-center/CURRENT_RUNTIME_BASELINE_20260911.md`](../docs/control-plane/command-center/CURRENT_RUNTIME_BASELINE_20260911.md). Despite the historical filename, do not treat that 2026-09-11 baseline as current architecture truth after later Control Plane changes.

## Verified snapshot binding

Installed Boss Request Bridge SHA-256 observed on 2026-09-11:

`3a23d4fb5ab7946fc6dcca15fb3450d14f6f896f6c2289ad3a0aa0e8bf0fc129`

This exactly matches `main_sha256` in the archived `config/boss-request-bridge-v1.manifest.json`. The exact copied Bridge passed its built-in 22-test self-test suite before archival.

The observed Gunicorn workers started at `2026-09-04 22:05:53 +0800`, one second after the latest observed `app.py` modification at `2026-09-04 22:05:52 +0800`; this is consistent with the workers loading the archived disk source at that time.

## Snapshot-time Boss Request capability

The Bridge captured in this directory was version `1.2.0`, revision `V2-persistent-verify-channel-r1`.

At **snapshot time (2026-09-11)**, that archived Bridge exposed only:

- action: `HK_STAGING_VERIFY`
- environment: `HK-STAGING-01`

This is a historical statement, **not the current capability inventory**. Later mainline work added and installed additional Control Plane capability, including TEST_PR integration and the fail-closed DEPLOY request capability. For current status, read:

1. [`../docs/control-plane/command-center/CURRENT_ARCHITECTURE.md`](../docs/control-plane/command-center/CURRENT_ARCHITECTURE.md)
2. [`../docs/control-plane/PR51_DEPLOY_CAPABILITY_CLOSEOUT_20260913.md`](../docs/control-plane/PR51_DEPLOY_CAPABILITY_CLOSEOUT_20260913.md)
3. the relevant current source under [`../control-plane/`](../control-plane/)
4. current HK operation/runbook documentation under [`../docs/control-plane/hk-staging/`](../docs/control-plane/hk-staging/)

Do not infer current VERIFY / TEST_PR / DEPLOY availability from this archive alone.

## What is deliberately not committed

This archive intentionally does **not** contain:

- Task-signing private key;
- GitHub SSH private keys;
- `.env` values;
- passwords or API tokens;
- SQLite runtime databases or backups;
- cookies/sessions;
- virtual environments, caches, or logs;
- raw `project-memory` history.

The project-memory files were reviewed during inventory, but are intentionally not copied into this historical source directory because they are non-authoritative context and would mix operational history with the snapshot baseline.

The server-side `github-go-source-reader` key recorded in the snapshot belongs to an abandoned direct-GO-repository-read design. Its fingerprint is retained for audit only; its private key is not archived and the key is not part of the intended current GitHub-native control architecture.

## Authority

This directory is historical source/configuration evidence. It is **not Execution Authority** and is **not the current CC design target**. Live state, deterministic policy gates, Human Approval where required, fresh Signed Tasks, installed artifacts, durable deployment state, and Signed Evidence remain authoritative for execution.
