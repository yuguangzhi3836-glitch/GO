"""Offline evidence recovery/audit only; never runs application tests or services."""
import base64
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent
CANDIDATE = '7bd98db21ee950aeb91c12b296b1864b5a758c3f'
TREE = 'c58edb0c0568c3f9fe80ba014c260513a07a8e74b211b608ade4d9052f8645b3'
NAMES = {'source-lineage.json', 'post-test-source.json', 'backend-full.xml',
         'backend-inventory.json', 'bundle-build.json', 'bundle-restore.json',
         'http-runtime-binding.json', 'http-checks.json', 'http-result.json',
         'packaging-tests.log'}

def require(ok, detail):
    if not ok:
        raise ValueError(detail)

def sha(data):
    return hashlib.sha256(data).hexdigest()

def save(relative, data):
    p = ROOT / relative
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():
        require(p.read_bytes() == data, 'Refuse overwrite of different evidence: '+str(relative))
    else:
        p.write_bytes(data)

def save_json(relative, obj):
    save(relative, (json.dumps(obj, indent=2, ensure_ascii=False)+'\n').encode())

def body(line):
    return re.sub(r'^\d{4}-\d\d-\d\dT\S+Z ', '', line)

def recover(shard):
    path = ROOT / 'shards' / str(shard) / 'workflow.log'
    active = None
    found = {}
    for lineno, line in enumerate(path.read_text().splitlines(), 1):
        line = body(line)
        if line.startswith('GO_EVIDENCE_FILE_BEGIN '):
            require(active is None, 'Nested frame')
            _, name, size, digest = line.split()
            require(name in NAMES and name not in found, 'Invalid/duplicate filename: '+name)
            active = {'name':name, 'bytes':int(size), 'sha256':digest, 'begin_line':lineno, 'chunks':[]}
        elif line.startswith('GO_EVIDENCE_B64 '):
            require(active is not None, 'Unframed base64')
            active['chunks'].append(line.split(' ', 1)[1])
        elif line.startswith('GO_EVIDENCE_FILE_END '):
            name = line.split(' ', 1)[1]
            require(active is not None and name == active['name'], 'Mismatched frame end')
            data = base64.b64decode(''.join(active.pop('chunks')), validate=True)
            require(len(data) == active['bytes'] and sha(data) == active['sha256'], 'Byte/hash mismatch: '+name)
            active['end_line'] = lineno
            save(Path('shards')/str(shard)/name, data)
            found[name] = active
            active = None
    require(active is None and set(found) == NAMES, 'Incomplete shard '+str(shard))
    return {'shard':shard, 'log_sha256':sha(path.read_bytes()), 'files':list(found.values())}

def load(shard, name):
    return json.loads((ROOT/'shards'/str(shard)/name).read_bytes())

def junit_identity(nodeid):
    # Parameter IDs may themselves contain ::, e.g. an IPv6 URL.
    identity, bracket, parameters = nodeid.partition('[')
    parts = identity.split('::')
    classname = parts[0][:-3].replace('/', '.')
    if len(parts) > 2:
        classname += '.' + '.'.join(parts[1:-1])
    return classname, parts[-1] + bracket + parameters

def coverage_from_log():
    text = '\n'.join(body(x) for x in (ROOT/'coverage/workflow.log').read_text().splitlines())
    marker = '{\n  "coverage": "PASS",'
    require(text.count(marker) == 1, 'Missing/ambiguous raw coverage object')
    start = text.index(marker)
    obj, end = json.JSONDecoder().raw_decode(text[start:])
    # Preserve the exact printed JSON lines, minus GitHub timestamps; no ZIP-byte claim.
    save('coverage/coverage.from-log.json', (text[start:start+end]+'\n').encode())
    return obj

def audit():
    recovered = [recover(s) for s in range(4)]
    original = coverage_from_log()
    all_ids = load(0, 'backend-inventory.json')['all_nodeids']
    require(len(all_ids) == 1679 and len(set(all_ids)) == len(all_ids), 'Invalid full collection')
    selected = []
    total = Counter(tests=0, failures=0, errors=0, skipped=0)
    shards, skips = [], []
    for s in range(4):
        inv = load(s, 'backend-inventory.json')
        require(inv['candidate'] == CANDIDATE and inv['source_tree_sha256'] == TREE, 'Lineage mismatch')
        require(inv['shard'] == s and inv['total_shards'] == 4 and inv['pytest_exitstatus'] == 0, 'Shard/exit mismatch')
        require(inv['all_nodeids'] == all_ids, 'Collection disagreement')
        ids = inv['selected_nodeids']
        require(len(ids) == len(set(ids)) and set(ids) == set(inv['reports']), 'Missing/duplicate execution reports')
        selected.extend(ids)
        for nodeid, reports in inv['reports'].items():
            phases = [r['when'] for r in reports]
            require(len(phases) == len(set(phases)) and set(phases) <= {'setup','call','teardown'}, 'Duplicate/invalid phases')
            require('teardown' in phases and all(r['outcome'] != 'failed' for r in reports), 'Incomplete/failed test')
            require(any((r['when']=='call' and r['outcome']=='passed') or r['outcome']=='skipped' for r in reports), 'No terminal outcome')
            owner = int(hashlib.sha256(nodeid.split('::',1)[0].encode()).hexdigest()[:8],16)%4
            require(owner == s, 'Wrong shard ownership')
        xml = (ROOT/'shards'/str(s)/'backend-full.xml').read_bytes()
        element = ET.fromstring(xml)
        cases = list(element.iter('testcase'))
        suites = list(element.iter('testsuite'))
        counts = {k:sum(int(x.get(k,'0')) for x in suites) for k in total}
        actual = {'tests':len(cases), 'failures':sum(x.find('failure') is not None for x in cases),
                  'errors':sum(x.find('error') is not None for x in cases),
                  'skipped':sum(x.find('skipped') is not None for x in cases)}
        require(actual == counts and counts['tests'] == len(ids), 'JUnit count mismatch')
        require(not counts['failures'] and not counts['errors'], 'JUnit failure')
        # Match individual JUnit identities to collected pytest identities, not just totals.
        expected_cases = Counter(junit_identity(n) for n in ids)
        require(Counter((c.get('classname'),c.get('name')) for c in cases) == expected_cases,
                'JUnit identities disagree with inventory')
        for c in cases:
            skipped = c.find('skipped')
            if skipped is not None:
                skips.append({'shard':s, 'classname':c.get('classname'), 'name':c.get('name'),
                              'message':skipped.get('message'), 'detail':skipped.text})
        lineage = load(s, 'source-lineage.json')
        post = load(s, 'post-test-source.json')
        require(lineage['candidate']==CANDIDATE and lineage['source_tree_sha256']==TREE and lineage['verified_files']==1267, 'Runtime source mismatch')
        require(post['source_after_tests']=='PASS' and not post['mismatches'], 'Post-test source drift')
        require(post['verified_files']==1267, 'Post-test file scope mismatch')
        for name in ['bundle-build.json','bundle-restore.json']:
            bundle = load(s, name)
            require(bundle['source_tree_sha256']==TREE and bundle['verified_files']==1267 and
                    bundle['archive_sha256']=='b4634f9da515a22f95fb740b979c2f77fdce29342eabbb9c54e5c666976f5b86' and
                    bundle['scope']=='OFFLINE_BUNDLE_INTEGRITY', 'Bundle record mismatch')
        http = load(s, 'http-checks.json')
        result = load(s, 'http-result.json')
        binding = load(s, 'http-runtime-binding.json')
        require(http['source_tree_sha256']==TREE and len(http['checks'])==148 and
                all(c['passed'] is True for c in http['checks']), 'HTTP checks mismatch')
        require(result['checks_passed']==148 and result['failed']==0 and result['http_requests']==87 and
                result['scope']=='LIVE_LOOPBACK_HTTP_ONLY', 'HTTP result mismatch')
        require(binding['source_tree_sha256']==TREE and binding['verified_source_files']==1267 and
                binding['mode']=='ISOLATED_SQLITE_HTTP' and binding['data_class']=='SYNTHETIC_ONLY', 'HTTP binding mismatch')
        packaging = (ROOT/'shards'/str(s)/'packaging-tests.log').read_text()
        require(re.search(r'Ran 10 tests in ', packaging) and packaging.rstrip().endswith('OK'), 'Packaging result mismatch')
        total.update(counts)
        shards.append({'shard':s, 'selected':len(ids), 'passed':counts['tests']-counts['skipped'],
                       'counts':counts, 'inventory_sha256':sha((ROOT/'shards'/str(s)/'backend-inventory.json').read_bytes()),
                       'junit_sha256':sha(xml)})
    require(len(selected)==len(set(selected))==len(all_ids) and set(selected)==set(all_ids), 'Incomplete/duplicate global coverage')
    require(original['candidate']==CANDIDATE and original['source_tree_sha256']==TREE, 'Coverage lineage mismatch')
    require(original['counts']==dict(total) and original['passed']==total['tests']-total['skipped'], 'Coverage totals mismatch')
    require(original['collected']==len(all_ids) and original['test_files']==len({n.split('::',1)[0] for n in all_ids}) and original['exactly_once'] is True, 'Coverage scope mismatch')
    for a,b in zip(shards, original['shards']):
        require(all(a[k]==v for k,v in b.items()), 'Coverage shard hash/count mismatch')
    require(len(original['shards'])==4 and len(skips)==6, 'Unexpected shard/skip count')
    result = {'audit':'PASS', 'method':'Offline strict Base64/length/SHA256 recovery, independent inventory/JUnit identity/phase/count/coverage audit; no application test rerun',
              'run_id':34453179558, 'candidate':CANDIDATE, 'source_tree_sha256':TREE,
              'decoded_original_files':40, 'raw_logs':5, 'collected':len(all_ids),
              'exactly_once':True, 'counts':dict(total), 'passed':total['tests']-total['skipped'],
              'source_files_verified_by_ci':1267, 'shards':shards,
              'coverage_json_origin':'Exact printed JSON recovered from coverage job log with timestamp prefixes removed; not a downloaded artifact ZIP',
              'artifact_zip_verification_record':'verification/artifact-audit.json (separate offline audit)',
              'three_end_real_ux_login':'HOLD','six_vertical_real_e2e':'HOLD', 'sealed_node_gate':'HOLD','final_release':'HOLD',
              'hk_execution_verified':False, 'deployed':False}
    save_json('verification/frame-checks.json', recovered)
    save_json('verification/skipped-tests.json', skips)
    save_json('verification/independent-audit.json', result)
    print(json.dumps(result, indent=2))

if __name__ == '__main__':
    audit()
