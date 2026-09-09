"""Recover byte-exact public test records exported by the isolated job to its log."""
import base64,hashlib,json,re,xml.etree.ElementTree as ET
from pathlib import Path
p=Path(__file__).resolve().parent
log=(p/'workflow_job.log').read_text(encoding='utf-8')
current=None;chunks=[];outputs=[]
for raw in log.splitlines():
    line=re.sub(r'^\ufeff?\d{4}-\d\d-\d\dT\S+Z ','',raw)
    match=re.fullmatch(r'GO_EVIDENCE_FILE_BEGIN ([\w.-]+) (\d+) ([a-f0-9]{64})',line)
    if match:
        assert current is None
        current=(match[1],int(match[2]),match[3]);chunks=[]
    elif line.startswith('GO_EVIDENCE_B64 '):
        assert current is not None
        chunks.append(line.split(' ',1)[1])
    elif line.startswith('GO_EVIDENCE_FILE_END '):
        assert current and current[0]==line.split(' ',1)[1]
        name,size,expected=current
        assert name in {'source-lineage.json','backend.xml','frontend.xml'}
        data=base64.b64decode(''.join(chunks),validate=True)
        assert len(data)==size and hashlib.sha256(data).hexdigest()==expected
        (p/name).write_bytes(data);outputs.append({'path':name,'bytes':size,'sha256':expected})
        current=None
assert current is None and len(outputs)==3
lineage=json.loads((p/'source-lineage.json').read_text())
assert lineage['candidate']=='c495ca6547a667b9a4eb94a02e296231f9b88e79'
assert lineage['source_tree_sha256']=='f576c976bfe8f34d3182ba232fe1290c374346106c602a4fffe4935366f7a961'
assert lineage['node']=='v22.22.0' and lineage['verified_files']==1222
counts={}
for name,expected in [('backend',172),('frontend',194)]:
    xml=ET.parse(p/(name+'.xml')).getroot()
    counts[name]={'tests':len(xml.findall('.//testcase')),'failures':len(xml.findall('.//failure')),'errors':len(xml.findall('.//error')),'skipped':len(xml.findall('.//skipped'))}
    assert counts[name]=={'tests':expected,'failures':0,'errors':0,'skipped':0}
result={'run_id':34372130831,'job_id':102535715178,'lineage':lineage,'counts':counts,'exported_files':outputs,'raw_job_log_sha256':hashlib.sha256((p/'workflow_job.log').read_bytes()).hexdigest(),
 'raw_test_records_inspected':True,'source_verified_after_tests':'SOURCE_VERIFIED_AFTER_TESTS 1222' in log,
 'artifact_zip_downloaded':False,'artifact_zip_independently_verified':False,
 'scope':'Independent disposable GitHub runner; backend SQLite TestClient, native domain functions via offline stdio API bridge, frontend VM/pure-function tests. Not native build, actual device or real browser E2E.',
 'predeployment_complete':False,'release_approved':False,'deployed':False,'gates':{g:'HOLD' for g in ['THREE_END_REAL_UX_LOGIN','SIX_VERTICAL_REAL_E2E','SEALED_NODE_GATE','FINAL_RELEASE']}}
(p/'INDEPENDENT_REVIEW.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(result,ensure_ascii=False))
