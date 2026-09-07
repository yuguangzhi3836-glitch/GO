#!/usr/bin/env python3
"""Seal only the measured hotel-catalog changes relative to exact DEPTH08."""
import argparse
import copy
import difflib
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

from assemble_depth08_candidate import sha, source_entries, tree_hash
from assemble_depth09_candidate import DEPTH08_SHA, DEPTH08_SOURCE

ROOT=Path(__file__).resolve().parents[1]
EVIDENCE=ROOT/'verification/current_build/depth09'


def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')


def measured(path):
    suites=list(ET.parse(path).getroot().iter('testsuite'))
    r={k:sum(int(s.get(k,0)) for s in suites) for k in ('tests','errors','failures','skipped')}
    r['passed']=r['tests']-r['errors']-r['failures']-r['skipped']
    r['seconds']=round(sum(float(s.get('time',0)) for s in suites),3)
    return r


def build(baseline):
    before_entries=source_entries(baseline)
    if tree_hash(before_entries)!=DEPTH08_SOURCE:raise ValueError('BASELINE_SOURCE_MISMATCH')
    totals=measured(EVIDENCE/'full_regression.xml')
    if totals['tests']<1069 or totals['failures'] or totals['errors']:raise ValueError('FULL_REGRESSION_NOT_PASSING')
    full=ET.parse(EVIDENCE/'full_regression.xml')
    cases=[copy.deepcopy(c) for c in full.getroot().iter('testcase') if 'test_depth09_hotel_replication' in c.get('classname','')]
    if len(cases)<43 or any(c.find('failure') is not None or c.find('error') is not None or c.find('skipped') is not None for c in cases):
        raise ValueError('DEPTH09_TARGETED_MATRIX_NOT_PASSING')
    subset=ET.Element('testsuites')
    s=ET.SubElement(subset,'testsuite',name='DEPTH09 unchanged subset of full_regression.xml',tests=str(len(cases)),errors='0',failures='0',skipped='0',time=str(sum(float(c.get('time',0)) for c in cases)))
    s.extend(cases);ET.ElementTree(subset).write(EVIDENCE/'targeted.xml',encoding='utf-8',xml_declaration=True)
    targeted=measured(EVIDENCE/'targeted.xml')
    before={x['path']:x['sha256'] for x in before_entries}
    current_entries=source_entries(ROOT)
    tested=json.loads((EVIDENCE/'tested_source.json').read_text())
    if tested['source_tree_sha256']!=tree_hash(current_entries):raise ValueError('SOURCE_CHANGED_AFTER_FINAL_REGRESSION_STARTED')
    current={x['path']:x['sha256'] for x in current_entries}
    if set(before)-set(current):raise ValueError('UNEXPECTED_SOURCE_REMOVAL')
    changes=[];patch=[]
    for name,digest in sorted(current.items()):
        if before.get(name)==digest:continue
        old=(baseline/name).read_bytes() if name in before else b''
        new=(ROOT/name).read_bytes()
        changes.append({'path':name,'status':'MODIFIED' if name in before else 'ADDED','before_sha256':before.get(name),'after_sha256':digest})
        patch.extend(difflib.unified_diff(old.decode().splitlines(True),new.decode().splitlines(True),fromfile='DEPTH08/'+name,tofile='DEPTH09/'+name))
    write(ROOT/'acceptance/DEPTH09_SOURCE_CHANGES.json',{'baseline_source_tree_sha256':DEPTH08_SOURCE,'changes':changes})
    (ROOT/'acceptance/DEPTH09_SOURCE_CHANGES.patch').write_text(''.join(patch))
    immutable={}
    for name,prefix in [('all_116_migrations','alembic/versions/'),('autonomy_kernel_and_governance','src/go_hotel/autonomy/'),('consumer_frontend','frontend/consumer/'),('official_aoluguya_facts','src/go_hotel/data/aoluguya/')]:
        files=[x for x in before_entries if x['path'].startswith(prefix)]
        immutable[name]={'count':len(files),'all_match':all(current.get(x['path'])==x['sha256'] for x in files),'files':files}
    master='GO_ULTIMATE_MASTER_PLAN_V7.0_2026-08-31_CONSTITUTIONAL_LEGAL_SYNC_MASTER.pdf'
    immutable['v7_master']={'count':1,'all_match':sha(ROOT/master)==sha(baseline/master),'sha256':sha(baseline/master)}
    if not all(x['all_match'] for x in immutable.values()):raise ValueError('IMMUTABLE_BASELINE_CHANGED')
    write(EVIDENCE/'immutable_baseline.json',immutable)
    source_sha=tree_hash(current_entries)
    status=json.loads((baseline/'verification/current_build/depth08/CURRENT_BUILD_STATUS.json').read_text())
    status.update(build='CP11_DEPTH_09_HOTEL_REPLICATION_CORRECTNESS',python=totals,new_targeted=targeted,
        source_tree_sha256=source_sha,FINAL_RELEASE_GATE='HOLD',HOTEL_REPLICATION_GATE='HOLD',engineering_complete=False,deployed=False,
        targeted_source='Unchanged test records extracted from this final full_regression.xml')
    status['baseline'].update(depth08_delta_sha256=DEPTH08_SHA,depth08_source_tree_sha256=DEPTH08_SOURCE,
        depth08_archive_commit='dffae0f5c3355e53c5f44c12aa3b8bb30b059179')
    status['hotel_replication']={'isolated_accuracy_gate':'PASS','live_multihotel_replication_gate':'NOT_ACCEPTED',
        'capture_adapter':'Explicit same-origin Hotel/HotelRoom JSON-LD relationships; unsupported structures remain incomplete',
        'source_inventory':'Declared entries captured != complete room-type inventory verified',
        'media':'Source-specific per-room photo parity and current file/hash/rights checks; no invented third photo',
        'publication':'Incomplete candidates stay draft; prior complete public version survives; manual unpublish persists',
        'identity':'No name-only merge; source identity serialized in SQLite tests; PostgreSQL transaction locks added but not run',
        'replication_fixture_properties':10,'live_properties_accepted':0,
        'remaining':['Screenshot OCR-to-verified-hotel intake','Site-specific adapters and full official room-index parity',
                     'Automatic capture-to-media cache orchestration and shared cache concurrency',
                     'Regional queue durable delivery/acknowledgement and killed-worker recovery',
                     'Real multi-hotel throughput and extraction accuracy','Public browser/mobile rendering and HK staging acceptance']}
    frontend=json.loads((EVIDENCE/'frontend_verification.json').read_text())
    if frontend['logic_failed'] or frontend['syntax_exit_code']:raise ValueError('FRONTEND_CHECK_FAILED')
    status['frontend'].update(node=frontend['node'],syntax_files_passed=len(frontend['syntax_files']),logic_passed=frontend['logic_passed'],
        browser_visual_accepted=False,frozen_node_22_22_certified=False,
        evidence_inherited_from='DEPTH09 node syntax check for changed admin file and 33 existing frontend logic tests; browser and Node 22.22 remain unaccepted')
    status['blocked_gates']=list(dict.fromkeys(status['blocked_gates']+['LIVE_MULTIHOTEL_REPLICATION','REGIONAL_BUILD_DURABLE_QUEUE','OFFICIAL_CAPTURE_TO_MEDIA_PIPELINE']))
    status['immutable_depth09']={k:{x:v for x,v in value.items() if x!='files'} for k,value in immutable.items()}
    write(EVIDENCE/'CURRENT_BUILD_STATUS.json',status)
    write(EVIDENCE/'SOURCE_TREE_MANIFEST.json',{'sha256':source_sha,'files':current_entries})
    write(ROOT/'CURRENT_DEPTH_CANDIDATE.json',{'build':status['build'],'FINAL_RELEASE_GATE':'HOLD','HOTEL_REPLICATION_GATE':'HOLD',
        'source_tree_sha256':source_sha,'deployed':False,'current_report':'verification/current_build/depth09/CURRENT_BUILD_STATUS.json',
        'start_here':'GO_DEPTH09_START_HERE.md','older_release_documents':'Historical milestones, not current release acceptance'})
    register=json.loads((baseline/'acceptance/MASTER_CLOSURE_REGISTER.json').read_text())
    register['current_build_report']='verification/current_build/depth09/CURRENT_BUILD_STATUS.json'
    for requirement in register['requirements']:
        if requirement['id']=='HOTEL-01':
            requirement.update(fully_accepted=False,status='OFFICIAL_CATALOG_IDENTITY_AND_PUBLICATION_CORRECTNESS_TESTED',
                current_evidence=['verification/current_build/depth09/targeted.xml'],
                scope_note='10 synthetic hotels replicated and replayed; explicit official catalog and media gates. Live multi-hotel capture, screenshot intake and complete hotel build orchestration remain unaccepted.')
    write(ROOT/'acceptance/MASTER_CLOSURE_REGISTER.json',register)
    paths={c['path'] for c in changes}|{'CURRENT_DEPTH_CANDIDATE.json','GO_DEPTH09_START_HERE.md','acceptance/GO_DEPTH09_REVIEW.md',
        'acceptance/DEPTH09_SOURCE_CHANGES.json','acceptance/DEPTH09_SOURCE_CHANGES.patch','acceptance/MASTER_CLOSURE_REGISTER.json'}
    paths|={p.relative_to(ROOT).as_posix() for p in EVIDENCE.iterdir() if p.suffix in {'.json','.xml','.log'}}
    m={'build':status['build'],'FINAL_RELEASE_GATE':'HOLD','HOTEL_REPLICATION_GATE':'HOLD','depth08_delta_sha256':DEPTH08_SHA,
       'baseline_source_tree_sha256':DEPTH08_SOURCE,'source_tree_sha256':source_sha,'files':[]}
    for name in sorted(paths):
        p=ROOT/name
        m['files'].append({'path':name,'size':p.stat().st_size,'sha256':sha(p),
            'before_sha256':sha(baseline/name) if (baseline/name).is_file() else None,'mode':0o755 if p.stat().st_mode&0o111 else 0o644})
    output=ROOT/'deliverables';output.mkdir(exist_ok=True)
    archive=output/'GO_CP11_DEPTH_09_HOTEL_REPLICATION_DELTA_20260907.zip'
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        z.writestr('DEPTH09_DELTA_MANIFEST.json',json.dumps(m,indent=2))
        for f in m['files']:z.write(ROOT/f['path'],'payload/'+f['path'])
    with zipfile.ZipFile(archive) as z:
        preflight_error=z.testzip()
        if preflight_error:raise ValueError('ZIP_CRC_FAILURE')
    receipt={'filename':archive.name,'size_bytes':archive.stat().st_size,'sha256':sha(archive),'source_tree_sha256':source_sha,
             'changed_source_files':len(changes),'payload_files':len(m['files']),'python':totals,'new_targeted':targeted,
             'FINAL_RELEASE_GATE':'HOLD','HOTEL_REPLICATION_GATE':'HOLD'}
    write(output/'GO_DEPTH09_BUILD_RECEIPT.json',receipt)
    (output/(archive.name+'.sha256')).write_text(receipt['sha256']+'  '+archive.name+'\n')
    print(json.dumps(receipt,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline',type=Path,required=True)
    build(parser.parse_args().baseline.resolve())
