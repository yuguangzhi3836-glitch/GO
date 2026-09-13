# GO HK-STAGING business runtime image
#
# This is the canonical, GitHub-reproducible runtime build definition for the
# current active HK-STAGING business runtime (DEPTH48).
#
# It is derived from the proven HK-STAGING runtime pattern that was previously
# only present on the server and in the historical `hk-staging/source/runtime/`
# snapshot. The build logic below is the logic that was actually validated on
# HK-STAGING-01 on 2026-09-13 (image `go-hotel:depth48-runtime-6d0fd905`).
#
# Build context is this directory (`application/`), so from a fresh clone:
#
#   docker build -t go-hotel:depth48-runtime application/
#
# Startup model:
#   uvicorn go_hotel.main:app --host 0.0.0.0 --port 8000   (HTTP :8000, /health)
# Worker services reuse the same image with an explicit module entrypoint,
# e.g. `python -m go_hotel.workers.outbox_worker`. See
# `deploy/hk-staging/docker-compose.business-runtime.yml`.
#
# Dependency model: `pyproject.toml` declares the full runtime dependency set,
# including `uvicorn[standard]` (uvloop/httptools/websockets) which the runtime
# requires and which was previously only added by an ad-hoc build command.

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY . .

RUN pip install --no-cache-dir -e ".[dev]"

ENV PYTHONPATH=/app/src

EXPOSE 8000

CMD ["uvicorn", "go_hotel.main:app", "--host", "0.0.0.0", "--port", "8000"]
