import json, pathlib, subprocess, sys, os
ROOT=pathlib.Path(__file__).resolve().parents[1]

def test_credential_manifest_has_15_gate_dependencies():
    text=(ROOT/'staging/bringup/credentials.yaml').read_text()
    for gate in ['PG16','REDIS','PSP','CONNECTOR','APNS','FCM','APPLE_SIGNING','GOOGLE_SIGNING']:
        assert gate in text

def test_gate_ledger_starts_fail_closed():
    d=json.loads((ROOT/'staging/certification/status.sprint2d.json').read_text())
    assert d['state']=='BLOCKED'
    assert len(d['gates'])==15
    assert all(v['status']=='BLOCKED' for v in d['gates'].values())

def test_preflight_fails_closed_without_credentials(tmp_path):
    env=os.environ.copy()
    for name in list(env):
        if name.startswith(('STAGING_','PSP_','REAL_CONNECTOR_','EXPO_','APPLE_','ASC_','APNS_','GOOGLE_','FIREBASE_','GO_APP_','IOS_','ANDROID_')):
            env.pop(name,None)
    report = tmp_path / 'reports' / 'preflight.json'
    source_report = ROOT / 'staging/bringup/preflight.local.json'
    before = source_report.read_bytes() if source_report.exists() else None
    p=subprocess.run([sys.executable,str(ROOT/'scripts/sprint2d_preflight.py'), '--output', str(report)],cwd=ROOT,env=env,capture_output=True,text=True)
    assert p.returncode==2
    assert 'BLOCKED_CREDENTIALS' in p.stdout
    assert json.loads(p.stdout)['report'] == str(report)
    result = json.loads(report.read_text())
    assert all(gate['credential_preflight'] == 'BLOCKED' for gate in result['gates'].values())
    assert result['network_probes'] == {}
    assert (source_report.read_bytes() if source_report.exists() else None) == before

def test_release_workflow_waits_for_store_build_and_submit():
    s=(ROOT/'.github/workflows/real-environment-bringup.yml').read_text()
    assert 'eas-cli build --platform ios' in s and '--wait' in s
    assert 'eas-cli submit --platform ios' in s
    assert 'eas-cli submit --platform android' in s

def test_evidence_template_forbids_secrets():
    d=json.loads((ROOT/'staging/bringup/evidence-template.json').read_text())
    assert 'Do not include tokens' in d['notes']
