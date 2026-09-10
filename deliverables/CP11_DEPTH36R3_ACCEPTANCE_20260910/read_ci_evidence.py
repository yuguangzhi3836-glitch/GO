"""Recover original named records from a GitHub job log and verify byte hashes."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

p = argparse.ArgumentParser()
p.add_argument('log', type=Path)
p.add_argument('output', type=Path)
a = p.parse_args()
a.output.mkdir(parents=True, exist_ok=False)
active = None
records = {}
missing = []
for line in a.log.read_text().splitlines():
    begin = re.search(r'GO_EVIDENCE_FILE_BEGIN ([a-zA-Z0-9_.-]+) (\d+) ([a-f0-9]{64})$', line)
    chunk = re.search(r'GO_EVIDENCE_B64 ([a-zA-Z0-9+/=]+)$', line)
    end = re.search(r'GO_EVIDENCE_FILE_END ([a-zA-Z0-9_.-]+)$', line)
    absent = re.search(r'GO_EVIDENCE_MISSING ([a-zA-Z0-9_.-]+)$', line)
    if begin:
        if active is not None or begin[1] in records:
            raise ValueError('DUPLICATE_OR_NESTED_RECORD')
        active = [begin[1], int(begin[2]), begin[3], []]
    elif chunk:
        if active is None:
            raise ValueError('CHUNK_WITHOUT_RECORD')
        active[3].append(chunk[1])
    elif end:
        if active is None or active[0] != end[1]:
            raise ValueError('END_WITHOUT_MATCHING_RECORD')
        name, size, digest, chunks = active
        data = base64.b64decode(''.join(chunks), validate=True)
        if len(data) != size or hashlib.sha256(data).hexdigest() != digest:
            raise ValueError('RECORD_BYTE_HASH_MISMATCH:' + name)
        (a.output / name).write_bytes(data)
        records[name] = {'bytes': size, 'sha256': digest}
        active = None
    elif absent:
        missing.append(absent[1])
if active is not None or not records:
    raise ValueError('INCOMPLETE_OR_ABSENT_RECORDS')
summary = {'raw_job_log_sha256': hashlib.sha256(a.log.read_bytes()).hexdigest(),
           'records': records, 'explicitly_missing': missing}
xml = a.output / ('backend-full.xml' if (a.output / 'backend-full.xml').exists() else 'backend-scoped.xml')
if xml.exists():
    root = ET.fromstring(xml.read_bytes())
    cases = list(root.iter('testcase'))
    failures, errors, skipped = [], [], []
    for case in cases:
        for tag, target in [('failure', failures), ('error', errors), ('skipped', skipped)]:
            for item in case.findall(tag):
                target.append({'class': case.get('classname'), 'name': case.get('name'),
                               'message': item.get('message'), 'text': item.text})
    summary['backend'] = {'tests': len(cases), 'passed': len(cases)-len(failures)-len(errors)-len(skipped),
                          'failures': failures, 'errors': errors, 'skipped': skipped,
                          'suites': [s.attrib for s in root.iter('testsuite')]}
(a.output / 'EXTRACTION_VERIFICATION.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2)+'\n')
print(json.dumps(summary, ensure_ascii=False, indent=2))
