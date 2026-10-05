"""Record CI stage outcomes without copying step outputs, credentials, or logs."""
import json
import os
from pathlib import Path
import subprocess
import sys


def receipt(steps):
    stages = [{'id': key, 'outcome': value.get('outcome', 'unknown'),
               'conclusion': value.get('conclusion', 'unknown')}
              for key, value in sorted(steps.items())]
    failures = [row['id'] for row in stages if row['outcome'] == 'failure']
    return {'schema': 'go.acceptance.stage-receipt.v1',
            'status': 'FAIL' if failures else 'NO_PRIOR_STEP_FAILURE',
            'first_failed_stage': failures[0] if failures else None,
            'stages': stages, 'acceptance_pass': False,
            'note': 'Stage outcomes only; never substitutes for test results.'}


def main():
    result = receipt(json.loads(os.environ['GO_CI_STEPS']))
    result['candidate_commit'] = subprocess.check_output(
        ['git', 'rev-parse', 'HEAD'], text=True).strip()
    result['job'] = os.environ.get('GITHUB_JOB')
    result['run_id'] = os.environ.get('GITHUB_RUN_ID')
    result['run_attempt'] = os.environ.get('GITHUB_RUN_ATTEMPT')
    out = Path(sys.argv[1]); out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
