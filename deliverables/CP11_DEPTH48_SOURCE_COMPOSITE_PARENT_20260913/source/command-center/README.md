# GO Command Center

This directory is the 2026-09-11 archive of the **actual source and runtime configuration observed on the live GO Command Center**. Source files are unpacked as normal Git files so ChatGPT/Codex can search and review them directly.

## Canonical source in this snapshot

- `source/web/` — current web Command Center source from `/home/goadmin/go-ai-command-center`.
- `source/bridge/go-boss-request-bridge` — exact installed Boss Request Bridge executable from `/usr/local/libexec/go-boss-request-bridge`.
- `config/` — current persistent VERIFY Request Bridge configuration and verified HK-STAGING baseline used by the Bridge.
- `systemd/` — current observed Command Center and Bridge systemd units, plus usage-report units.
- `nginx/` — observed Nginx configuration associated with the current web service.
- `audit/20260911/KEY_FINGERPRINTS.txt` — public fingerprints only; no private key material.
- `SOURCE_SHA256SUMS.txt` — SHA-256 hashes of the observed source/configuration files copied from the server.

The detailed observed runtime baseline is in [`../docs/control-plane/command-center/CURRENT_RUNTIME_BASELINE_20260911.md`](../docs/control-plane/command-center/CURRENT_RUNTIME_BASELINE_20260911.md).

## Verified runtime binding

Installed Boss Request Bridge SHA-256:

`3a23d4fb5ab7946fc6dcca15fb3450d14f6f896f6c2289ad3a0aa0e8bf0fc129`

This exactly matches `main_sha256` in `config/boss-request-bridge-v1.manifest.json`. The exact copied Bridge passed its built-in 22-test self-test suite before archival.

The observed Gunicorn workers started at `2026-09-04 22:05:53 +0800`, one second after the latest observed `app.py` modification at `2026-09-04 22:05:52 +0800`; this is consistent with the workers loading the archived disk source.

## Current Boss Request capability

The installed Bridge is version `1.2.0`, revision `V2-persistent-verify-channel-r1`.

The Boss Request channel currently exposes only:

- action: `HK_STAGING_VERIFY`
- environment: `HK-STAGING-01`

The underlying Control Plane has separately proven VERIFY/CANARY/DEPLOY/ROLLBACK paths, but the **Boss Request channel in this snapshot exposes VERIFY only**. DEPLOY_PR source-snapshot work is not yet a proven live Boss Request capability.

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

The project-memory files were reviewed during inventory, but are intentionally not copied into this canonical source directory because they are historical/non-authoritative context and would mix operational history with the source baseline.

The server-side `github-go-source-reader` key belongs to the abandoned direct-GO-repository-read design. Its fingerprint is retained for audit only; its private key is not archived and the key is not part of the intended source-snapshot architecture.

## Authority

This repository is a source/configuration archive and documentation source. It is **not execution authority**. Live state, deterministic policy gates, Human Approval where required, Signed Tasks, installed artifacts, durable deployment state, and Signed Evidence remain authoritative for execution.
