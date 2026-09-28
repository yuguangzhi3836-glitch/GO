"""Explore bounded active work; queued actors never count as executing work."""
from pathlib import Path
import hashlib
import json
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
def read(path):return json.loads(path.read_text())
def valid(result):
    assert result['correctness']=='PASS'
    assert result['status'] in ('STOPPED_AT_FAILED_TIER','BOUNDED_SERVICE_PLAN_PASS','EXPERIMENT_PLAN_COMPLETE_NOT_CAPACITY_ACCEPTANCE')
    assert result['stages'] and all(s['errors']==0 and s['sql']=='PASS' for s in result['stages'])

def main():
    baseline=read(ROOT/'multi-instance-evidence/result.json');valid(baseline)
    valid(read(ROOT/'multi-profile-evidence/result.json'))
    out=ROOT/'multi-admission-evidence';out.mkdir(exist_ok=False)
    summary={'status':'RUNNING','mode':'EXPERIMENT_ONLY_NOT_CAPACITY_ACCEPTANCE',
             'baseline':baseline,'experiments':[],
             'scope':'Same runner and application; single run per limit. Queue wait included. No higher tiers than 100. No production admission implementation.'}
    try:
        for limit in (2,5):
            folder=out/f'active-{limit}-per-instance'
            code=subprocess.call([sys.executable,str(ROOT/'ci/multi_instance/run.py'),
                '--admission-active-per-instance',str(limit),'--out',str(folder)],cwd=ROOT)
            result=read(folder/'result.json');valid(result)
            assert code==(1 if result['status']=='STOPPED_AT_FAILED_TIER' else 0)
            assert result['mode']=='ADMISSION_EXPERIMENT_NOT_ACCEPTANCE'
            assert all(s['concurrent_transactions']<=100 and s['observed_peak_executing']<=2*limit for s in result['stages'])
            summary['experiments'].append(result)
            (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
        summary['status']='EXPERIMENT_COMPLETE_NOT_CAPACITY_ACCEPTANCE'
        # An experiment never turns the failed normal acceptance workflow green.
        return 0
    except Exception as exc:
        summary.update(status='INVALID_OR_CORRECTNESS_FAILED',error_type=type(exc).__name__,error=str(exc)[:500])
        raise
    finally:
        (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
        (out/'SHA256.json').write_text(json.dumps({str(p.relative_to(out)):hashlib.sha256(p.read_bytes()).hexdigest()
            for p in out.rglob('*') if p.is_file() and p!=out/'SHA256.json'},indent=2)+'\n')

if __name__=='__main__':raise SystemExit(main())
