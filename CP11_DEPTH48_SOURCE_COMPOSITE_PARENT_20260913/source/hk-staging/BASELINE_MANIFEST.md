# HK-STAGING archive baseline — 2026-09-11

- Environment: `HK-STAGING-01`
- Host observed: `iZj6ccs8t04f1p4d8pe69zZ`
- Business image: `sha256:66c540878ff5dd8d2d089059288c3d9f0c45f880514f7b053bd50defb9e8c324`
- Business image tag: `go-hotel:aoluguya-direct-r3-1-20260906`
- Runtime source file count: `577`
- Runtime source manifest SHA-256: `2c2606a33c5b124062c5ea99b7f2431d2714fd8e453529549431c84205087022`
- Current host build-context file count: `577`
- Current host build-context manifest SHA-256: `3dd3cd35985f24b55b87c8793dff010c2b23269b9b6d12a5367d14eeb8c30c7d`
- Runtime-vs-host common files: `577`
- Runtime-vs-host byte-identical: `576`
- Runtime-vs-host differing files: `1`
- Compose SHA-256: `7ef4ab181c1250d8cec0e348b29c24bfbb8e5dce4fc2a57f6faaa59363c26895`
- Runtime env path: `/home/go-stg/control/r317-five-star-completeness-20260828/runtime.env`
- Runtime env SHA-256: `6682ff61f336fb8ff95a6585e9133c88c52a4eaa440a7aea6a6e06f771e607fc`
- Runtime env values archived: `NO`
- Agent: `0.5.7-rebuilt`
- Agent source manifest SHA-256 (archive including entrypoint): `09beaf8af8b690276d9421b1b344e94422e261e897448f76e59b75722ce391a8`
- Executor: `0.4.3-rollback-runtime`
- Executor source manifest SHA-256: `cd25e9a4d84a7d32e22627e36156e8b3805a7864e83257fb01cbc4cf82bb0506`
- Runtime mutation during inventory: `NO`
- Container restart during inventory: `NO`
- Image build during inventory: `NO`
- Deploy during inventory: `NO`

Fixed eight business targets: `api`, `recovery-worker`, `outbox-worker`, `mobile-push-receipt-worker`, `reconciliation-worker`, `mobile-push-worker`, `mobile-engagement-worker`, `judgment-worker`. Redis and Caddy are non-targets.
