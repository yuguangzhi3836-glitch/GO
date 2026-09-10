"""Export named, nonsecret CI records; never include private runtime state."""
import base64
import hashlib
import json
from pathlib import Path

root=Path('restored')
manifest=Path('candidate/deliverables/CP11_DEPTH36R3_MOBILE_CONTRACT_20260910/SOURCE_FINGERPRINT.json')
evidence=Path('evidence'); evidence.mkdir(exist_ok=True)
result={'source_after_tests':'UNKNOWN','browser_gate':'HOLD','final_release':'HOLD'}
if manifest.exists() and root.exists():
    fp=json.loads(manifest.read_text())
    errors=[p for p,h in fp.items() if not (root/p).is_file() or hashlib.sha256((root/p).read_bytes()).hexdigest()!=h]
    result.update(source_after_tests='PASS' if not errors else 'FAIL',verified_files=len(fp),mismatches=errors)
(evidence/'post-test-source.json').write_text(json.dumps(result,indent=2)+'\n')
for name in ['source-lineage.json','post-test-source.json','backend-full.xml','backend-inventory.json','bundle-build.json',
             'bundle-restore.json','http-runtime-binding.json','http-checks.json','http-result.json','packaging-tests.log']:
    path=evidence/name
    if not path.exists():
        print('GO_EVIDENCE_MISSING',name); continue
    data=path.read_bytes()
    print('GO_EVIDENCE_FILE_BEGIN',name,len(data),hashlib.sha256(data).hexdigest())
    encoded=base64.b64encode(data).decode()
    for offset in range(0,len(encoded),400): print('GO_EVIDENCE_B64',encoded[offset:offset+400])
    print('GO_EVIDENCE_FILE_END',name)
if result['source_after_tests']!='PASS': raise SystemExit('SOURCE_AFTER_TESTS_NOT_VERIFIED')
