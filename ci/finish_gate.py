"""Record exact JUnit results; skipped or incomplete checks never pass."""
import json
import os
from pathlib import Path
import xml.etree.ElementTree as ET

results={}
for name,minimum in [('migration_history',4),('postgres_existing',6),('postgres_expiry',30),('frontend_node22',115)]:
    path=Path('evidence',name+'.xml')
    if not path.exists():results[name]={'accepted':False,'reason':'MISSING_REPORT'};continue
    root=ET.parse(path).getroot()
    cases=list(root.iter('testcase'))
    bad=[e for c in cases for e in list(c) if e.tag in {'failure','error','skipped'}]
    results[name]={'tests':len(cases),'failures_errors_skips':len(bad),'accepted':len(cases)>=minimum and not bad}
queue=Path('evidence/redis_queue.txt')
results['redis_queue']={'accepted':queue.exists() and 'REDIS_QUEUE_SMOKE=PASS' in queue.read_text()}
results['prior_steps']={'accepted':os.environ.get('PRIOR_STEPS_STATUS')=='success'}
accepted=all(x['accepted'] for x in results.values())
Path('evidence/RUNTIME_GATE.json').write_text(json.dumps({'commit':os.environ.get('GITHUB_SHA'),
    'runtime_acceptance':'PASS' if accepted else 'HOLD','checks':results,
    'FINAL_RELEASE_GATE':'HOLD','engineering_complete':False,
    'remaining':['Whole-system business depth','Full master requirement acceptance','Actual browser and cross-device visual acceptance']},indent=2)+'\n')
print(json.dumps(results));raise SystemExit(0 if accepted else 1)
