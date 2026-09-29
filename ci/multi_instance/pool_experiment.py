"""Same-runner ABBA pool-size experiment; ordinary pool-5 gate remains authoritative."""
from pathlib import Path
import hashlib
import json
import os
import statistics
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
HEAD = os.environ['EXPECTED_HEAD']
ORDER = (5, 10, 10, 5)


def write(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')


def main():
    out = ROOT / 'multi-pool-experiment-evidence'
    out.mkdir(exist_ok=False)
    assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip() == HEAD
    tree = subprocess.check_output(['git','rev-parse','HEAD:application'],cwd=ROOT,text=True).strip()
    summary = {'head': HEAD, 'application_tree':tree,
        'harness_sha256': {p.name:hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (ROOT/'ci/multi_instance').glob('*.py')},
        'order':ORDER,'instrumentation':False,
        'scope':'isolated two-service PostgreSQL experiment on one CI runner; 20 and 100 complete synthetic transactions only; no HTTP, real PSP, supplier, production capacity, or capacity acceptance',
        'rounds':[],'status':'RUNNING'}
    write(out/'summary.json',summary)
    try:
        for number,pool_size in enumerate(ORDER,1):
            folder=out/f'{number}-pool-{pool_size}'
            command=[sys.executable,str(ROOT/'ci/multi_instance/run.py'),'--out',str(folder),'--pool-comparison-control']
            if pool_size==10:command+=['--experimental-pool-size','10']
            code=subprocess.call(command,cwd=ROOT)
            binding=json.loads((folder/'binding.json').read_text())
            result=json.loads((folder/'result.json').read_text())
            assert binding['head']==HEAD and binding['application_tree']==tree
            assert binding['pool_per_instance']==pool_size and binding['max_overflow']==0
            assert binding['p95_gate_ms']==5000 and binding['p99_gate_ms']==10000
            assert binding['diagnostic_instrumentation'] is False
            assert result['correctness']=='PASS' and len(result['stages'])==2
            assert all(s['errors']==0 and s['sql']=='PASS' for s in result['stages'])
            assert result['status'] in ('STOPPED_AT_FAILED_TIER','EXPERIMENT_PLAN_COMPLETE_NOT_CAPACITY_ACCEPTANCE')
            assert code==(1 if result['status']=='STOPPED_AT_FAILED_TIER' else 0)
            summary['rounds'].append({'number':number,'pool_per_instance':pool_size,
                'head':HEAD,'application_tree':tree,'environment':{
                    k:binding[k] for k in ('cpu_count','cpu_model','database_version','installed_packages','python','instances','max_connections')},
                'correctness':result['correctness'],'status':result['status'],'stages':result['stages'],'exit_code':code})
            write(out/'summary.json',summary)
            print(json.dumps(summary['rounds'][-1]),flush=True)
        environments=[r['environment'] for r in summary['rounds']]
        assert all(e==environments[0] for e in environments),'ENVIRONMENT_CHANGED'
        summary['median_p95_ms']={str(pool):{str(n):statistics.median(s['p95_ms']
            for r in summary['rounds'] if r['pool_per_instance']==pool
            for s in r['stages'] if s['concurrent_transactions']==n)
            for n in (20,100)} for pool in (5,10)}
        summary['status']='COMPARISON_COMPLETE_EXPERIMENT_ONLY'
        return 0
    except Exception as exc:
        summary.update(status='COMPARISON_INVALID_OR_CORRECTNESS_FAILED',error_type=type(exc).__name__,error=str(exc)[:300])
        raise
    finally:
        write(out/'summary.json',summary)
        write(out/'SHA256.json',{str(p.relative_to(out)):hashlib.sha256(p.read_bytes()).hexdigest()
            for p in out.rglob('*') if p.is_file() and p!=out/'SHA256.json'})


if __name__=='__main__':raise SystemExit(main())
