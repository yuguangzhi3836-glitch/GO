"""Non-authoritative, allowlisted diagnostics when raw evidence cannot be published.

Never publishes provider messages, opinions, response bodies or credentials.
This record cannot replace a sealed bundle or unlock C13.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re

from lite_cli import FORBIDDEN_SECRET_PATTERNS
from lite_errors import FAILURE_CLASSES


def _enum(value, allowed):
    return value if isinstance(value, str) and value in allowed else None


def _integer(value, maximum):
    return value if type(value) is int and 0 <= value <= maximum else None


def _sha(value, length):
    return value if isinstance(value, str) and re.fullmatch('[0-9a-f]{%d}' % length, value) else None


def build(spec_path, outcome_path, seal_path=None):
    sources, values = {}, {}
    for name, source in [('spec', spec_path), ('outcome', outcome_path), ('seal_result', seal_path)]:
        path = pathlib.Path(source) if source else None
        if path is None or not path.is_file():
            sources[name] = {'present': False}
            values[name] = {}
            continue
        raw = path.read_bytes()
        try:
            value = json.loads(raw)
            value = value if isinstance(value, dict) else {}
        except (ValueError, UnicodeError):
            value = {}
        sources[name] = {'present': True, 'bytes': len(raw),
                         'sha256': hashlib.sha256(raw).hexdigest(),
                         'secret_shape_labels': [label for label, pattern in FORBIDDEN_SECRET_PATTERNS
                                                 if re.search(pattern, raw)]}
        values[name] = value
    spec, outcome, seal = values['spec'], values['outcome'], values['seal_result']
    trace = outcome.get('review_trace')
    trace = trace if isinstance(trace, dict) else {}
    plan = trace.get('plan')
    plan = plan if isinstance(plan, dict) else {}
    parts = trace.get('parts')
    parts = parts if isinstance(parts, list) else []
    planned = plan.get('parts')
    planned = planned if isinstance(planned, list) else []
    # Error codes are a small fixed vocabulary. The entire provider message is omitted,
    # including unknown codes and values that merely resemble a known code.
    code = None
    try:
        error = json.loads(outcome.get('detail', ''))['error']
        code = _enum(error.get('code'), ('insufficient_quota', 'rate_limit_exceeded',
                                       'invalid_api_key', 'billing_hard_limit_reached'))
    except (ValueError, TypeError, KeyError, AttributeError):
        pass
    result = {
        'schema_version': 'go.c13c14.lite.failure_diagnostic.v1',
        'diagnostic_only': True, 'not_acceptance_evidence': True,
        'c13_prerequisite_eligible': False, 'authorizes_any_action': False,
        'original_content_included': False,
        'role': _enum(spec.get('role'), ('c13', 'c14')),
        'run_id': _integer(spec.get('run_id'), 10**15),
        'candidate_sha': _sha(spec.get('candidate_sha'), 40),
        'application_tree': _sha(spec.get('application_tree'), 40),
        'reported_verdict': _enum(outcome.get('verdict'), ('PASS_SCOPED', 'FAIL', 'BLOCKED', 'NOT_APPLICABLE')),
        'failure_class': _enum(outcome.get('failure_class'), FAILURE_CLASSES),
        'http_status': _integer(outcome.get('http_status'), 599),
        'provider_error_code': code,
        'ai_called': outcome.get('ai_called') is True,
        'planned_part_count': len(planned), 'recorded_part_count': len(parts),
        'recorded_response_count': sum(isinstance(p, dict) and isinstance(p.get('response_json'), str) for p in parts),
        'recorded_error_count': sum(isinstance(p, dict) and p.get('error') is not None for p in parts),
        'trace_complete': trace.get('complete') is True,
        'seal_status': _enum(seal.get('status'), ('SEALED', 'REFUSED')),
        'sources': sources,
    }
    # Defense in depth: only the fixed vocabulary, bounded numbers and hashes leave
    # the runner. Even a secret inside a JSON key or malformed raw body is omitted.
    encoded = json.dumps(result, ensure_ascii=True, sort_keys=True, indent=2).encode() + b'\n'
    if any(re.search(pattern, encoded) for _, pattern in FORBIDDEN_SECRET_PATTERNS):
        raise ValueError('diagnostic_output_secret_shape')
    return encoded


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--spec', required=True)
    parser.add_argument('--outcome', required=True)
    parser.add_argument('--seal-result')
    parser.add_argument('--out', required=True)
    args = parser.parse_args(argv)
    raw = build(args.spec, args.outcome, args.seal_result)
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(raw)
    print(json.dumps({'diagnostic_only': True, 'sha256': hashlib.sha256(raw).hexdigest()}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
