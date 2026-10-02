import hashlib
import json
from pathlib import Path
import sys
import pytest
sys.path.insert(0, str(Path(__file__).parent))
from verify import verify_journey
from measure import summarize


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def fixture(folder, tamper=None):
    result={'status':'MEASUREMENT_COMPLETE_NOT_CAPACITY_ACCEPTANCE','operations':[],
            'checks':[{'sql':'PASS','ownership_denial':'PASS'} for _ in range(2)]}
    orders=[]
    for n in (20,100):
        for op in ('create_order','payment_confirm','order_query','full_transaction'):
            directory=folder/f'tier-{n}'/op
            startups=[{'pid':i+1,'initial_pool_connections':0,'initial_configured_mappers':0,
                       'launch_ns':1,'child_entry_ns':2,'ready_ns':3,'import_cpu_seconds':.1} for i in range(2)]
            write(directory/'startups.json',startups)
            batches=[]
            for batch in range(4):
                rows=[{'pid':i%2+1,'owner':f'{n}-{batch}-{i}', 'batch':batch,'operation':op,'ok':True,
                       'start_ns':100+i,'end_ns':10000+i,'duration_ms':.0099,
                       'value':{'order_id':f'{op}-{n}-{batch}-{i}'}} for i in range(n)]
                if tamper in ('overlap','overlap_ledger') and n==100 and op=='order_query' and batch==1:
                    rows[-1]['start_ns']=10001
                    rows[-1]['duration_ms']=(rows[-1]['end_ns']-rows[-1]['start_ns'])/1e6
                summary={'batch':batch,'mode':'PROCESS_COLD_FIRST_BATCH' if batch==0 else 'CONTINUED_PROCESS',
                         'requested_concurrency':n,'release_ns':99,**summarize(rows),
                         'process_cpu_seconds':2.,'max_worker_rss_kib':100.}
                if tamper=='percentile' and n==100 and batch==3: summary['p95_ms']+=1
                if tamper=='pid' and n==100 and batch==3: summary['pids']=[9,10]
                if tamper=='mode' and batch==0:summary['mode']='CONTINUED_PROCESS'
                if tamper=='cpu':summary['process_cpu_seconds']=float('nan')
                write(directory/f'batch-{batch}-raw.json',rows)
                write(directory/f'batch-{batch}-summary.json',summary)
                for i in range(2):
                    write(directory/f'worker-{i}/batch-{batch}.json',{'rows':rows[i::2],'process_cpu_seconds':1.})
                batches.append(summary)
                if op in ('create_order','full_transaction'):orders += [r['value']['order_id'] for r in rows]
            result['operations'].append({'concurrency':n,'operation':op,'batches':batches})
    binding={'head':'head','application_tree':'tree','tiers':[20,100],'batches_per_operation':4,
             'instances_per_operation':2,'pool_per_instance':5,'max_overflow':0,
             'original_formal_p95_ms':5000,'original_formal_p99_ms':10000,'schema':'mi_test',
             **{k:'synthetic' for k in ('cpu_count','cpu_model','python','platform','packages','postgresql')}}
    if tamper=='binding':binding['application_tree']='wrong'
    facts=[{'order_id':oid,'order_status':'COMPLETED','trips_state':'COMPLETED','attempts':1,
            'ledger_entries':2,'capture_amount_minor':16800,'ledger_debit_minor':16800,
            'ledger_credit_minor':16800} for oid in orders]
    if tamper in ('ledger','overlap_ledger'):facts[-1]['ledger_credit_minor']=1
    write(folder/'tier-100/ledger-facts.json',facts)
    write(folder/'result.json',result);write(folder/'binding.json',binding);write(folder/'exit.json',{'exit_code':0})
    write(folder/'SHA256.json',{str(p.relative_to(folder)):hashlib.sha256(p.read_bytes()).hexdigest()
                              for p in folder.rglob('*') if p.is_file()})


def test_complete_raw_measurement_reconciles(tmp_path):
    fixture(tmp_path)
    assert verify_journey(tmp_path,'head','tree')['orders_verified']==960


@pytest.mark.parametrize('tamper',['percentile','pid','mode','cpu','binding','ledger'])
def test_rehashed_invalid_evidence_is_still_rejected(tmp_path,tamper):
    fixture(tmp_path,tamper)
    with pytest.raises(AssertionError):verify_journey(tmp_path,'head','tree')


def test_collecting_shortfall_keeps_rejection_and_checks_remaining_facts(tmp_path):
    fixture(tmp_path, 'overlap')
    with pytest.raises(AssertionError, match='JOURNEY_CONCURRENCY_SHORTFALL'):
        verify_journey(tmp_path, 'head', 'tree')
    report=verify_journey(tmp_path, 'head', 'tree', collect_shortfalls=True)
    assert report['concurrency_valid'] is False
    assert report['concurrency_shortfalls']==[{'concurrency':100,'operation':'order_query','batch':1,'observed_peak_inflight':99}]
    assert report['orders_verified']==960 and len(report['metrics'])==32


def test_shortfall_collection_does_not_ignore_ledger_failure(tmp_path):
    fixture(tmp_path, 'overlap_ledger')
    with pytest.raises(AssertionError):
        verify_journey(tmp_path, 'head', 'tree', collect_shortfalls=True)
