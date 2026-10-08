# HK-STAGING active business runtime

This directory holds the **canonical, GitHub-reproducible** definition of the
business runtime that is currently active on HK-STAGING-01.

It is not a plan, not a candidate, and not historical evidence: the definitions
here are the runtime definition that is active now. What the host is *actually* running is established
from the newest signed VERIFY Evidence for HK-STAGING on the evidence bus
(`chenzhenxi1-sudo/go-control-evidence`); this repository declares no runtime pointer.
The pointer that used to stand here
(`docs/canonical-baseline/CURRENT_HK_RUNTIME.json`) was retired on 2026-10-08.

## Files

| File | Purpose |
| --- | --- |
| `docker-compose.business-runtime.yml` | The 8 business services (`api` + 7 workers). Protected non-targets are deliberately absent. |
| `RUNTIME_ENV_CONTRACT.md` | Sanitized environment key contract (no values). |

The image build definition is [`application/Dockerfile`](../../application/Dockerfile).
The build context is `application/`.

## Orientation in 60 seconds

```text
business source   application/                       (Python + alembic + frontend + workers)
build definition  application/Dockerfile             docker build -t <tag> application/
compose           deploy/hk-staging/docker-compose.business-runtime.yml
env contract      deploy/hk-staging/RUNTIME_ENV_CONTRACT.md
runtime state     newest signed VERIFY Evidence on chenzhenxi1-sudo/go-control-evidence
```

## Build

```sh
git clone https://github.com/yuguangzhi3836-glitch/GO.git
cd GO
docker build -t go-hotel:depth48-runtime application/
```

No host-side files, previous parent, sealed package, or release tree is required.
This was verified by a fresh GitHub-only checkout build, whose recorded result used to
live in the retired `docs/canonical-baseline/CURRENT_HK_RUNTIME.json`
(`fresh_checkout_build`).

## Run

```sh
export GO_RUNTIME_ENV_FILE=/path/to/runtime.env        # host-owned, never committed
export GO_BUSINESS_IMAGE_TAG=go-hotel:depth48-runtime

docker compose -p go-822-staging \
  --env-file "$GO_RUNTIME_ENV_FILE" \
  -f deploy/hk-staging/docker-compose.business-runtime.yml \
  up -d --no-deps \
  api outbox-worker recovery-worker reconciliation-worker \
  judgment-worker mobile-engagement-worker \
  mobile-push-worker mobile-push-receipt-worker
```

`--no-deps` plus an explicit service list is deliberate: a business cutover must
never recreate the protected non-targets.

## Protected non-targets (do not stop, remove, or recreate as part of a business cutover)

`caddy` · `redis` · PostgreSQL/RDS business data · persistent media volumes ·
HK Agent · Executor · signing keys · Task/Evidence/ledger · Control Plane
authority data · SSH access and key material.

## Smoke

```sh
curl -fsS http://127.0.0.1:8000/health
# {"status":"ok","service":"go-hotel-platform"}

docker run --rm --entrypoint python <tag> -c \
  "from alembic.config import Config; from alembic.script import ScriptDirectory; \
   print(ScriptDirectory.from_config(Config('/app/alembic.ini')).get_heads())"
# prints the migration heads of the image under test - read them from that run
```

## Database

**This repository does not assert the live database revision.** Read it from the
newest signed VERIFY Evidence for HK-STAGING
(`chenzhenxi1-sudo/go-control-evidence`) - that is the only thing that says what
the host is running.

Forward migration only. Never drop, reset, or destructively downgrade the
business database.

**Deployment and inspection go through GO Forge**, not by hand. See the repository
root [`AGENTS.md`](../../AGENTS.md) (AI) and [`README.md`](../../README.md) (human).
Do not run `HK_STAGING_*` actions unless the Owner explicitly authorizes Old
Command Center fallback mode.

## Superseded, and not to be confused with this runtime

| Item | Status |
| --- | --- |
| `hk-staging/` (2026-09-11 snapshot) | Historical snapshot of the previous HK runtime generation. Not active. |
| `CP11_DEPTH46_CONSOLIDATED_PARENT_20260913` | Superseded historical runtime parent. |
| `CP11_DEPTH48_SOURCE_COMPOSITE_PARENT_20260913` | Source input / assembly artifact. Its inner image is **not** a business runtime image. |
| old `R3.x` HK runtime images | Superseded, removed from the host. |
