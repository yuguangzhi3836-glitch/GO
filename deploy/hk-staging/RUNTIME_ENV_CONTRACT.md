# HK-STAGING business runtime — sanitized environment contract

This file records the **shape** of the runtime environment only. It contains no
values. It exists so that a fresh session can know which environment keys the
business runtime needs without reading the host's `runtime.env`.

- Runtime env file on HK-STAGING-01 (path only, values not archived):
  `/home/go-stg/control/r317-five-star-completeness-20260828/runtime.env`
- Declared in code: `application/src/go_hotel/core/config.py` (`class Settings`,
  `pydantic-settings`, field name -> `UPPER_SNAKE` env key).
- **Never commit the env file, any value from it, or a rendered copy.**

## A. Application keys (declared in `core/config.py`)

| Env key | Config field | Required | Notes |
| --- | --- | --- | --- |
| `APP_ENV` | `app_env` | yes | `staging` on HK-STAGING-01 |
| `DATABASE_URL` | `database_url` | yes | SQLAlchemy URL; must be a secret-bearing value, never committed |
| `REDIS_URL` | `redis_url` | yes | queue/transport backend |
| `OUTBOX_TRANSPORT` | `outbox_transport` | yes | `redis` on HK-STAGING-01 |
| `JWT_SIGNING_KEY` | `jwt_signing_key` | yes | secret |
| `CONNECTOR_VAULT_MASTER_KEY` | `connector_vault_master_key` | yes | secret |
| `WEBHOOK_SECRET` | `webhook_secret` | yes | secret |
| `COOKIE_SECURE` | `cookie_secure` | yes | `false` on HK-STAGING-01 (loopback TLS terminated by Caddy) |
| `MFA_REQUIRED_FOR_ADMIN` | `mfa_required_for_admin` | yes | `true` on HK-STAGING-01 |
| `MOBILE_PUSH_MODE` | `mobile_push_mode` | yes | `mock` on HK-STAGING-01 |
| `BOOTSTRAP_ADMIN_USERNAME` | `bootstrap_admin_username` | yes | not a secret |
| `BOOTSTRAP_ADMIN_PASSWORD` | `bootstrap_admin_password` | yes | secret; default values are rejected by the runtime preflight gates |
| `BOOTSTRAP_SUPPLIER_USERNAME` | `bootstrap_supplier_username` | yes | not a secret |
| `BOOTSTRAP_SUPPLIER_PASSWORD` | `bootstrap_supplier_password` | yes | secret; default values are rejected |
| `BOOTSTRAP_SUPPLIER_ID` | `bootstrap_supplier_id` | yes | not a secret |
| `GO_AI_PROVIDERS_JSON` | `go_ai_providers_json` | optional | provider *references* (env-var names), not raw keys |
| `GO_FIRECRAWL_API_KEY` | — (consumed by media-discovery scripts) | optional | secret |
| `GO_HOTEL_REGION_DISCOVERY_PROVIDERS_JSON` | — | optional | region discovery providers |
| `GO_HOTEL_REGION_DISCOVERY_BOOTSTRAP_OSM` | — | optional | OSM bootstrap toggle |
| `GO_HOTEL_REGION_DISCOVERY_OSM_ENDPOINT` | — | optional | endpoint URL |

## B. Keys inherited from the `python:3.12-slim` base image

Present in the container environment but not application configuration:
`LANG`, `PATH`, `PYTHONPATH` (set to `/app/src` by the image),
`PYTHON_VERSION`, `PYTHON_SHA256`, `GPG_KEY`.

## C. Values supplied by the Compose definition, not the env file

- `PYTHONPATH=/app/src` (api service) — the image also sets this.
- `AOLUGUYA_DIRECT_TEST_MODE`, `AOLUGUYA_REAL_INVENTORY_CONFIGURED`,
  `AOLUGUYA_REAL_RATE_CONFIGURED`, `AOLUGUYA_REAL_PAYMENT_CONFIGURED` —
  HK-STAGING keeps real supplier inventory/rate/payment disabled.

## D. Secret handling

- The env file lives on the host only. It is referenced by path through
  `GO_RUNTIME_ENV_FILE`. It is never copied into this repository, into an image
  layer, into evidence, or into PR text.
- Only key names, paths, and non-secret fingerprints may be recorded here or in any
  repository document. The retired `docs/canonical-baseline/CURRENT_HK_RUNTIME.json`,
  which used to be one of those documents, was removed on 2026-10-08.
