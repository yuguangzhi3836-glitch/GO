import os, subprocess, sys, json
from pathlib import Path

def test_0101_named_provider_runner_fails_closed_without_credentials(tmp_path):
    env=os.environ.copy()
    for k in list(env):
        if k.startswith('STRIPE_TEST_') or k.startswith('SITEMINDER_CHANNELS_PLUS_') or k.startswith('SITEMINDER_CERT_'):
            env.pop(k,None)
    out=tmp_path/'evidence.json';env['P0_0101_EVIDENCE_PATH']=str(out)
    p=subprocess.run([sys.executable,'scripts/p0_0101_named_provider_certification.py'],env=env,capture_output=True,text=True,timeout=30)
    assert p.returncode==2
    payload=json.loads(out.read_text())
    assert payload['gate']=='BLOCK'
    assert 'STRIPE_TEST_SECRET_KEY' in payload['missing_required_inputs']
    assert 'SITEMINDER_CHANNELS_PLUS_API_ID' in payload['missing_required_inputs']
