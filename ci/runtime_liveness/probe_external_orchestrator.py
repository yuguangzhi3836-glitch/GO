#!/usr/bin/env python3
"""Actively fetch and validate a fresh Cell lease snapshot from an external orchestrator."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import secrets
import tempfile
from urllib import parse, request

from validate_runtime_liveness import instant, validate

SCHEMA = "go.cell-orchestrator-snapshot.v1"
MAX_RESPONSE_BYTES = 1024 * 1024


class ProbeError(ValueError):
    pass


def _utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_state(path: Path) -> dict | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as error:
        raise ProbeError(f"invalid durable probe state: {error}") from error
    if not isinstance(value, dict):
        raise ProbeError("invalid durable probe state")
    return value


def _save_state(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        try:
            os.unlink(name)
        except FileNotFoundError:
            pass


def verify_envelope(payload: object, *, challenge: str, now: datetime,
                    previous: dict | None, max_snapshot_age_seconds: int) -> dict:
    if not isinstance(payload, dict) or payload.get("schema") != SCHEMA:
        raise ProbeError("unexpected orchestrator snapshot schema")
    for field in ("orchestrator_id", "snapshot_id", "challenge"):
        if not isinstance(payload.get(field), str) or not payload[field].strip():
            raise ProbeError(f"missing {field}")
    if not secrets.compare_digest(payload["challenge"], challenge):
        raise ProbeError("challenge mismatch; cached/static response rejected")
    sequence = payload.get("sequence")
    if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1:
        raise ProbeError("sequence must be a positive integer")
    try:
        generated_at = instant(payload["generated_at"])
    except (KeyError, TypeError, ValueError) as error:
        raise ProbeError(f"invalid generated_at: {error}") from error
    if generated_at > now + timedelta(seconds=5):
        raise ProbeError("snapshot generated_at is in the future")
    if now - generated_at > timedelta(seconds=max_snapshot_age_seconds):
        raise ProbeError("snapshot is stale")
    if previous:
        previous_sequence = previous.get("sequence")
        if (not isinstance(previous.get("orchestrator_id"), str)
                or not isinstance(previous.get("snapshot_id"), str)
                or isinstance(previous_sequence, bool) or not isinstance(previous_sequence, int)
                or previous_sequence < 1):
            raise ProbeError("invalid durable probe state fields")
        if payload["orchestrator_id"] != previous.get("orchestrator_id"):
            raise ProbeError("orchestrator identity changed")
        if sequence <= previous_sequence:
            raise ProbeError("snapshot sequence replay or rollback")
        if payload["snapshot_id"] == previous.get("snapshot_id"):
            raise ProbeError("snapshot_id replay")
    result = dict(payload)
    result["observed_at"] = _utc(now)
    return result


def fetch_snapshot(url: str, *, challenge: str, timeout_seconds: float,
                   token: str | None, allow_http_loopback: bool = False) -> object:
    parsed = parse.urlparse(url)
    loopback = parsed.hostname in {"127.0.0.1", "::1", "localhost"}
    if parsed.scheme != "https" and not (allow_http_loopback and parsed.scheme == "http" and loopback):
        raise ProbeError("orchestrator URL must use HTTPS")
    if not token and not (allow_http_loopback and loopback):
        raise ProbeError("orchestrator bearer token is required")
    body = json.dumps({"schema": "go.cell-liveness-probe.v1", "challenge": challenge}).encode()
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = request.Request(url, data=body, headers=headers, method="POST")
    try:
        with request.urlopen(req, timeout=timeout_seconds) as response:
            data = response.read(MAX_RESPONSE_BYTES + 1)
    except OSError as error:
        raise ProbeError(f"orchestrator request failed: {error}") from error
    if len(data) > MAX_RESPONSE_BYTES:
        raise ProbeError("orchestrator response too large")
    try:
        return json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ProbeError(f"orchestrator returned invalid JSON: {error}") from error


def run_probe(url: str, state_file: Path, *, now: datetime | None = None,
              timeout_seconds: float = 10, max_snapshot_age_seconds: int = 30,
              max_heartbeat_age_seconds: int = 120, token: str | None = None,
              challenge: str | None = None, allow_http_loopback: bool = False) -> dict:
    if timeout_seconds <= 0 or max_snapshot_age_seconds <= 0 or max_heartbeat_age_seconds <= 0:
        raise ProbeError("probe timeout and freshness limits must be positive")
    observed = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    nonce = challenge or secrets.token_hex(32)
    previous = _load_state(state_file)
    payload = fetch_snapshot(url, challenge=nonce, timeout_seconds=timeout_seconds,
                             token=token, allow_http_loopback=allow_http_loopback)
    snapshot = verify_envelope(payload, challenge=nonce, now=observed, previous=previous,
                               max_snapshot_age_seconds=max_snapshot_age_seconds)
    result = validate(snapshot, observed, max_heartbeat_age_seconds)
    _save_state(state_file, {"orchestrator_id": snapshot["orchestrator_id"],
                             "snapshot_id": snapshot["snapshot_id"],
                             "sequence": snapshot["sequence"],
                             "generated_at": snapshot["generated_at"],
                             "observed_at": snapshot["observed_at"],
                             "gate": result["gate"]})
    result.update({"orchestrator_id": snapshot["orchestrator_id"],
                   "snapshot_id": snapshot["snapshot_id"],
                   "sequence": snapshot["sequence"]})
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=os.environ.get("GO_CELL_ORCHESTRATOR_URL"))
    parser.add_argument("--token-env", default="GO_CELL_ORCHESTRATOR_TOKEN")
    parser.add_argument("--state-file", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=float, default=10)
    parser.add_argument("--max-snapshot-age-seconds", type=int, default=30)
    parser.add_argument("--max-heartbeat-age-seconds", type=int, default=120)
    args = parser.parse_args()
    try:
        if not args.url:
            raise ProbeError("GO_CELL_ORCHESTRATOR_URL or --url is required")
        result = run_probe(args.url, args.state_file, timeout_seconds=args.timeout_seconds,
                           max_snapshot_age_seconds=args.max_snapshot_age_seconds,
                           max_heartbeat_age_seconds=args.max_heartbeat_age_seconds,
                           token=os.environ.get(args.token_env))
    except (ProbeError, OSError, ValueError) as error:
        result = {"gate": "SCHEDULER_FAIL", "reason": "ORCHESTRATOR_UNAVAILABLE_OR_INVALID",
                  "all_cells_exited": None, "errors": [str(error)],
                  "meaning": "No live executor claim is admitted when the external orchestrator probe fails."}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["gate"] == "PASS_SCOPED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
