"""Check static inventory completeness and source/evidence immutability only."""
import ast,hashlib,json
from pathlib import Path
out=Path(__file__).resolve().parent
root=out.parents[3]
data=json.loads((out/'CALLBACK_INVENTORY.json').read_text())
actual=[]
for file in sorted((root/'application/src/go_hotel/api/routes').glob('*.py')):
 for fn in ast.parse(file.read_text()).body:
  if not isinstance(fn,(ast.FunctionDef,ast.AsyncFunctionDef)):continue
  for call in ast.walk(fn):
   if isinstance(call,ast.Call) and isinstance(call.func,ast.Name) and call.func.id in {'run_idempotent','run_idempotent_async'}:
    actual.append((str(file.relative_to(root)),fn.name,call.lineno,ast.literal_eval(call.args[0])))
recorded=[(r['route_file'],r['function'],r['call_line'],r['operation']) for r in data['rows']]
assert sorted(actual)==sorted(recorded)
assert len(recorded)==len(set(recorded))==37
assert len({r['operation'] for r in data['rows']})==34
assert len({r['route_file'] for r in data['rows']})==9
for row in data['rows']:
 for field in ['classification','precommit_failure_boundary','postcommit_or_uncertain_boundary','available_durable_keys','minimal_recovery_hook','review_sources']:
  assert row[field],(row['id'],field)
for op in ['FLIGHT_CHECKOUT','FLIGHT_EXECUTE_CHANGE']:
 row=next(r for r in data['rows'] if r['operation']==op)
 assert row['priority']=='P0'
sources=json.loads((out/'SOURCE_SHA256.json').read_text())
for path,expected in sources.items():
 assert hashlib.sha256((root/path).read_bytes()).hexdigest()==expected,('review source changed',path)
prior_count=0
for line in (out.parent/'SHA256SUMS').read_text().splitlines():
 expected,name=line.split('  ',1)
 assert hashlib.sha256((out.parent/name).read_bytes()).hexdigest()==expected,('original evidence changed',name)
 prior_count+=1
print(json.dumps({'task_id':'V70-R2-C11-02','check':'STATIC_INVENTORY_AND_IMMUTABILITY','result':'PASS','callsites':37,'operations':34,'route_files':9,'source_files_verified':len(sources),'original_c11_evidence_files_verified':prior_count,'runtime_tests_executed':0,'original_post_commit_gap':'HOLD_UNFIXED','C14':'NOT_SELF_SIGNED','C13':'NOT_SELF_SIGNED'},indent=2))
