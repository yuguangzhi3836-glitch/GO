"""Prove each collected test has exactly one completed shard execution."""
import hashlib
import json
import os
from pathlib import Path
import xml.etree.ElementTree as ET

root=Path('all-evidence')
paths=sorted(root.glob('GO-DEPTH36-predeployment-*-shard-*/backend-inventory.json'))
assert len(paths)==4,('MISSING_SHARD_RECORD',len(paths))
inventories=[json.loads(p.read_text()) for p in paths]
all_ids=inventories[0]['all_nodeids']
assert all_ids and len(all_ids)==len(set(all_ids))
seen=[]; indices=[]; summaries=[]; counts={'tests':0,'failures':0,'errors':0,'skipped':0}
for path,inv in zip(paths,inventories):
    assert inv['candidate']==os.environ['SEALED_CANDIDATE']
    assert inv['source_tree_sha256']==os.environ['EXPECTED_SOURCE_TREE']
    assert inv['total_shards']==4 and inv['all_nodeids']==all_ids
    assert inv['pytest_exitstatus']==0,('PYTEST_NOT_SUCCESSFUL',inv['shard'])
    indices.append(inv['shard']); seen.extend(inv['selected_nodeids'])
    assert set(inv['reports'])==set(inv['selected_nodeids']),('UNEXECUTED_TEST',inv['shard'])
    for nodeid,reports in inv['reports'].items():
        assert any(r['when']=='teardown' for r in reports),('INCOMPLETE_TEST',nodeid)
        assert not any(r['outcome']=='failed' for r in reports),('FAILED_TEST',nodeid)
        assert any(r['when']=='call' and r['outcome']=='passed' or r['outcome']=='skipped' for r in reports)
    xml=path.parent/'backend-full.xml'
    suites=list(ET.fromstring(xml.read_bytes()).iter('testsuite'))
    assert sum(int(s.get('tests')) for s in suites)==len(inv['selected_nodeids'])
    for s in suites:
        for key in counts: counts[key]+=int(s.get(key,'0'))
    post=json.loads((path.parent/'post-test-source.json').read_text())
    assert post['source_after_tests']=='PASS' and not post['mismatches']
    summaries.append({'shard':inv['shard'],'selected':len(inv['selected_nodeids']),
                      'inventory_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                      'junit_sha256':hashlib.sha256(xml.read_bytes()).hexdigest()})
assert sorted(indices)==[0,1,2,3]
assert len(seen)==len(set(seen))==len(all_ids) and set(seen)==set(all_ids)
assert counts['tests']==len(all_ids) and counts['failures']==counts['errors']==0
result={'coverage':'PASS','candidate':os.environ['SEALED_CANDIDATE'],
        'source_tree_sha256':os.environ['EXPECTED_SOURCE_TREE'],
        'collected':len(all_ids),'test_files':len({x.split('::',1)[0] for x in all_ids}),
        'exactly_once':True,'counts':counts,'passed':counts['tests']-counts['skipped'],
        'shards':summaries,'postgres_gate':'NOT_RUN','browser_gate':'HOLD','final_release':'HOLD'}
Path('coverage.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
