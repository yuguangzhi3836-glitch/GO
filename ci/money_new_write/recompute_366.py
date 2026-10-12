"""Offline archive recomputation; no database connection or workload execution."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

EXPECTED = 'a720dd9adfbddeb90c19a16ef862a56f156237d4616405e4dbfa893f67cc8c88'


def recompute(archive, catalog_path):
    raw = Path(archive).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == EXPECTED, 'Unexpected evidence archive'
    catalog = json.loads(Path(catalog_path).read_text())['sql_catalog']
    labels = ['root_lock', 'idempotency_key_lock', 'credit_source_guard',
              'history_lock', 'movement_insert', 'fulfillment_lock',
              'ledger_insert', 'fulfillment_event_insert_shared', 'fulfillment_update']
    fingerprints = {}
    for index, label in enumerate(labels):
        sql = catalog[index]
        # Exact explicit bind names in historical a6361b9 money query constants.
        if index in (0, 5):
            sql = sql.replace('%(payment_intent_id_1)s', '%(intent_id)s')
        elif index == 1:
            sql = sql.replace('%(idempotency_key_1)s', '%(movement_key)s')
        elif index == 3:
            sql = sql.replace('%(root_payment_intent_id_1)s', '%(intent_id)s')
        fingerprints[label] = sql.split()[0] + ' ' + hashlib.sha256(sql.encode()).hexdigest()[:16]
    result = {'archive_sha256': EXPECTED,
              'archive_commit': '13a08ec261cc1618b7cada5a2b64bd438b848621',
              'application_commit': 'a6361b9376ab59f05616338b8245ac4e2976dec3',
              'live_retest_completed': False,
              'source_row_count': None, 'source_indexes_observed': None,
              'source_explain_plan': None, 'auth_capture_replay_timing_split': None,
              'fingerprints': fingerprints, 'tiers': {}}
    with zipfile.ZipFile(archive) as z:
        for tier, groups in [(20, range(57, 61)), (100, range(61, 65))]:
            aggregates = {label: {'count': 0, 'wall_seconds': 0.0} for label in labels}
            totals = dict(sql_count=0, sql_wall_seconds=0.0, hold_count=0,
                          hold_seconds=0.0, queue_seconds=0.0)
            for group in groups:
                path = f'held-cpu-evidence/round-1/group-{group}.json.profile.json'
                metrics = json.loads(z.read(path))['metrics']
                assert metrics['held_cpu']['valid']
                statements = {row['statement']: row for row in metrics['sql']}
                for label, fingerprint in fingerprints.items():
                    row = statements[fingerprint]
                    aggregates[label]['count'] += row['count']
                    aggregates[label]['wall_seconds'] += row['sum_seconds']
                sql = metrics['sql_by_service']['money.create_in_session']
                connection = metrics['connection_by_service']['money.create_in_session']
                totals['sql_count'] += sql['count']
                totals['sql_wall_seconds'] += sql['sum_seconds']
                totals['hold_count'] += connection['hold_count']
                totals['hold_seconds'] += connection['hold_sum_seconds']
                totals['queue_seconds'] += connection['queue_sum_seconds']
            assert totals['sql_count'] == tier * 20
            assert totals['hold_count'] == tier * 5
            assert aggregates['credit_source_guard']['count'] == tier * 2
            result['tiers'][tier] = {'money_service_totals': totals,
                'global_fingerprint_totals_not_service_joined': aggregates,
                'guard_wall_over_money_sql': aggregates['credit_source_guard']['wall_seconds']/totals['sql_wall_seconds'],
                'root_and_key_wall_over_money_sql': sum(aggregates[k]['wall_seconds'] for k in ('root_lock', 'idempotency_key_lock'))/totals['sql_wall_seconds']}
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('archive')
    parser.add_argument('--catalog', default=str(Path(__file__).parent/'results/cost-100000.json'))
    args = parser.parse_args()
    print(json.dumps(recompute(args.archive, args.catalog), indent=2))
