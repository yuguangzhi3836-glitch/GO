"""Fresh GitHub-hosted Docker/PG fixtures ONLY. No HK/production address or secret input."""
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time

PY = '/opt/go/python/bin/python3.13'
HERE = Path(__file__).resolve().parent
OUT = Path('staging-delivery'); OUT.mkdir(exist_ok=True)
IMAGE = os.environ['IMAGE']
assert IMAGE.startswith('go-depth40-staging:ci-')
assert os.environ.get('GITHUB_ACTIONS') == 'true'
NET = 'go-depth40-staging-ci'
PREFIX = 'go-d40-ci-'
VOLUME = 'go-d40-ci-media'
password = secrets.token_urlsafe(32)
envfile = Path('staging-ci.private.env').resolve()
ENV = {
    'APP_ENV': 'staging', 'DATABASE_URL': f'postgresql+psycopg://go:{password}@postgres:5432/go_depth40_ci',
    'REDIS_URL': 'redis://redis:6379/0', 'JWT_SIGNING_KEY': secrets.token_urlsafe(48),
    'CONNECTOR_VAULT_MASTER_KEY': secrets.token_urlsafe(48), 'WEBHOOK_SECRET': secrets.token_urlsafe(32),
    'BOOTSTRAP_ADMIN_USERNAME': 'ci-admin', 'BOOTSTRAP_ADMIN_PASSWORD': secrets.token_urlsafe(32),
    'BOOTSTRAP_SUPPLIER_USERNAME': 'ci-supplier', 'BOOTSTRAP_SUPPLIER_PASSWORD': secrets.token_urlsafe(32),
    'BOOTSTRAP_SUPPLIER_ID': 'sup_depth40_ci', 'COOKIE_SECURE': 'false', 'MFA_REQUIRED_FOR_ADMIN': 'false',
    'OUTBOX_TRANSPORT': 'redis', 'MOBILE_PUSH_MODE': 'mock',
    'HOSTED_RESERVATION_EXPIRY_WORKER_ENABLED': 'false',
    'VERTICAL_RESERVATION_EXPIRY_WORKER_ENABLED': 'true',
    'MODEL_GATEWAY_EXTERNAL_EGRESS_ENABLED': 'false', 'TRAVEL_INTELLIGENCE_ENABLED': 'false',
    'GO_MEDIA_CACHE_DIR': '/state/media',
}
envfile.write_text(''.join(f'{k}={v}\n' for k,v in ENV.items())); envfile.chmod(0o600)
checks = []
containers = []


def scrub(s):
    for key, value in ENV.items():
        if any(token in key for token in ('PASSWORD','KEY','SECRET','URL')):
            s=s.replace(value, '<redacted:'+key+'>')
    return s.replace(password, '<redacted:CI_DB_PASSWORD>')


def cmd(args, timeout=240, check=True):
    p=subprocess.run(args, text=True, capture_output=True, timeout=timeout)
    if check and p.returncode:
        raise RuntimeError(scrub(p.stdout+'\n'+p.stderr))
    return p


def record(name, passed, detail=None):
    checks.append({'check': name, 'passed': bool(passed), 'detail': detail})
    print(json.dumps(checks[-1]), flush=True)
    if not passed:
        raise RuntimeError(name)


def run_image(args, *, entrypoint=None, extra=None, check=True, timeout=240):
    command=['docker','run','--rm','--network',NET,'--read-only','--cap-drop','ALL',
             '--security-opt','no-new-privileges','--tmpfs','/tmp:rw,nosuid,size=64m',
             '--env-file',str(envfile),'--mount','type=volume,src='+VOLUME+',dst=/state']
    if extra: command += extra
    if entrypoint: command += ['--entrypoint',entrypoint]
    return cmd(command+[IMAGE]+args, timeout=timeout, check=check)


def sql(statement):
    return cmd(['docker','exec',PREFIX+'pg','psql','-U','go','-d','go_depth40_ci','-v','ON_ERROR_STOP=1',
                '-Atc',statement]).stdout.strip()


try:
    # Fixture images are test-only, their exact RepoDigests are recorded; never delivered as GO images.
    fixtures={}
    for ref in ('postgres:16.4','redis:7.4.1'):
        cmd(['docker','pull',ref])
        fixtures[ref]=json.loads(cmd(['docker','image','inspect',ref]).stdout)[0]['RepoDigests']
    (OUT/'CI_FIXTURE_IMAGES.json').write_text(json.dumps(fixtures,indent=2)+'\n')
    cmd(['docker','network','create','--internal',NET])
    cmd(['docker','volume','create',VOLUME])
    for name,alias,args in [
        (PREFIX+'pg','postgres',['-e','POSTGRES_USER=go','-e','POSTGRES_DB=go_depth40_ci',
             '-e','POSTGRES_PASSWORD='+password,'postgres:16.4']),
        (PREFIX+'redis','redis',['redis:7.4.1'])]:
        containers.append(name)
        cmd(['docker','run','-d','--name',name,'--network',NET,'--network-alias',alias]+args)
    for _ in range(45):
        if cmd(['docker','exec',PREFIX+'pg','pg_isready','-U','go','-d','go_depth40_ci'],check=False).returncode==0:
            break
        time.sleep(1)
    record('fresh_database_empty',sql("SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")=='0')
    p=run_image(['-B','-m','alembic','upgrade','0132_rail_runtime_field_widths'],entrypoint=PY,check=False,timeout=420)
    (OUT/'CI_FRESH_MIGRATION.log').write_text(scrub(p.stdout+'\n'+p.stderr))
    record('fresh_pg16_migration_to_0132',p.returncode==0)
    # This fixture setup is explicitly outside the delivered entrypoint, and only on this empty CI DB.
    seed="from go_hotel.security.service import identity_service; identity_service.bootstrap(); print('CI_PRINCIPALS_CREATED')"
    run_image(['-B','-c',seed],entrypoint=PY)
    # A NEW isolated media volume only; the delivered launcher never initializes an index.
    run_image(['-B','-c','from go_hotel.services.media_harvester import media_harvester_service; print("CI_MEDIA_INITIALIZED")'],entrypoint=PY)
    before=sql('SELECT count(*) FROM identity_user')
    p=run_image(['preflight'])
    result=json.loads(p.stdout)
    record('read_only_preflight',result['status']=='PASS_READ_ONLY' and result['database']['transaction_read_only'])
    record('preflight_no_identity_write',sql('SELECT count(*) FROM identity_user')==before)
    # Deliberately simulate old/missing lineage on a disposable database; restore marker in CI only.
    sql("UPDATE alembic_version SET version_num='0114_ext_truth_incident_hard'")
    p=run_image(['api'],check=False)
    record('old_database_refuses_api_start',p.returncode==2 and 'DATABASE_HEAD_MISMATCH' in p.stdout)
    record('rejection_does_not_migrate',sql('SELECT version_num FROM alembic_version')=='0114_ext_truth_incident_hard')
    sql("UPDATE alembic_version SET version_num='0132_rail_runtime_field_widths'")
    p=run_image(['regional-hotel-build-worker'],check=False)
    record('locked_worker_role_rejected',p.returncode==2 and 'FIXED_SERVICE_ROLE_REQUIRED' in p.stdout)
    p=run_image(['preflight'],extra=['-e','APP_ENV=production'],check=False)
    record('production_environment_rejected',p.returncode==2 and 'STAGING_ENV_REQUIRED' in p.stdout)
    p=run_image(['preflight'],extra=['-e','JWT_SIGNING_KEY=dev-only-change-me-jwt'],check=False)
    record('default_credential_rejected',p.returncode==2 and 'DEFAULT_CREDENTIAL_REJECTED' in p.stdout)
    p=run_image(['preflight'],extra=['-e','GO_MEDIA_CACHE_DIR=/opt/go/source/var/media_cache'],check=False)
    record('source_tree_media_path_rejected',p.returncode==2 and 'FIXED_MEDIA_VOLUME_MAPPING_REQUIRED' in p.stdout)
    workers=['recovery-worker','outbox-worker','mobile-push-receipt-worker','reconciliation-worker',
             'mobile-push-worker','mobile-engagement-worker','judgment-worker']
    for role in ['api']+workers:
        name=PREFIX+role; containers.append(name)
        cmd(['docker','run','-d','--name',name,'--network',NET,'--network-alias',role,
             '--read-only','--cap-drop','ALL','--security-opt','no-new-privileges','--pids-limit','96',
             '--memory','512m' if role=='api' else '192m','--tmpfs','/tmp:rw,noexec,nosuid,size=32m',
             '--env-file',str(envfile),'--mount','type=volume,src='+VOLUME+',dst=/state',IMAGE,role])
    # Probe from the same internal network; no public port or external provider is used.
    p=run_image(['-B','-c', (HERE/'http_probe.py').read_text()],entrypoint=PY,timeout=180)
    (OUT/'CI_HTTP_PROBE.json').write_text(p.stdout)
    record('api_and_three_frontends_http',json.loads(p.stdout)['status']=='PASS')
    # Let each 30-second worker interval run at least once after startup.
    deadline=time.monotonic()+35
    while time.monotonic()<deadline: time.sleep(1)
    states={}
    for role in ['api']+workers:
        name=PREFIX+role
        inspect=json.loads(cmd(['docker','inspect',name]).stdout)[0]
        logs=cmd(['docker','logs',name],check=False)
        raw=scrub(logs.stdout+'\n'+logs.stderr)
        (OUT/('CI_'+role+'.log')).write_text(raw)
        states[role]={'image_id':inspect['Image'],'running':inspect['State']['Running'],
                      'restart_count':inspect['RestartCount'],'exit_code':inspect['State']['ExitCode']}
        record(role+'_live',states[role]['running'] and states[role]['restart_count']==0 and
               'Traceback (most recent call last)' not in raw and 'tick_failed' not in raw)
    (OUT/'CI_EIGHT_SERVICE_BINDING.json').write_text(json.dumps(states,indent=2)+'\n')
    record('post_start_head_unchanged',sql('SELECT version_num FROM alembic_version')=='0132_rail_runtime_field_widths')
    (OUT/'CI_RESOURCE_SAMPLES.jsonl').write_text(cmd(['docker','stats','--no-stream','--format','{{json .}}']+
        [PREFIX+role for role in ['api']+workers]).stdout)
    print(json.dumps({'status':'PASS','checks':len(checks)}),flush=True)
finally:
    (OUT/'CI_RESULT.json').write_text(json.dumps({'status':'PASS' if len(checks)>=20 and all(c['passed'] for c in checks)
        else 'HOLD','checks':checks,'scope':'ISOLATED_PG16_REDIS_EIGHT_SERVICES','hk_execution':'NOT_RUN',
        'browser_gate':'HOLD','six_vertical_gate':'HOLD','migration_scope':'DISPOSABLE_CI_DATABASE_ONLY'},indent=2)+'\n')
    # Preserve app diagnostics even if HTTP readiness fails; never archive container environments.
    for name in containers:
        if name in {PREFIX+'pg',PREFIX+'redis'}: continue
        log=cmd(['docker','logs',name],check=False)
        raw=scrub(log.stdout+'\n'+log.stderr)
        (OUT/('CI_'+name+'.log')).write_text(raw)
        state=cmd(['docker','inspect','--format','{{json .State}}',name],check=False)
        (OUT/('CI_'+name+'_state.json')).write_text(scrub(state.stdout))
        if len(checks)<20 or not all(c['passed'] for c in checks):
            print(name+'\n'+raw[-12000:],flush=True)
    for name in reversed(containers):
        cmd(['docker','rm','--force',name],check=False)
    cmd(['docker','network','rm',NET],check=False)
    cmd(['docker','volume','rm',VOLUME],check=False)
    envfile.unlink(missing_ok=True)
