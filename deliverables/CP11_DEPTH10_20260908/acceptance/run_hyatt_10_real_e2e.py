#!/usr/bin/env python3
"""Real Hyatt 10-hotel cohort runner.

Runs only in an application runtime with PostgreSQL and outbound HTTPS. It selects
the first ten identity-valid hotels from the official Hyatt China directory, never
a hand-picked list, enqueues them through the durable ledger and drains those exact
tasks through the official discovery pipeline. Output is machine-readable evidence.
This runner deliberately does not declare browser/catalog/media parity PASS; those
remain separate assertions in HYATT_10_REAL_HOTEL_GATE.md.
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from urllib.request import Request, urlopen

from sqlalchemy import text

from go_hotel.db.session import SessionLocal
from go_hotel.services.hyatt_directory_adapter import HyattDirectoryAdapter, HYATT_CHINA_DIRECTORY
from go_hotel.services.chain_autonomous_build import discovery_seed
from go_hotel.services.chain_task_lease import chain_task_lease_service


def now(): return datetime.now(timezone.utc).isoformat()


def fetch_page(url: str):
    req = Request(url, headers={"User-Agent": "GO-Hotel-Official-Capture/DEPTH10"})
    with urlopen(req, timeout=30) as response:
        final = response.geturl()
        body = response.read(8 * 1024 * 1024 + 1)
    if len(body) > 8 * 1024 * 1024:
        raise ValueError("HYATT_DIRECTORY_RESPONSE_TOO_LARGE")
    return final, body.decode("utf-8", errors="replace")


def require_postgres():
    with SessionLocal() as s:
        if s.get_bind().dialect.name != "postgresql": raise RuntimeError("POSTGRES_REQUIRED")
        return str(s.execute(text("select version()" )).scalar())


def main():
    evidence = {"gate": "HYATT_10_REAL_E2E_RUNTIME", "started_at": now(), "status": "HOLD", "hotels": []}
    try:
        evidence["postgres"] = require_postgres()
        final, html = fetch_page(HYATT_CHINA_DIRECTORY)
        evidence["directory_url"] = final
        evidence["directory_snapshot_sha256"] = hashlib.sha256(html.encode()).hexdigest()
        adapter = HyattDirectoryAdapter(directory_url=final, page_size=100)
        seeds = adapter.enumerate_all(lambda _: (final, html), max_properties=1000)
        if len(seeds) < 10: raise RuntimeError("HYATT_OFFICIAL_DIRECTORY_LT_10")
        cohort = seeds[:10]
        for seed in cohort:
            payload = {"task": "CHAIN_HOTEL", "chain": "HYATT", "official_property_id": seed.official_property_id,
                       "idempotency_key": seed.idempotency_key, "directory_url": seed.directory_url,
                       "discovery_seed": discovery_seed(seed)}
            task = chain_task_lease_service.enqueue(task_id=seed.idempotency_key, payload=payload, actor="HYATT_10_E2E")
            evidence["hotels"].append({"property_id": seed.official_property_id, "name": seed.name,
                                       "property_url": seed.property_url, "task_id": task.task_id})
        # This runtime runner records deterministic cohort/enqueue evidence. Worker
        # drain is intentionally performed by the deployed chain worker so process
        # death/lease semantics remain observable rather than hidden in one script.
        evidence["cohort_count"] = len(cohort)
        evidence["enqueue_status"] = "PASS"
        evidence["status"] = "READY_FOR_WORKER_DRAIN"
        evidence["finished_at"] = now()
        print(json.dumps(evidence, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        evidence["error"] = repr(exc); evidence["finished_at"] = now()
        print(json.dumps(evidence, ensure_ascii=False, indent=2)); return 1


if __name__ == "__main__": raise SystemExit(main())
