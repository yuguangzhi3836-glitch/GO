# Both official images use the same Debian release. Only the Node executable is
# needed by the native API contract tests; no npm credentials or host tools enter.
FROM node:22-bookworm-slim AS node
FROM python:3.12-slim-bookworm
RUN apt-get update \
    && apt-get install -y --no-install-recommends libstdc++6 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=node /usr/local/bin/node /usr/local/bin/node
RUN python --version && node --version \
    && node --experimental-strip-types -e 'console.log("C13_NODE_READY")'
