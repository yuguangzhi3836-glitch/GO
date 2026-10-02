"""Recompute historical R3 CPU attribution from its immutable raw ZIP."""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import PurePosixPath
from statistics import median
import zipfile

EXPECTED = '1be3458c68a141050454bd1708878efa9d4921f364f1e58c1e8c57aa1e2ba5cb'


def recompute(path):
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != EXPECTED:
        raise ValueError('R3_ARCHIVE_DIGEST_MISMATCH')
    rounds = []
    with zipfile.ZipFile(path) as archive:
        for label in ('1-baseline', '2-candidate', '3-candidate', '4-baseline'):
            sums = defaultdict(float)
            mapper = 0.0
            workers = 0
            for name in archive.namelist():
                if '/' + label + '-diagnostic/' not in '/' + name or not name.endswith('.job'):
                    continue
                job = json.loads(archive.read(name))
                tasks = job.get('tasks', [])
                if len(tasks) != 25 or not all(t['op'] == 'ride' for t in tasks):
                    continue
                metrics = json.loads(archive.read(str(PurePosixPath(name).with_suffix('.json.profile.json'))))['metrics']
                workers += 1
                for key, row in metrics['service_calls'].items():
                    sums[key] += row['exclusive_calling_thread_cpu_seconds']
                mapper += sum(r['configuring_thread_cpu_seconds'] for r in metrics['mapper_configuration'])
            if workers != 4:
                raise ValueError('R3_WORKER_COUNT_MISMATCH')
            rounds.append({'round': label, 'workers': workers,
                           'exclusive_service_cpu_seconds': dict(sorted(sums.items())),
                           'mapper_cpu_seconds': mapper,
                           'money_family_exclusive_cpu_seconds': sums['money.create'] + sums['money.create_in_session']})
    baseline = [r for r in rounds if r['round'].endswith('baseline')]
    return {'raw_zip_sha256': EXPECTED,
            'archive_commit': '3173cd94e0a1377c6dcde5442d27f56517d51c65',
            'diagnostic_only': True, 'rounds': rounds,
            'baseline_medians_seconds': {
                'ride.create_exclusive_cpu': median(r['exclusive_service_cpu_seconds']['ride.create'] for r in baseline),
                'money_family_exclusive_cpu': median(r['money_family_exclusive_cpu_seconds'] for r in baseline),
                'orm_first_configuration_cpu': median(r['mapper_cpu_seconds'] for r in baseline)},
            'limitations': ['Instrumented CPU includes observer cost; not an adoption budget.',
                           'Mapper CPU overlaps service CPU; do not add these numbers.',
                           'Existing mapper records do not identify active service/lease.',
                           'Historical R3 application is not the deployed PR320 application.']}


if __name__ == '__main__':
    from pathlib import Path
    parser = argparse.ArgumentParser()
    parser.add_argument('raw_zip', type=Path)
    args = parser.parse_args()
    print(json.dumps(recompute(args.raw_zip), indent=2, sort_keys=True))
