"""Same offline image, disposable PostgreSQL 18.4, synthetic data; no HK interface."""
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time
from identity import AFTER, BEFORE, IMAGE

assert os.environ.get('GITHUB_ACTIONS') == 'true'
PY='/opt/go/python/bin/python3.13'
HERE=Path(__file__).resolve().parent
OUT=Path('upgrade-evidence').resolve(); OUT.mkdir(exist_ok=True)
NET='go-depth40-upgrade-ci'
PG='go-depth40-upgrade-ci-pg'
VOL='go-depth40-upgrade-ci-media'
DB='depth40_upgrade_ci'
RESTORE='depth40_restore_ci'
PASSWORD=secrets.token_urlsafe(32)
private=Path('upgrade-ci.private.env').resolve()
ENV={'APP_ENV':'staging','DATABASE_URL':f'postgresql+psycopg://go:{PASSWORD}@postgres:5432/{DB}',
     'GO_DISPOSABLE_UPGRADE_CI':'true','GO_MEDIA_CACHE_DIR':'/state/media',
     'HOSTED_RESERVATION_EXPIRY_WORKER_ENABLED':'false','VERTICAL_RESERVATION_EXPIRY_WORKER_ENABLED':'false'}
private.write_text(''.join(k+'='+v+'\n' for k,v in ENV.items())); private.chmod(0o600)
checks=[]; complete=False; lock=None

def scrub(s):
    return s.replace(ENV['DATABASE_URL'],'<CI_DATABASE_URL>').replace(PASSWORD,'<CI_DB_PASSWORD>')

def cmd(args, *, check=True, timeout=240):
    p=subprocess.run(args,capture_output=True,text=True,timeout=timeout)
    if check and p.returncode: raise RuntimeError(scrub(p.stdout+'\n'+p.stderr))
    return p

def record(name, ok, detail=None):
    checks.append({'check':name,'passed':bool(ok),'detail':detail})
    print(json.dumps(checks[-1]),flush=True)
    if not ok: raise RuntimeError(name)

def sql(statement, db=DB):
    assert db in {DB,RESTORE,'postgres'}
    return cmd(['docker','exec',PG,'psql','-h','127.0.0.1','-U','go','-d',db,'-X','-At','-v','ON_ERROR_STOP=1','-c',statement]).stdout.strip()

def image_args(args, *, db=DB, pgoptions=None, name=None):
    assert db in {DB,RESTORE}
    result=['docker','run','--rm','--network',NET,'--read-only','--cap-drop','ALL',
        '--security-opt','no-new-privileges','--pids-limit','96','--memory','768m',
        '--tmpfs','/tmp:rw,nosuid,size=64m','--env-file',str(private),
        '--mount','type=bind,src='+str(HERE)+',dst=/review,readonly',
        '--mount','type=bind,src='+str(OUT)+',dst=/evidence,readonly',
        '--mount','type=volume,src='+VOL+',dst=/state']
    if db!=DB: result+=['-e','DATABASE_URL='+ENV['DATABASE_URL'].rsplit('/',1)[0]+'/'+db]
    if pgoptions: result+=['-e','PGOPTIONS='+pgoptions]
    if name: result+=['--name',name]
    return result+['--entrypoint',PY,IMAGE,'-B']+args

def run(args, **kw):
    check=kw.pop('check',True); timeout=kw.pop('timeout',240)
    return cmd(image_args(args,**kw),check=check,timeout=timeout)

def snapshot(label, *, db=DB, baseline=None):
    args=['/review/db_probe.py','snapshot']
    if baseline: args+=['--baseline','/evidence/'+baseline]
    p=run(args,db=db); value=json.loads(p.stdout)
    (OUT/(label+'.json')).write_text(json.dumps(value,indent=2)+'\n')
    return value

def widths(s):
    return {r['column_name']:r['character_maximum_length'] for r in s['schema']
        if r['table_name']=='rail_order_runtime' and r['column_name'] in {'status','booking_reference'}}

def migrate(label, target=AFTER, *, direction='upgrade', timeout_ms=2000, check=True):
    start=time.monotonic()
    p=run(['-m','alembic',direction,target],check=False,timeout=420,
        pgoptions=f'-c lock_timeout={timeout_ms} -c statement_timeout=60000 -c application_name=go_depth40_ci_migrate')
    (OUT/(label+'.log')).write_text(scrub(p.stdout+'\n'+p.stderr))
    record(label,p.returncode==0 if check else p.returncode!=0,
        {'exit_code':p.returncode,'elapsed_seconds':round(time.monotonic()-start,3)})
    return p

def start_lock():
    global lock
    lock=subprocess.Popen(['docker','exec','-e','PGAPPNAME=go_depth40_ci_lock',PG,'psql','-U','go','-d',DB,
        '-X','-v','ON_ERROR_STOP=1','-c','BEGIN; LOCK TABLE rail_order_runtime IN ACCESS EXCLUSIVE MODE; SELECT pg_sleep(55); ROLLBACK;'],
        stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    for _ in range(100):
        if sql("SELECT count(*) FROM pg_locks l JOIN pg_stat_activity a ON a.pid=l.pid "
            "WHERE a.application_name='go_depth40_ci_lock' AND l.mode='AccessExclusiveLock' AND l.granted")=='1': return
        time.sleep(0.1)
    raise RuntimeError('CI_LOCK_NOT_OBSERVED')

def stop_lock():
    global lock
    sql("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE application_name='go_depth40_ci_lock'")
    if lock:
        lock.communicate(timeout=15); lock=None

try:
    cmd(['docker','pull','postgres:18.4'])
    info=json.loads(cmd(['docker','image','inspect','postgres:18.4']).stdout)[0]
    (OUT/'POSTGRES_FIXTURE.json').write_text(json.dumps({'requested':'postgres:18.4','id':info['Id'],
        'repo_digests':info['RepoDigests'],'scope':'DISPOSABLE_CI_ONLY'},indent=2)+'\n')
    cmd(['docker','network','create','--internal',NET]); cmd(['docker','volume','create',VOL])
    cmd(['docker','run','-d','--name',PG,'--network',NET,'--network-alias','postgres',
         '-e','POSTGRES_USER=go','-e','POSTGRES_DB='+DB,'-e','POSTGRES_PASSWORD='+PASSWORD,'postgres:18.4'])
    for _ in range(80):
        p=cmd(['docker','exec',PG,'psql','-h','127.0.0.1','-U','go','-d',DB,'-Atc','SELECT 1'],check=False)
        if p.returncode==0 and p.stdout.strip()=='1': break
        time.sleep(0.5)
    else: raise RuntimeError('POSTGRES_TCP_NOT_READY')
    record('postgres_exact_18_4',sql('SHOW server_version_num')=='180004')
    record('fixed_image_config_loaded',cmd(['docker','image','inspect',IMAGE,'--format','{{.Id}}']).stdout.strip()==IMAGE)
    # Source identity is checked without invoking configuration/database/media bootstraps.
    p=run(['-c','import sys,json;sys.path.insert(0,"/opt/go/staging");from preflight import verify_source;print(json.dumps(verify_source()))'])
    (OUT/'SOURCE_CHECK.json').write_text(p.stdout)
    record('same_1271_source_files',json.loads(p.stdout)['files']==1271)
    (OUT/'MIGRATION_LINEAGE.json').write_text(run(['/review/db_probe.py','lineage']).stdout)
    migrate('SYNTHETIC_EMPTY_TO_0114',BEFORE)
    run(['/review/db_probe.py','seed'])
    before=snapshot('BEFORE_0114')
    record('real_0114_migrations_and_legacy_widths',before['head']==BEFORE and widths(before)=={'status':32,'booking_reference':24})
    record('synthetic_legacy_records_seeded',before['tables']['rail_order_runtime']['rows']==2 and before['tables']['mobility_refund_runtime']['rows']==1)
    p=cmd(['docker','exec',PG,'pg_dump','-U','go','-d',DB,'-Fc','--file=/tmp/depth40-synthetic-0114.dump'])
    (OUT/'PG_DUMP.log').write_text(scrub(p.stdout+'\n'+p.stderr))
    cmd(['docker','cp',PG+':/tmp/depth40-synthetic-0114.dump',str(OUT/'SYNTHETIC_ONLY_0114.dump')])
    dump=OUT/'SYNTHETIC_ONLY_0114.dump'
    (OUT/'SYNTHETIC_BACKUP.json').write_text(json.dumps({'sha256':hashlib.sha256(dump.read_bytes()).hexdigest(),
        'bytes':dump.stat().st_size,'scope':'SYNTHETIC_CI_ONLY','hk_backup':False},indent=2)+'\n')
    record('pg18_custom_backup_created',dump.stat().st_size>0)
    start_lock()
    failed=migrate('UPGRADE_LOCK_TIMEOUT_ROLLBACK',check=False)
    record('lock_timeout_failure_reason','lock timeout' in failed.stderr.lower())
    stop_lock()
    record('all_schema_and_rows_unchanged_after_lock_failure',snapshot('AFTER_LOCK_FAILURE')==before)
    start_lock()
    proc=subprocess.Popen(image_args(['-m','alembic','upgrade',AFTER],
        pgoptions='-c lock_timeout=45000 -c statement_timeout=60000 -c application_name=go_depth40_ci_interrupt'),
        stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    for _ in range(150):
        count=sql("SELECT count(*) FROM pg_stat_activity WHERE application_name='go_depth40_ci_interrupt' "
                  "AND wait_event_type='Lock' AND query ILIKE '%rail_order_runtime%'")
        if count=='1': break
        time.sleep(0.1)
    else: raise RuntimeError('INTERRUPTION_POINT_NOT_OBSERVED')
    record('migration_reached_final_width_change_before_interrupt',count=='1')
    sql("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE application_name='go_depth40_ci_interrupt'")
    stdout,stderr=proc.communicate(timeout=30)
    (OUT/'UPGRADE_CONNECTION_TERMINATION.log').write_text(scrub(stdout+'\n'+stderr))
    stop_lock()
    record('interrupted_migration_failed',proc.returncode!=0)
    record('all_schema_and_rows_unchanged_after_interruption',snapshot('AFTER_INTERRUPTION')==before)
    migrate('UPGRADE_0114_TO_0132')
    after=snapshot('AFTER_0132',baseline='BEFORE_0114.json')
    record('upgraded_head_and_critical_widths',after['head']==AFTER and widths(after)=={'status':64,'booking_reference':128})
    unchanged=all(after['original_columns'][name]=={'rows':t['rows'],'rows_sha256':t['rows_sha256']}
                  for name,t in before['tables'].items() if name!='alembic_version')
    record('all_original_columns_and_rows_preserved',unchanged,{'original_tables':len(before['tables'])-1})
    record('legacy_refund_default_backfilled',sql("SELECT count(*) FROM mobility_refund_runtime WHERE settlement_plan_json::jsonb='[]'::jsonb")=='1')
    migrate('SECOND_UPGRADE_IS_NOOP')
    record('second_upgrade_preserves_full_state',snapshot('AFTER_SECOND_UPGRADE')=={**after,'original_columns':{}})
    run(['/review/db_probe.py','long-values'])
    long_state=snapshot('AFTER_LONG_VALUES')
    failed=migrate('UNSAFE_NARROWING_REFUSED','0131_vertical_payment_deadline',direction='downgrade',check=False)
    record('downgrade_refusal_reason','RAIL_RUNTIME_DOWNGRADE_WOULD_TRUNCATE_HISTORY' in failed.stderr)
    record('failed_downgrade_retains_data_and_head',snapshot('AFTER_REFUSED_DOWNGRADE')==long_state)
    sql('CREATE DATABASE '+RESTORE+' TEMPLATE template0','postgres')
    p=cmd(['docker','exec',PG,'pg_restore','-U','go','-d',RESTORE,'--exit-on-error','--single-transaction','/tmp/depth40-synthetic-0114.dump'])
    (OUT/'PG_RESTORE.log').write_text(scrub(p.stdout+'\n'+p.stderr))
    record('backup_restores_all_tables_rows_sequences_and_definitions',snapshot('RESTORED_0114',db=RESTORE)==before)
    record('restore_did_not_overwrite_upgraded_database',snapshot('UPGRADED_DB_AFTER_SEPARATE_RESTORE')==long_state)
    p=run(['/review/media_exercise.py'],check=False)
    (OUT/'MEDIA_PRESERVATION.json').write_text(scrub(p.stdout))
    (OUT/'MEDIA_PRESERVATION.stderr.log').write_text(scrub(p.stderr))
    record('legacy_media_copy_import_and_restore',p.returncode==0,
           {'checks':len(json.loads(p.stdout).get('checks',[]))} if p.stdout.strip().startswith('{') else None)
    complete=True
finally:
    (OUT/'RESULT.json').write_text(json.dumps({'status':'PASS_ISOLATED_UPGRADE' if complete else 'HOLD',
        'checks':checks,'database_scope':'DISPOSABLE_PG18_4_SYNTHETIC_0114_FIXTURE',
        'not_a_clone_of_hk':True,'hk_migration':'NOT_RUN','hk_media_conversion':'NOT_RUN',
        'hk_backup_restore':'HOLD','hk_deployment':'HOLD','production_release':'HOLD'},indent=2)+'\n')
    p=cmd(['docker','logs',PG],check=False)
    (OUT/'POSTGRES.log').write_text(scrub(p.stdout+'\n'+p.stderr))
    cmd(['docker','rm','--force',PG],check=False)
    if lock:
        try: lock.communicate(timeout=10)
        except subprocess.TimeoutExpired: lock.kill()
    cmd(['docker','network','rm',NET],check=False)
    cmd(['docker','volume','rm',VOL],check=False)
    private.unlink(missing_ok=True)
