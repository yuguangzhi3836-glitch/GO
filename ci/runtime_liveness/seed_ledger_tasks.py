#!/usr/bin/env python3
"""Idempotently seed only unfinished canonical Ledger tasks into the durable queue."""
import argparse
import json
from pathlib import Path

from durable_orchestrator import DurableOrchestrator, OrchestratorError, SOURCE_RE

ALLOWED = {"UNFINISHED", "DONE_SCOPED", "PASS", "BLOCKED_EXTERNAL"}


def seed(store: DurableOrchestrator, manifest: dict) -> dict:
    if not isinstance(manifest, dict) or manifest.get("schema") != "go.cell-ledger-seed.v1":
        raise OrchestratorError("invalid seed manifest schema")
    canonical = manifest.get("canonical_source_sha")
    if not isinstance(canonical, str) or not SOURCE_RE.fullmatch(canonical):
        raise OrchestratorError("invalid canonical_source_sha")
    tasks = manifest.get("tasks")
    if not isinstance(tasks, list):
        raise OrchestratorError("tasks must be a list")
    result = {"enqueued": [], "inherited_pass": [], "blocked_external": []}
    seen = set()
    for item in tasks:
        if not isinstance(item, dict):
            raise OrchestratorError("task entry must be an object")
        task_id, state = item.get("task_id"), item.get("state")
        if task_id in seen:
            raise OrchestratorError("duplicate task_id in seed manifest")
        seen.add(task_id)
        if state not in ALLOWED:
            raise OrchestratorError("invalid seed task state")
        source_sha = item.get("source_sha", canonical)
        if source_sha != canonical:
            raise OrchestratorError("seed task is not bound to canonical source")
        if state in {"DONE_SCOPED", "PASS"}:
            result["inherited_pass"].append(task_id)
            continue
        task = store.enqueue(task_id, item.get("cell_id"), source_sha, item.get("payload", {}))
        if state == "BLOCKED_EXTERNAL":
            store.block_external(task_id, item.get("evidence_sha256"),
                                 item.get("release_condition", ""))
            result["blocked_external"].append(task_id)
        else:
            result["enqueued"].append(task["task_id"])
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    result = seed(DurableOrchestrator(args.database), manifest)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
