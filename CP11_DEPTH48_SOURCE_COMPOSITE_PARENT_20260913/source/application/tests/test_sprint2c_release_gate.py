from pathlib import Path
import json, subprocess, sys
ROOT=Path(__file__).resolve().parents[1]
def test_release_artifacts_exist():
    for p in ['staging/certification/gates.yaml','staging/certification/real_device_e2e_matrix.csv','docs/release/STORE_SUBMISSION_CHECKLIST.md','.github/workflows/release-certification.yml']:
        assert (ROOT/p).exists()
def test_static_store_check_passes_structure():
    r=subprocess.run([sys.executable,str(ROOT/'scripts/store_release_static_check.py')],capture_output=True,text=True)
    assert r.returncode==0, r.stdout+r.stderr
    assert json.loads(r.stdout)['passed'] is True
def test_certification_gate_fails_closed_without_real_evidence(tmp_path):
    out=tmp_path/'gate.json'
    r=subprocess.run([sys.executable,str(ROOT/'scripts/sprint2c_certification_gate.py'),'--output',str(out)],capture_output=True,text=True)
    assert r.returncode==2
    d=json.loads(out.read_text())
    assert d['state']=='ENGINEERING_READY'
    assert d['blocker_count']>0
    assert d['gates']['TESTFLIGHT']['status']=='BLOCKED'
