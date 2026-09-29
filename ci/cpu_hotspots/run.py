"""Control then CPU probe, using unchanged correctness and latency gates."""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys
from importlib.metadata import version

ROOT=Path(__file__).resolve().parents[2]
HEAD=os.environ['EXPECTED_HEAD']

def write(path,value):
    path.write_text(json.dumps(value,indent=2,sort_keys=True)+'\n')

def main():
    assert subprocess.check_output(['git','rev-parse','HEAD'],text=True,cwd=ROOT).strip()==HEAD
    out=ROOT/'cpu-hotspot-evidence';out.mkdir(exist_ok=False)
    summary={'head':HEAD,'application_tree':subprocess.check_output(['git','rev-parse','HEAD:application'],text=True,cwd=ROOT).strip(),
        'yappi':version('yappi'),'rounds':[],'status':'RUNNING',
        'harness_sha256':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
            for folder in ('ci/multi_instance','ci/cpu_hotspots') for p in (ROOT/folder).glob('*.py')},
        'note':'Thread CPU discovery only; no throughput acceptance. Control and profile retain 13 correctness scenarios and original 20/100 stop gates. No warmup, pool/admission or application changes.'}
    try:
        for mode in ('control','profile'):
            folder=out/mode
            code=subprocess.call([sys.executable,str(Path(__file__).with_name('probe.py')),
                '--experimental-switch-interval-ms','5','--out',str(folder)],cwd=ROOT)
            result=json.loads((folder/'result.json').read_text())
            binding=json.loads((folder/'binding.json').read_text())
            assert binding['head']==HEAD and binding['application_tree']==summary['application_tree']
            assert binding['pool_per_instance']==5 and binding['max_overflow']==0
            assert binding['diagnostic_instrumentation'] is False
            assert binding['worker_switch_interval_ms']==5
            assert binding['p95_gate_ms']==5000 and binding['p99_gate_ms']==10000
            assert result['correctness']=='PASS' and result['stages']
            assert all(s['errors']==0 and s['sql']=='PASS' for s in result['stages'])
            assert code==(1 if result['status']=='STOPPED_AT_FAILED_TIER' else 0)
            item={'mode':mode,'binding':binding,'result':result,'exit_code':code}
            summary['rounds'].append(item);write(out/'summary.json',summary)
            print(json.dumps({'mode':mode,'stages':result['stages']}),flush=True)
        summary['status']='CPU_DISCOVERY_COMPLETE_NOT_CAPACITY_ACCEPTANCE'
    finally:
        write(out/'summary.json',summary)
        write(out/'SHA256.json',{str(p.relative_to(out)):hashlib.sha256(p.read_bytes()).hexdigest()
            for p in out.rglob('*') if p.is_file() and p!=out/'SHA256.json'})

if __name__=='__main__':main()
