# GO HK-STAGING — observed live source and runtime archive

This directory archives the source and operational configuration observed on **HK-STAGING-01** on 2026-09-11. It is separate from `command-center/`.

## What is here

- `source/runtime/` — **577 exact build-input files recovered from the currently running business image**, excluding only six generated runtime artifacts (`*.egg-info` and `var/media_cache/index.json`).
- `source/agent/` — current HK Agent source plus the exact installed `/usr/local/libexec/go-hk-agent` entrypoint.
- `source/executor/` — exact installed `go-hk-deployctl`, its four required runtime modules, and the preflight probe.
- `compose/` — exact Compose file bound to the running `go-822-staging` project.
- `systemd/`, `config/`, `caddy/` — observed operational configuration, with private key contents and runtime secret values excluded.
- `build/` — current host-side build observations and the single proven host-vs-live source drift.

## Live business image

- Tag: `go-hotel:aoluguya-direct-r3-1-20260906`
- Image ID / repository digest: `sha256:66c540878ff5dd8d2d089059288c3d9f0c45f880514f7b053bd50defb9e8c324`
- Image created: `2026-09-06T12:11:13.978020567+08:00`
- Compose project: `go-822-staging`
- API container observed healthy: `go-822-staging-api-1`

All eight business targets use this same image. Redis and Caddy are protected non-target services.

These eight business roles are now documented as the current proven `HK_STAGING_BUSINESS_TOPOLOGY` version `1`. They are a versioned baseline rather than a permanent architectural limit. See [`../docs/control-plane/hk-staging/DEPLOYMENT_TOPOLOGY_V1.json`](../docs/control-plane/hk-staging/DEPLOYMENT_TOPOLOGY_V1.json) and [`../docs/control-plane/hk-staging/TOPOLOGY_CHANGE_POLICY.md`](../docs/control-plane/hk-staging/TOPOLOGY_CHANGE_POLICY.md). The installed Executor still enforces the fixed eight-service scope; no dynamic topology loading is claimed.

## Runtime source identity

`source/runtime/` contains 577 files. Its deterministic sorted SHA-256 manifest digest is:

`2c2606a33c5b124062c5ea99b7f2431d2714fd8e453529549431c84205087022`

The server's current host build context also contains 577 files, but its corresponding manifest digest is:

`3dd3cd35985f24b55b87c8793dff010c2b23269b9b6d12a5367d14eeb8c30c7d`

The two trees have 577 common paths, 576 byte-identical files, and exactly one differing file. See `build/RUNTIME_VS_HOST_DIFF.md`.

## Agent / Executor

- Agent version observed in source: `0.5.7-rebuilt`
- Agent transport SHA-256: `4301a7e920fc25d98ea8403ac00ebbdb6a864bcb092d33caf343ad28603ff490`
- Installed Agent entrypoint SHA-256: `73f7e407dcd97d5ed7bff2bcf171d717a281087ced0ecfc0a8d51c87b8861cf5`
- Executor version: `0.4.3-rollback-runtime`
- Installed Executor main SHA-256: `f0804521437a4d43db79aafd96928a15978f1d79393b1376be17b7a3907f37c0`
- Installed Executor collector SHA-256: `dff91265a5e3e80704277664f1952129ff19c6c7174d78e9b3e66125b9618ccc`

The Executor main and collector digests above are the ones installed on
HK-STAGING-01 as of the 2026-09-17 controlled canary-delivery change, which gave
both production runners the calling convention the sealed-artifact reader calls
them through. Earlier values (`b9aea31e…` / `2b05e3a7…`, and before them
`323c30a7…` / `a0eeda9e…`) are kept in the change record, not here.

The Executor's four runtime modules are included under `source/executor/runtime/` and were independently hash-verified before archival.

## Secrets deliberately excluded

This archive does **not** contain private/signing/SSH key material, runtime `.env` values, passwords, API tokens, database contents, cookies/sessions, container logs, caches, or virtual environments. Runtime environment metadata records only the file SHA-256 and variable names in the audit/baseline documentation.

One secret scan hit in `source/agent/hk_agent/agent053_regression.py` is an intentional test fixture containing only a private-key **header marker**; a complete private-key block is absent. It was classified as a false positive and retained because modifying it would alter the Agent regression source.

## Change control

Planned permanent changes are governed by [`../docs/governance/CHANGE_CONTROL_POLICY.md`](../docs/governance/CHANGE_CONTROL_POLICY.md): use a short-lived branch and Pull Request; normal work must not write directly to `main`. A topology change requires a new reviewed topology version rather than silent expansion of the current eight-service deployment scope.

## Authority

This repository is a source/configuration archive. It is **not Execution Authority**. Live state, Human Approval where required, Signed Tasks, installed artifacts, durable deployment records, and Signed Evidence remain authoritative.
