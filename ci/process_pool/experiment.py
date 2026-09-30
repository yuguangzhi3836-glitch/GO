"""Mirror-order 2x2 attribution, followed by separately instrumented runs."""
from pathlib import Path
import hashlib,json,os,statistics,subprocess,sys
import importlib.util
_spec=importlib.util.spec_from_file_location('process_pool_run',Path(__file__).with_name('run.py'))
_run=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(_run)
ROOT,CONFIGS,validate=_run.ROOT,_run.CONFIGS,_run.validate

ORDER=(0,1,3,2,2,3,1,0)

def main():
    out=ROOT/'process-pool-evidence';out.mkdir(exist_ok=False)
    head=os.environ['EXPECTED_HEAD']
    summary={'head':head,'order':[CONFIGS[i] for i in ORDER],'rounds':[],'diagnostics':[],'status':'RUNNING','acceptance':False,'scope':'Fixed restored application; cold-process attribution only. Warm/continued revalidation is required before adoption.'}
    def save(): (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    save()
    try:
        for number,(instances,pool) in enumerate([CONFIGS[i] for i in ORDER],1):
            folder=out/f'{number}-{instances}x{pool}'
            with (out/f'{number}-command.log').open('w') as log:
                code=subprocess.call([sys.executable,str(ROOT/'ci/process_pool/run.py'),'--instances',str(instances),'--pool',str(pool),'--out',str(folder)],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
            assert code in (0,1)
            row=validate(folder,instances,pool,False,head);row.update(number=number,folder=folder.name)
            summary['rounds'].append(row);save();print('ROUND_COMPLETE',number,instances,pool,json.dumps(row['stages']),flush=True)
        for instances,pool in CONFIGS:
            folder=out/f'diagnostic-{instances}x{pool}'
            with (out/f'diagnostic-{instances}x{pool}-command.log').open('w') as log:
                code=subprocess.call([sys.executable,str(ROOT/'ci/process_pool/run.py'),'--instances',str(instances),'--pool',str(pool),'--out',str(folder),'--diagnostic'],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
            assert code in (0,1)
            row=validate(folder,instances,pool,True,head);row['folder']=folder.name
            summary['diagnostics'].append(row);save();print('DIAGNOSTIC_COMPLETE',instances,pool,flush=True)
        all_rows=summary['rounds']+summary['diagnostics']
        assert len({r['schema'] for r in all_rows})==12
        assert all(r['environment']==all_rows[0]['environment'] for r in all_rows)
        summary['medians']={f'{i}x{p}':{str(n):{key:statistics.median(s[key] for r in summary['rounds'] if (r['instances'],r['pool_per_instance'])==(i,p) for s in r['stages'] if s['concurrent_transactions']==n) for key in ('p95_ms','p99_ms','application_cpu_seconds','lifetime_cpu_seconds','sum_worker_max_rss_kib')} for n in (20,100)} for i,p in CONFIGS}
        summary['contrasts']={'parallelism_fixed_8_connections':['2x4','4x2'],'parallelism_fixed_16_connections':['2x8','4x4'],'pool_fixed_2_processes':['2x4','2x8'],'pool_fixed_4_processes':['4x2','4x4']}
        summary['status']='COMPLETE_ATTRIBUTION_NOT_ACCEPTANCE'
        return 0
    except Exception as exc:
        summary.update(status='INCOMPLETE_OR_INVALID',error_type=type(exc).__name__)
        raise
    finally:
        save()
        (out/'SHA256.json').write_text(json.dumps({str(f.relative_to(out)):hashlib.sha256(f.read_bytes()).hexdigest() for f in out.rglob('*') if f.is_file() and f!=out/'SHA256.json'},indent=2)+'\n')

if __name__=='__main__':raise SystemExit(main())
