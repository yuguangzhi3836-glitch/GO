from __future__ import annotations

import json
from collections.abc import Mapping, Sequence


_REDACTED = "<redacted>"
_SENSITIVE_KEY_PARTS = (
    "authorization",
    "cookie",
    "credential",
    "dsn",
    "endpoint",
    "params",
    "password",
    "query",
    "secret",
    "sql",
    "statement",
    "token",
    "url",
)


def _is_sensitive_key(key: object) -> bool:
    return isinstance(key, str) and any(part in key.lower() for part in _SENSITIVE_KEY_PARTS)


def redact_payload(value):
    if isinstance(value, Mapping):
        return {
            key: _REDACTED if _is_sensitive_key(key) else redact_payload(item)
            for key, item in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [redact_payload(item) for item in value]
    return value


def summarize_failure(error, *, operation: str, sequence: int) -> dict[str, object]:
    if isinstance(error, BaseException):
        error_type = type(error).__name__
        business_error_code = _extract_business_error_code(error.args)
    elif isinstance(error, Mapping):
        error_type = str(error.get("error_type") or error.get("type") or "Error")
        business_error_code = _extract_business_error_code(
            (
                error.get("business_error_code"),
                error.get("code"),
                error.get("error_code"),
            )
        )
    else:
        error_type = type(error).__name__
        business_error_code = None
    summary = {
        "operation": operation,
        "sequence": sequence,
        "error_type": error_type,
    }
    if business_error_code:
        summary["business_error_code"] = business_error_code
    return summary


def _extract_business_error_code(values: Sequence[object]) -> str | None:
    for value in values:
        if not isinstance(value, str):
            continue
        candidate = value.strip()
        if not candidate or len(candidate) > 120:
            continue
        if any(ch.isspace() for ch in candidate):
            continue
        if any(ch.islower() for ch in candidate):
            continue
        if not any(ch.isalpha() for ch in candidate):
            continue
        return candidate
    return None


def audit_log_json(payload: Mapping[str, object]) -> str:
    return json.dumps(redact_payload(payload), ensure_ascii=True, indent=2, sort_keys=True)


def validate_profile(result: Mapping[str, object], *, operation: str, requested: int) -> list[str]:
    issues: list[str] = []
    completed = result.get("completed")
    failure_count = result.get("failure_count")
    failures = result.get("failures")
    if result.get("requested") != requested:
        issues.append(f"{operation}: requested mismatch")
    if not isinstance(completed, int):
        issues.append(f"{operation}: completed missing")
    elif completed != requested:
        issues.append(f"{operation}: completed mismatch")
    if not isinstance(failure_count, int):
        issues.append(f"{operation}: failure_count missing")
    if not isinstance(failures, list):
        issues.append(f"{operation}: failures missing")
        failures = None
    if isinstance(failures, list):
        if failures:
            issues.append(f"{operation}: failures not empty")
        if isinstance(failure_count, int) and failure_count != len(failures):
            issues.append(f"{operation}: failure_count inconsistent")
    latency_samples = result.get("latency_ms_samples")
    if not isinstance(latency_samples, list) or len(latency_samples) != requested:
        issues.append(f"{operation}: latency sample mismatch")
    replay_identity = result.get("replay_identity")
    replay_identities = result.get("replay_identities")
    if operation == "REPLAY":
        if not isinstance(replay_identity, str) or not replay_identity:
            issues.append("REPLAY: replay_identity missing")
        if not isinstance(replay_identities, list) or len(replay_identities) != requested:
            issues.append("REPLAY: replay_identities mismatch")
        elif replay_identity and any(identity != replay_identity for identity in replay_identities):
            issues.append("REPLAY: replay identity mismatch")
    return issues


def validate_run(report: Mapping[str, object], *, expected_profiles: Mapping[str, int]) -> list[str]:
    issues: list[str] = []
    if report.get("worker_exit_code") != 0:
        issues.append("worker_exit_code non-zero")
    if report.get("worker_status") == "PASS" and not isinstance(report.get("profiles"), Mapping):
        issues.append("profiles missing")
        return issues
    profiles = report.get("profiles")
    if not isinstance(profiles, Mapping):
        issues.append("profiles missing")
        return issues
    for operation, requested in expected_profiles.items():
        profile = profiles.get(operation)
        if not isinstance(profile, Mapping):
            issues.append(f"{operation}: profile missing")
            continue
        issues.extend(validate_profile(profile, operation=operation, requested=requested))
    extra = set(profiles) - set(expected_profiles)
    if extra:
        issues.append(f"unexpected profiles: {','.join(sorted(extra))}")
    return issues
