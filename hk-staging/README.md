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
- Installed Executor main SHA-256: `323c30a7dda9bfa86c45a505854022ee161ef85b3bf41673c018987c88028388`

The Executor's four runtime modules are included under `source/executor/runtime/` and were independently hash-verified before archival.

## Secrets deliberately excluded

This archive does **not** contain private/signing/SSH key material, runtime `.env` values, passwords, API tokens, database contents, cookies/sessions, container logs, caches, or virtual environments. Runtime environment metadata records only the file SHA-256 and variable names in the audit/baseline documentation.

One secret scan hit in `source/agent/hk_agent/agent053_regression.py` is an intentional test fixture containing only a private-key **header marker**; a complete private-key block is absent. It was classified as a false positive and retained because modifying it would alter the Agent regression source.

## Authority

This repository is a source/configuration archive. It is **not Execution Authority**. Live state, Human Approval where required, Signed Tasks, installed artifacts, durable deployment records, and Signed Evidence remain authoritative.
