#!/usr/bin/env python3
import json
import os
import sys
import urllib.request

base = os.getenv("STAGING_BASE_URL", "http://localhost:8000").rstrip("/")
checks = ["/health", "/metrics"]
if os.getenv("STAGING_ADMIN_TOKEN"):
    checks.append("/internal/v1/ops/readiness")
failed = []
for path in checks:
    try:
        req=urllib.request.Request(base + path)
        if os.getenv("STAGING_ADMIN_TOKEN"):
            req.add_header("Authorization", "Bearer " + os.environ["STAGING_ADMIN_TOKEN"])
        with urllib.request.urlopen(req, timeout=5) as r:
            body = r.read().decode("utf-8", "replace")
            print(path, r.status, body[:160].replace("\n", " "))
            if r.status >= 400:
                failed.append(path)
    except Exception as e:
        print(path, "ERROR", repr(e))
        failed.append(path)
if failed:
    print("STAGING_SMOKE=FAIL", json.dumps(failed))
    sys.exit(1)
print("STAGING_SMOKE=PASS")
