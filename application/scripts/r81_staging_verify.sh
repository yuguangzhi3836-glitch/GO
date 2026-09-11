#!/bin/sh
set -eu
BASE_URL=${BASE_URL:-https://staging-api.goaidirect.com}
PYTHON=${PYTHON:-python3}

echo "[R8.1] static package check"
test -f frontend/consumer/index.html
test -f frontend/supplier/index.html
test -f frontend/admin/index.html
grep -q "COPY frontend ./frontend" Dockerfile

echo "[R8.1] migration naming constraints"
$PYTHON scripts/r8_staging_static_gate.py

echo "[R8.1] HTTPS probes"
for path in /health /go-app/ /supplier-console/ /go-admin/; do
  code=$(curl -L -s -o /dev/null -w '%{http_code}' "$BASE_URL$path" || true)
  echo "$path -> $code"
  case "$code" in 200|301|302|307|308) ;; *) echo "R8.1_HTTPS_PROBE_FAILED:$path:$code"; exit 1;; esac
done

echo "R8.1_STAGING_HTTP_STATIC_VERIFY: PASS"
echo "NOTE: browser render + console inspection remains mandatory and is not proven by curl."
