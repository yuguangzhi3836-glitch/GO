"""Exact-candidate forward-migration rehearsal in a fresh, local CI database only."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import traceback

from lineage import read_graph, forward_path, lineage_digest

HERE = Path(__file__).resolve().parent
def sha(data): return hashlib.sha256(data).hexdigest()
def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args], text=True).strip()
def write(out, name, value):
    (out/name).write_text(json.dumps(value, sort_keys=True, indent=2)+'\n')

def snapshot(connection, tables):
    from sqlalchemy import text
    result = {}
    for table in sorted(tables):
        if table == 'alembic_version':
            continue
        quoted = connection.dialect.identifier_preparer.quote(table)
        rows = sorted(connection.execute(text('SELECT row_to_json(t)::text FROM '+quoted+' AS t')).scalars())
        result[table] = {'rows': len(rows), 'sha256': sha(('\n'.join(rows)+'\n').encode())}
    return result

def run(candidate, baseline, out, result):
    from sqlalchemy import create_engine, inspect, text
    from sqlalchemy.engine import make_url
    binding = json.loads((HERE/'BINDING.json').read_text())
    url = make_url(os.environ['DATABASE_URL'])
    assert url.drivername == 'postgresql+psycopg'
    assert url.host == '127.0.0.1' and url.port == 5432
    assert url.database == 'go_issue103_isolated' and url.username == 'go_ci', 'ISOLATED_DATABASE_REQUIRED'
    assert os.environ.get('GITHUB_ACTIONS') == 'true', 'CI_ONLY_NO_HOST_EXECUTION'
    assert git(candidate,'rev-parse','HEAD') == binding['candidate_sha'], 'CANDIDATE_SHA_MISMATCH'
    assert git(candidate,'rev-parse','HEAD:application') == binding['candidate_application_tree']
    assert git(baseline,'rev-parse','HEAD') == binding['baseline_source_sha'], 'BASELINE_SHA_MISMATCH'
    assert git(baseline,'rev-parse','HEAD:application') == binding['baseline_application_tree']
    assert not git(candidate,'status','--porcelain','--untracked-files=no'), 'DIRTY_CANDIDATE'
    fingerprint = {}
    for name in git(candidate,'ls-files','application').splitlines():
        path = candidate/name
        assert path.is_file() and not path.is_symlink(), 'SOURCE_NOT_REGULAR'
        fingerprint[name[len('application/'):]] = sha(path.read_bytes())
    value = sha(''.join(f'{p}\0{h}\n' for p,h in sorted(fingerprint.items())).encode())
    assert value == binding['candidate_fingerprint_sha256'], 'APPLICATION_FINGERPRINT_MISMATCH'
    write(out,'SOURCE_FINGERPRINT.json',fingerprint)
    graph = read_graph(candidate/'application/alembic/versions')
    old = read_graph(baseline/'application/alembic/versions')
    path = forward_path(graph,binding['baseline_revision'],binding['target_revision'])
    assert forward_path(old,binding['baseline_revision'],binding['baseline_revision']) == []
    for revision, entry in old.items():
        assert graph.get(revision) == entry, 'HISTORICAL_MIGRATION_BYTES_CHANGED:'+revision
    write(out,'LINEAGE.json',{'baseline':old,'candidate':graph,'forward_revisions':path,
                              'lineage_sha256':lineage_digest(graph),
                              'historical_migration_retention':'PASS',
                              'migration_required':bool(path),
                              'atomic_transaction_claim':False,
                              'concurrent_index_migration':'0135_journey_search_trigram'})
    result.update(binding=binding, source_binding='PASS', migration_lineage='PASS',
                  historical_migration_retention='PASS', migration_required=bool(path),
                  migration_source_digest=sha((out/'LINEAGE.json').read_bytes()),
                  lineage_sha256=lineage_digest(graph))
    engine = create_engine(url)
    with engine.connect() as connection:
        assert connection.execute(text('SELECT current_database()')).scalar_one() == 'go_issue103_isolated'
        version = connection.execute(text('SHOW server_version')).scalar_one()
        assert version.startswith('18.4'), 'POSTGRES_VERSION_MISMATCH'
        assert inspect(connection).get_table_names() == [], 'FRESH_DATABASE_REQUIRED'
    env = dict(os.environ, PYTHONPATH=str(candidate/'application/src'), PYTHONDONTWRITEBYTECODE='1',
               MODEL_GATEWAY_EXTERNAL_EGRESS_ENABLED='false', TRAVEL_INTELLIGENCE_ENABLED='false')
    def upgrade(revision, label):
        result['last_stage'] = label
        p=subprocess.run([sys.executable,'-m','alembic','upgrade',revision],
                         cwd=candidate/'application', env=env, capture_output=True,text=True,timeout=480)
        (out/(label+'.log')).write_text(p.stdout+p.stderr)
        if p.returncode:
            raise RuntimeError('ALEMBIC_FAILED:'+label+'; see '+label+'.log')
    upgrade(binding['baseline_revision'],'baseline_upgrade')
    with engine.begin() as connection:
        current = list(connection.execute(text('SELECT version_num FROM alembic_version')).scalars())
        assert current == [binding['baseline_revision']], 'BASELINE_REVISION_MISMATCH'
        connection.execute(text("INSERT INTO flight_change_plan (quote_id,order_id,account_id,plan_json,plan_hash,created_at) VALUES ('issue103-retention','issue103-order','issue103-account',CAST(:plan AS JSON),:digest,'2026-09-17T00:00:00Z')"),
                           {'plan':'{"retention":"must survive forward upgrade"}','digest':'a'*64})
        tables=inspect(connection).get_table_names()
        before=snapshot(connection,tables)
    write(out,'BASELINE_DATA.json',before)
    upgrade(binding['target_revision'],'candidate_upgrade')
    with engine.connect() as connection:
        assert list(connection.execute(text('SELECT version_num FROM alembic_version')).scalars()) == [binding['target_revision']], 'TARGET_REVISION_MISMATCH'
        assert snapshot(connection,tables) == before, 'EXISTING_BUSINESS_DATA_CHANGED'
        actual_tables=set(inspect(connection).get_table_names())
        assert {'go_ai_execution','hosted_money_unknown_episode','hosted_money_unknown_episode_audit'} <= actual_tables
        width=connection.execute(text("SELECT character_maximum_length FROM information_schema.columns WHERE table_schema='public' AND table_name='flight_order_runtime' AND column_name='status'")).scalar_one()
        assert width == 64, 'FLIGHT_STATUS_WIDTH_MISMATCH'
        indexes=connection.execute(text("SELECT c.relname,i.indisvalid FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid WHERE c.relname IN ('ix_go_journey_title_lower_trgm','ix_go_journey_destination_lower_trgm') ORDER BY c.relname")).all()
        assert len(indexes)==2 and all(row[1] for row in indexes), 'TRIGRAM_INDEXES_MISSING_OR_INVALID'
        extension=connection.execute(text("SELECT extversion FROM pg_extension WHERE extname='pg_trgm'")).scalar_one()
        # These are a separately provisioned controls DB contract, not business Alembic tables.
        controls={'supplier_runtime_replay','supplier_runtime_evidence','supplier_runtime_mutation'}
        result['separate_controls_database']={'provisioned_by_business_migrations':sorted(controls & actual_tables),
            'contract':'supplier_runtime_controls.metadata is explicitly isolated; external activation still HOLD'}
    upgrade(binding['target_revision'],'already_at_target')
    with engine.connect() as connection:
        assert snapshot(connection,tables)==before
    assert not git(candidate,'status','--porcelain','--untracked-files=no'), 'PRODUCT_SOURCE_CHANGED'
    result.update(postgres_version=version, forward_upgrade='PASS', prestate_revision=binding['baseline_revision'],
                  poststate_revision=binding['target_revision'], existing_data_retention='PASS',
                  baseline_business_tables=len(before), pg_trgm_version=extension,
                  valid_trigram_indexes=[row[0] for row in indexes], target_noop='PASS',
                  status='PASS_SCOPED', database_scope='DISPOSABLE_GITHUB_ACTIONS_POSTGRES_ONLY')

def main():
    p=argparse.ArgumentParser();p.add_argument('--candidate',type=Path,required=True)
    p.add_argument('--baseline',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();out=a.out.resolve();out.mkdir(parents=True,exist_ok=True)
    result={'schema':'go.hk-migration-rehearsal.v1','status':'FAIL','tooling_sha':git(HERE,'rev-parse','HEAD'),
            'ci_run_id':os.environ.get('GITHUB_RUN_ID'),'live_database_touched':False,
            'inherited_cell_tests_rerun':False,'migration_authorized':False,'deployment_authorized':False,
            'deploy_admission':'BLOCKED','remaining_blockers':['LIVE_CANDIDATE_BINDING_NOT_UPDATED',
            'INSTALLED_FORWARD_MIGRATION_UNSUPPORTED','EXACT_CANDIDATE_CANARY_NOT_PROVEN'],
            'holds':['REAL_SUPPLIER_CERTIFICATION','FINAL_RELEASE','PRODUCTION']}
    code=0
    try:
        run(a.candidate.resolve(),a.baseline.resolve(),out,result)
    except Exception as exc:
        code=1;result['first_error']=str(exc);(out/'ERROR.log').write_text(traceback.format_exc())
    write(out,'EVIDENCE.json',result)
    (out/'SHA256SUMS').write_text(''.join(sha(f.read_bytes())+'  '+f.name+'\n'
                                for f in sorted(out.iterdir()) if f.is_file() and f.name!='SHA256SUMS'))
    print(json.dumps(result,sort_keys=True));print('EVIDENCE_SHA256='+sha((out/'EVIDENCE.json').read_bytes()))
    return code

if __name__ == '__main__':
    raise SystemExit(main())
