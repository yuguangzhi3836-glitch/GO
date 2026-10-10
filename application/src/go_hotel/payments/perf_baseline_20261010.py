from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

RESULT_PREFIX = "C11_PERF_BASELINE_20261010 "
PROFILE_CASES = (
    ("AUTHORIZATION", 20),
    ("AUTHORIZATION", 100),
    ("CAPTURE", 20),
    ("CAPTURE", 100),
    ("REPLAY", 20),
    ("REPLAY", 100),
)

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


def profile_key(operation: object, requested: object) -> str:
    return f"{operation}:{requested}"


def expected_profiles() -> dict[str, int]:
    return {profile_key(operation, requested): requested for operation, requested in PROFILE_CASES}


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


def audit_log_json(payload: Mapping[str, object]) -> str:
    return json.dumps(redact_payload(payload), ensure_ascii=True, indent=2, sort_keys=True)


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


def normalize_profiles(profiles: object) -> dict[str, Mapping[str, object]]:
    if isinstance(profiles, Mapping):
        normalized: dict[str, Mapping[str, object]] = {}
        for key, value in profiles.items():
            if not isinstance(value, Mapping):
                raise ValueError(f"profile {key!r} missing mapping payload")
            name = str(key)
            if name in normalized:
                raise ValueError(f"duplicate profile {name}")
            normalized[name] = value
        return normalized
    if isinstance(profiles, Sequence) and not isinstance(profiles, (str, bytes, bytearray)):
        normalized = {}
        for value in profiles:
            if not isinstance(value, Mapping):
                raise ValueError("profile list contains non-mapping entry")
            key = profile_key(value.get("operation"), value.get("requested"))
            if key in normalized:
                raise ValueError(f"duplicate profile {key}")
            normalized[key] = value
        return normalized
    raise ValueError("profiles missing")


def validate_profile(result: Mapping[str, object], *, operation: str, requested: int) -> list[str]:
    issues: list[str] = []
    if result.get("status") != "PASS":
        issues.append(f"{operation}:{requested}: status not PASS")
    if result.get("operation") != operation:
        issues.append(f"{operation}:{requested}: operation mismatch")
    if result.get("requested") != requested:
        issues.append(f"{operation}:{requested}: requested mismatch")
    if result.get("workers") != requested:
        issues.append(f"{operation}:{requested}: workers mismatch")
    completed = result.get("completed")
    if not isinstance(completed, int):
        issues.append(f"{operation}:{requested}: completed missing")
    elif completed != requested:
        issues.append(f"{operation}:{requested}: completed mismatch")
    failure_count = result.get("failure_count")
    if not isinstance(failure_count, int):
        issues.append(f"{operation}:{requested}: failure_count missing")
    elif failure_count != 0:
        issues.append(f"{operation}:{requested}: failure_count not zero")
    failures = result.get("failures")
    if not isinstance(failures, list):
        issues.append(f"{operation}:{requested}: failures missing")
        failures = None
    elif failures:
        issues.append(f"{operation}:{requested}: failures not empty")
    if isinstance(failures, list) and isinstance(failure_count, int) and len(failures) != failure_count:
        issues.append(f"{operation}:{requested}: failure_count inconsistent")
    latency_samples = result.get("latency_ms_samples")
    if not isinstance(latency_samples, list):
        issues.append(f"{operation}:{requested}: latency samples missing")
    else:
        if len(latency_samples) != requested:
            issues.append(f"{operation}:{requested}: latency sample mismatch")
        if any(not isinstance(sample, (int, float)) or sample < 0 for sample in latency_samples):
            issues.append(f"{operation}:{requested}: invalid latency sample")
    if operation == "REPLAY":
        replay_identity = result.get("replay_identity")
        replay_identities = result.get("replay_identities")
        if not isinstance(replay_identity, str) or not replay_identity:
            issues.append(f"{operation}:{requested}: replay_identity missing")
        if not isinstance(replay_identities, list):
            issues.append(f"{operation}:{requested}: replay_identities missing")
        else:
            if len(replay_identities) != requested:
                issues.append(f"{operation}:{requested}: replay identities mismatch")
            elif replay_identity and any(identity != replay_identity for identity in replay_identities):
                issues.append(f"{operation}:{requested}: replay identity mismatch")
    return issues


def validate_run(report: Mapping[str, object], *, expected_profile_counts: Mapping[str, int]) -> list[str]:
    issues: list[str] = []
    if report.get("worker_exit_code") != 0:
        issues.append("worker_exit_code non-zero")
    if report.get("worker_status") != "PASS":
        issues.append("worker_status not PASS")
    profiles = report.get("profiles")
    try:
        normalized = normalize_profiles(profiles)
    except ValueError as exc:
        issues.append(str(exc))
        return issues
    for key, requested in expected_profile_counts.items():
        profile = normalized.get(key)
        if not isinstance(profile, Mapping):
            issues.append(f"{key}: profile missing")
            continue
        operation = key.split(":", 1)[0]
        issues.extend(validate_profile(profile, operation=operation, requested=requested))
    extra = set(normalized) - set(expected_profile_counts)
    if extra:
        issues.append(f"unexpected profiles: {','.join(sorted(extra))}")
    return issues


def parse_result_line(stdout: str) -> dict[str, object]:
    for line in stdout.splitlines():
        if line.startswith(RESULT_PREFIX):
            return json.loads(line[len(RESULT_PREFIX):])
    raise AssertionError(f"missing {RESULT_PREFIX.strip()} line")
