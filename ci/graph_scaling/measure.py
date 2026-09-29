import ast, json, statistics, sys, time, subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'application/src'),str(ROOT/'application/tests')]
import go_hotel.services.order_supplier_fulfillment as module
import test_supplier_money_graph_scaling as fixture
source=subprocess.check_output(['git','show','886e1e90a2e5ff10873e06e81e5ac4442c3c93ab:application/src/go_hotel/services/order_supplier_fulfillment.py'],cwd=ROOT,text=True)
node=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=='_payment_state')
namespace=dict(vars(module));exec(compile(ast.Module(body=[node],type_ignores=[]),'baseline-payment-state','exec'),namespace)
baseline=namespace['_payment_state'];candidate=module._payment_state
rows_out=[]
for parents in (1,100,1000,2000):
    samples={'baseline':[],'candidate':[]};visits={}
    for label,function in [('baseline',baseline),('candidate',candidate)]:
        fixture._payment_state=function
        counted=fixture.split_graph(parents);assert fixture.evaluate(counted,parents*100)=='PAID'
        visits[label]=counted.visits
    for label,function in [('baseline',baseline),('candidate',candidate),('candidate',candidate),('baseline',baseline)]*2:
        fixture._payment_state=function
        rows=list(fixture.split_graph(parents))
        begin=time.process_time_ns();result=fixture.evaluate(rows,parents*100);elapsed=(time.process_time_ns()-begin)/1e9
        assert result=='PAID'
        samples[label].append(elapsed)
    med={k:statistics.median(v) for k,v in samples.items()}
    rows_out.append({'rows':parents*2,'row_visits':visits,'cpu_samples_seconds':samples,'median_cpu_seconds':med,'cpu_ratio':med['candidate']/med['baseline']})
result={'baseline_source':'886e1e90a2e5ff10873e06e81e5ac4442c3c93ab:application/src/go_hotel/services/order_supplier_fulfillment.py','scope':'Local in-memory bound graph component only; no database latency or full transaction CPU claim. Four samples per label after both functions warm; plain lists during timing. Counted list row visits collected separately are deterministic complexity evidence. Same process and prebuilt row objects.','rows':rows_out}
Path('graph-component-measurement.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
