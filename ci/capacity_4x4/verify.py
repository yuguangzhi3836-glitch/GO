"""Strict readback for fixed four-process/four-connection validation."""
from pathlib import Path
import hashlib,importlib.util,json,statistics,sys,xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('pp4',ROOT/'ci/process_pool/run.py')
pp=importlib.util.module_from_spec(spec);spec.loader.exec_module(pp)
sys.path.insert(0,str(ROOT/'ci/journey_latency'))
from verify import verify_journey

def verify(folder,head):
    folder=Path(folder);tree='6570b66bc977f89c0311d67bdc6b721cd70d4e09'
    rounds=[]
    for number in (1,2):
        f=folder/f'formal-{number}'
        row=pp.validate(f,4,4,False,head)
        assert all(s['pass'] for s in row['stages'])
        rounds.append(row)
    journeys=[]
    for number in (1,2):
        journeys.append(verify_journey(folder/f'journey-{number}',head,tree,4,4))
    assert len({r['schema'] for r in rounds}|{j['schema'] for j in journeys})==4
    assert rounds[0]['environment']==rounds[1]['environment']
    formal={str(n):{k:statistics.median(s[k] for r in rounds for s in r['stages'] if s['concurrent_transactions']==n) for k in ('p95_ms','p99_ms','application_cpu_seconds','lifetime_cpu_seconds','sum_worker_max_rss_kib')} for n in (20,100)}
    modes={}
    for concurrency in (20,100):
        for mode in ('PROCESS_COLD_FIRST_BATCH','CONTINUED_PROCESS'):
            rows=[m for j in journeys for m in j['metrics'] if m['concurrency']==concurrency and m['operation']=='full_transaction' and m['mode']==mode]
            modes[f'{concurrency}-{mode}']={k:statistics.median(r[k] for r in rows) for k in ('p95_ms','p99_ms','process_cpu_seconds','max_worker_rss_kib')}
    result={'status':'PASS_4X4_SYNTHETIC_SCOPE','head':head,'application_tree':tree,'formal':formal,'full_transaction':modes,'orders_verified':sum(j['orders_verified'] for j in journeys),'limitations':['not HTTP/auth/network','simulated supplier/PSP','two journey repetitions; not soak','application CPU excludes PostgreSQL','original 2-vCPU and 2-process configurations remain FAIL']}
    (folder/'verified-summary.json').write_text(json.dumps(result,indent=2)+'\n')
    return result

if __name__=='__main__':
    target=Path(sys.argv[1]);head=sys.argv[2]
    print(json.dumps(verify(target,head),indent=2))
