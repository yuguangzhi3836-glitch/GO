#!/usr/bin/env python3
"""Independently recompute existing GO three-surface load evidence. No network."""
from __future__ import annotations
import argparse
import bisect
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
import re
from pathlib import Path

ROLES = ("consumer", "supplier", "admin")
EXPECTED_SHA = "96721782158b5d665f7723305e5fb2212bd256ae"
EXPECTED_HARNESS = "3b6dd0532b71c08e1b9e0b0ab838c8d2607c9ae720a0037e1f273ca07a2dcde7"
EXPECTED_IMAGE = "sha256:6c005a88ec772ac971e560e5f29d0cfa6a8354bb16e0d52d9cbefef0def1dfe1"


def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def read_lines(p):
    if not p.exists():
        raise ValueError("MISSING_EVIDENCE:" + p.name)
    out = []
    with p.open() as stream:
        for number, line in enumerate(stream, 1):
            if line.strip():
                try:
                    value = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"INVALID_NDJSON:{p.name}:{number}") from exc
                if not isinstance(value, dict):
                    raise ValueError(f"NON_OBJECT_NDJSON:{p.name}:{number}")
                out.append(value)
    return out


def timestamp(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000


def percentile(values, fraction):
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * fraction) - 1)] if ordered else None


def natural(row):
    return row.get("client_aborted") is not True


def successful(row):
    return (row.get("status") == 200 and row.get("semantic_ok") is True
            and row.get("response_request_id") == row.get("request_id"))


def summarize(rows):
    durations = [r["elapsed_ms"] for r in rows]
    failed = sum(not successful(r) for r in rows)
    return {
        "requests": len(rows), "errors": failed,
        "error_rate": failed / len(rows) if rows else None,
        "semantic_errors": sum(r.get("status") == 200 and r.get("semantic_ok") is not True for r in rows),
        "request_id_echo_errors": sum(r.get("status") == 200 and r.get("response_request_id") != r.get("request_id") for r in rows),
        "p50_ms": percentile(durations, .5), "p95_ms": percentile(durations, .95),
        "p99_ms": percentile(durations, .99),
        "statuses": dict(Counter(str(r.get("status")) for r in rows)),
        "error_codes": dict(Counter(r.get("error_code") or "UNSPECIFIED" for r in rows if not successful(r))),
    }


def gate(s):
    return bool(s["requests"] and s["p95_ms"] <= 2000 and s["p99_ms"] <= 5000
                and s["error_rate"] <= .01 and s["semantic_errors"] == 0)


def same(value, other):
    if isinstance(value, (int, float)) and isinstance(other, (int, float)):
        return math.isclose(value, other, abs_tol=1e-8, rel_tol=1e-8)
    return value == other


def compare_statistics(computed, reported):
    keys = ("requests", "errors", "error_rate", "semantic_errors", "p50_ms", "p95_ms", "p99_ms", "statuses")
    return {key: {"computed": computed[key], "reported": reported.get(key)}
            for key in keys if not same(computed[key], reported.get(key))}


def expected_allocation(total):
    c, s = math.floor(total * .7 + .5), math.floor(total * .15 + .5)
    return dict(zip(ROLES, (c, s, total - c - s)))


def max_in_flight_bounds(rows):
    # Millisecond timestamps cannot resolve the ordering of equal-time events.
    events = defaultdict(lambda: [0, 0])
    for row in rows:
        events[row["started_ms"]][0] += 1
        events[row["finished_ms"]][1] += 1
    current = low = high = 0
    for at, (starts, finishes) in sorted(events.items()):
        high = max(high, current + starts)
        current += starts - finishes
        low = max(low, current)
    return {"lower_bound": low, "upper_bound": high, "resolution": "millisecond_event_order_bounds"}


def host_summary(host, start, end):
    relevant = [r for r in host if start - 15000 <= r["_at_ms"] <= end + 5000]
    times = [r["_at_ms"] for r in relevant]
    memories, cpus, connections, active_connections, pending = [], defaultdict(list), [], [], []
    for row in relevant:
        available = row.get("host", {}).get("memory_bytes", {}).get("MemAvailable")
        if isinstance(available, (int, float)):
            memories.append(available)
        for item in row.get("stats", []):
            try:
                cpus[item.get("Name", "unknown")].append(float(str(item.get("CPUPerc", "")).rstrip("%")))
            except (TypeError, ValueError):
                pass
        db = row.get("database") or {}
        if isinstance(db.get("connections"), list):
            connections.append(sum(int(x.get("n", 0)) for x in db["connections"]))
            active_connections.append(sum(int(x.get("n", 0)) for x in db["connections"] if x.get("state") == "active"))
        for item in db.get("outbox", []):
            if str(item.get("status", "")).upper() in {"PENDING", "RETRY", "PROCESSING", "INFLIGHT"}:
                pending.append(int(item.get("n", 0)))
    return {
        "sample_count": len(relevant), "window_includes_seconds_before": 15,
        "window_includes_seconds_after": 5,
        "first_sample_at": relevant[0].get("at") if relevant else None,
        "last_sample_at": relevant[-1].get("at") if relevant else None,
        "maximum_gap_ms": max((b-a for a, b in zip(times, times[1:])), default=None),
        "unhealthy_observations": [{"at": r.get("at"), "reason": r.get("reason")} for r in relevant if r.get("healthy") is not True],
        "min_available_memory_bytes": min(memories, default=None),
        "peak_container_cpu_percent": {name: max(values) for name, values in cpus.items()},
        "peak_database_connections": max(connections, default=None),
        "peak_database_active_connections": max(active_connections, default=None),
        "peak_single_pending_outbox_status_count": max(pending, default=None),
        "interpretation": "Temporal association only; no root-cause attribution from coincidence.",
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--evidence", type=Path, required=True)
    ap.add_argument("--host", type=Path, help="Raw host-telemetry.ndjson; defaults inside evidence")
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--expected-harness", default=EXPECTED_HARNESS,
                    help="Independent reviewed harness SHA256; defaults to the reviewed run01 version, never inferred from the run report")
    args = ap.parse_args()
    if not re.fullmatch(r"[a-f0-9]{64}", args.expected_harness):
        ap.error("--expected-harness must be a lowercase SHA256 from an independent review receipt")
    root = args.evidence.resolve()
    report_file, requests_file, activity_file = (root/n for n in ("report.json", "requests.ndjson", "activity.ndjson"))
    report = json.loads(report_file.read_text())
    rows, activity = read_lines(requests_file), read_lines(activity_file)
    host_file = args.host or root/"host-telemetry.ndjson"
    host = read_lines(host_file) if host_file.exists() else []
    for row in host:
        row["_at_ms"] = timestamp(row["at"])
    host.sort(key=lambda x: x["_at_ms"])
    host_times = [x["_at_ms"] for x in host]
    manifest_results = {}
    if (root/"sha256.json").exists():
        manifest = json.loads((root/"sha256.json").read_text())
        for name, declared in manifest.items():
            target = (root/name).resolve()
            if root not in target.parents:
                raise ValueError("UNSAFE_MANIFEST_PATH")
            manifest_results[name] = {"exists": target.is_file(), "matches": target.is_file() and digest(target) == declared}
    ids = [r["request_id"] for r in rows]
    recomputed = {
        "schema": "go.c13.independent-load-recompute.v1", "at": datetime.now(timezone.utc).isoformat(),
        "run_id": report.get("run_id"), "network_requests": 0,
        "inputs": {str(p): digest(p) for p in (report_file, requests_file, activity_file, host_file) if p.is_file()},
        "manifest_results": manifest_results,
        "input_manifest_present": (root/"sha256.json").exists(),
        "independently_expected_harness_sha256": args.expected_harness,
        "harness_sha_matches_reviewed_version": report.get("harness_sha256") == args.expected_harness,
        "identity_declarations": report.get("identity"),
        "expected_identity_declarations_match": report.get("identity", {}).get("source_sha") == EXPECTED_SHA and report.get("identity", {}).get("image") == EXPECTED_IMAGE and report.get("identity", {}).get("db_head") == "0137_hosted_unknown_episode",
        "raw_request_rows": len(rows), "duplicate_request_ids": len(ids) - len(set(ids)),
        "stored_ok_disagrees_with_fields": sum(bool(r.get("ok")) != successful(r) for r in rows),
        "invalid_request_time_rows": sum(r["finished_ms"] < r["started_ms"] for r in rows),
        "active_user_evidence_limit": "Distinct VU aliases and request outcomes are recomputed. Raw bodies are intentionally omitted; distinct actual user_ids/session IDs and response semantic judgments cannot be independently rederived from hashes alone.",
        "declared_account_population": report.get("account_population"),
        "phase_statistics": {p: summarize([r for r in rows if r.get("phase") == p and natural(r)]) for p in sorted({r.get("phase", "unknown") for r in rows})},
        "authenticated_vu_requests": {}, "stages": [], "discrepancies": [],
        "maximum_in_flight_recomputed_bounds": max_in_flight_bounds(rows),
    }
    for role in ROLES:
        rr = [r for r in rows if r.get("role") == role]
        recomputed["authenticated_vu_requests"][role] = {
            "successful_login_aliases": len({r["vu"] for r in rr if r.get("phase") == "login" and successful(r)}),
            "successful_identity_check_aliases": len({r["vu"] for r in rr if r.get("phase") == "identity" and successful(r)}),
            "successful_logout_aliases": len({r["vu"] for r in rr if r.get("phase") == "cleanup" and successful(r)}),
        }
    for declared in report.get("stages", []):
        vus = declared["vus"]
        start = declared.get("steady_started_ms")
        target_ms = declared.get("requested_steady_seconds", declared.get("seconds", 0)) * 1000
        deadline = declared.get("deadline_ms")
        stage_finished = timestamp(declared["finished_at"]) if declared.get("finished_at") else None
        stop = timestamp(report["stopped_at"]) if report.get("stopped_at") else None
        candidates = [x for x in (deadline, stage_finished, stop) if x is not None]
        end = min(candidates) if candidates else start
        selected = [r for r in rows if r.get("stage") == vus and r.get("phase") in {"load", "ramp"}]
        stable = [r for r in selected if start is not None and end is not None and start <= r["started_ms"] < end and natural(r)]
        ramp = [r for r in selected if natural(r) and (start is None or r["started_ms"] < start)]
        full = [r for r in selected if natural(r)]
        secs = max(0, (end-start)/1000) if start is not None and end is not None else 0
        counts = expected_allocation(vus)
        samples = [a for a in activity if a.get("stage") == vus and start is not None and end is not None and start <= a.get("at_ms", timestamp(a["at"])) < end]
        sample_times = sorted(a.get("at_ms", timestamp(a["at"])) for a in samples)
        active_matches = all(a.get("active_vus") == counts for a in samples)
        out = {
            "vus": vus, "expected_allocation": counts, "steady_start_ms": start, "effective_end_ms": end,
            "requested_seconds": target_ms/1000, "effective_steady_seconds": secs,
            "activity_samples": len(samples), "all_sampled_role_counts_match": active_matches,
            "first_activity_offset_ms": sample_times[0]-start if sample_times else None,
            "last_activity_gap_to_end_ms": end-sample_times[-1] if sample_times else None,
            "maximum_activity_sampling_gap_ms": max((b-a for a,b in zip(sample_times,sample_times[1:])), default=None),
            "observed_peak_active_by_role": {role: max((a.get("active_vus", {}).get(role, 0) for a in samples), default=0) for role in ROLES},
            "natural_tail_completions_after_steady_end": sum(r["finished_ms"] > end for r in stable) if end else 0,
            "ramp_natural_completions_after_steady_start": sum(r["finished_ms"] > start for r in ramp) if start else 0,
            "stage_client_aborted_requests": sum(not natural(r) for r in selected),
            "ramp_client_aborted_requests": sum(not natural(r) and (start is None or r["started_ms"] < start) for r in selected),
            "ramp_summary": summarize(ramp), "full_stage_summary": summarize(full),
            "ramp_per_role": {role: summarize([r for r in ramp if r.get("role") == role]) for role in ROLES},
            "full_stage_per_role": {role: summarize([r for r in full if r.get("role") == role]) for role in ROLES},
            "summary": summarize(stable), "per_role": {}, "per_kind": {},
            "reported_passed": declared.get("passed"),
        }
        for role in ROLES:
            rr = [r for r in stable if r.get("role") == role]
            s = summarize(rr)
            s["successful_distinct_vus"] = len({r["vu"] for r in rr if successful(r) and r["finished_ms"] <= end})
            s["rps"] = sum(r["finished_ms"] <= end for r in rr)/secs if secs else 0
            s["thresholds_passed"] = gate(s)
            out["per_role"][role] = s
            diff = compare_statistics(s, declared.get("per_role", {}).get(role, {}))
            if not same(s["successful_distinct_vus"], declared.get("per_role", {}).get(role, {}).get("successful_distinct_vus")):
                diff["successful_distinct_vus"] = {"computed": s["successful_distinct_vus"], "reported": declared.get("per_role", {}).get(role, {}).get("successful_distinct_vus")}
            if not same(s["rps"], declared.get("per_role", {}).get(role, {}).get("rps")):
                diff["rps"] = {"computed": s["rps"], "reported": declared.get("per_role", {}).get(role, {}).get("rps")}
            if diff:
                recomputed["discrepancies"].append({"stage": vus, "role": role, "statistics": diff})
        for kind in sorted({r["kind"] for r in stable}):
            out["per_kind"][kind] = summarize([r for r in stable if r["kind"] == kind])
        out["recomputed_stage_passed"] = (not declared.get("stop_reason") and secs >= target_ms/1000
            and len(samples) >= target_ms/1000-2 and active_matches and gate(out["summary"])
            and all(s["thresholds_passed"] and s["successful_distinct_vus"] == counts[role] for role,s in out["per_role"].items()))
        if report.get("load_profile") == "ARRIVAL_RAMP_THEN_FULL_POPULATION_STEADY_V2":
            out["ramp_passed"] = all(not s["requests"] or gate(s) for s in out["ramp_per_role"].values())
            out["full_stage_passed"] = gate(out["full_stage_summary"]) and all(gate(s) for s in out["full_stage_per_role"].values())
            out["recomputed_stage_passed"] = out["recomputed_stage_passed"] and out["ramp_passed"] and out["full_stage_passed"]
            for section in ("ramp_per_role", "full_stage_per_role"):
                for role, s in out[section].items():
                    s["thresholds_passed"] = gate(s) if s["requests"] or section == "full_stage_per_role" else None
                    declared_role = declared.get(section, {}).get(role, {})
                    delta = compare_statistics(s, declared_role)
                    if s["thresholds_passed"] != declared_role.get("passed"):
                        delta["passed"] = {"computed": s["thresholds_passed"], "reported": declared_role.get("passed")}
                    if delta:
                        recomputed["discrepancies"].append({"stage": vus, "section": section, "role": role, "statistics": delta})
            for flag in ("ramp_passed", "full_stage_passed"):
                if out[flag] != declared.get(flag):
                    recomputed["discrepancies"].append({"stage": vus, "section": flag, "computed": out[flag], "reported": declared.get(flag)})
        if out["recomputed_stage_passed"] != declared.get("passed"):
            recomputed["discrepancies"].append({"stage": vus, "pass_decision": {"computed": out["recomputed_stage_passed"], "reported": declared.get("passed")}})
        if not same(secs, declared.get("measured_steady_seconds")):
            recomputed["discrepancies"].append({"stage": vus, "steady_seconds": {"computed": secs, "reported": declared.get("measured_steady_seconds")}})
        diff = compare_statistics(out["summary"], declared.get("summary", {}))
        if diff:
            recomputed["discrepancies"].append({"stage": vus, "statistics": diff})
        for section in ("ramp_summary", "full_stage_summary"):
            if section in declared:
                delta = compare_statistics(out[section], declared[section])
                if delta:
                    recomputed["discrepancies"].append({"stage": vus, "section": section, "statistics": delta})
        if start is not None and end is not None:
            out["host"] = host_summary(host, start, end)
        recomputed["stages"].append(out)
    errors = [r for r in rows if r.get("phase") in {"load", "ramp"} and natural(r) and not successful(r)]
    examples = []
    for row in errors[:30]:
        pos = bisect.bisect_right(host_times, row["started_ms"]) - 1
        sample = host[pos] if pos >= 0 else None
        age = row["started_ms"] - sample["_at_ms"] if sample else None
        examples.append({k: row.get(k) for k in ("request_id", "role", "vu", "path", "kind", "status", "error_code", "started_at", "elapsed_ms")}
                        | {"preceding_host_sample_at": sample.get("at") if sample else None,
                           "host_sample_age_ms": age, "host_sample_within_15_seconds": age is not None and 0 <= age <= 15000,
                           "host_healthy": sample.get("healthy") if sample else None,
                           "host_reason": sample.get("reason") if sample else None})
    recomputed["first_failure_examples_with_host"] = examples
    recomputed["load_client_aborted_requests"] = sum(r.get("phase") in {"load", "ramp"} and not natural(r) for r in rows)
    recomputed["maximum_stage_passed"] = max((s["vus"] for s in recomputed["stages"] if s["recomputed_stage_passed"]), default=0)
    if report.get("mode") == "RUN" and report.get("maximum_stage_passed") != recomputed["maximum_stage_passed"]:
        recomputed["discrepancies"].append({"maximum_stage_passed": {"computed": recomputed["maximum_stage_passed"], "reported": report.get("maximum_stage_passed")}})
    recomputed["scoped_performance_1000_passed"] = recomputed["maximum_stage_passed"] == 1000 and not report.get("stop_reason")
    integrity_ok = (not recomputed["duplicate_request_ids"] and not recomputed["invalid_request_time_rows"]
                    and not recomputed["stored_ok_disagrees_with_fields"] and not recomputed["discrepancies"]
                    and all(x["matches"] for x in manifest_results.values()))
    recomputed["recomputation_consistent"] = integrity_ok
    recomputed["host_evidence_available"] = bool(host)
    recomputed["evidence_identity_eligible"] = integrity_ok and recomputed["harness_sha_matches_reviewed_version"] and recomputed["expected_identity_declarations_match"]
    recomputed["scope"] = "Authenticated protocol reads/searches only; no order, money, real browser or real-provider certification."
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(recomputed, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"output": str(args.output), "recomputation_consistent": integrity_ok,
                      "maximum_stage_passed": recomputed["maximum_stage_passed"],
                      "scoped_performance_1000_passed": recomputed["scoped_performance_1000_passed"],
                      "discrepancies": len(recomputed["discrepancies"]), "host_evidence_available": bool(host)}, ensure_ascii=False))
    # Successful analysis of a failed load run is a successful recomputation.
    return 0 if integrity_ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
