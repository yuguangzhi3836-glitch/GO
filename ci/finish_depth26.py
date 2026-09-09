import base64,hashlib,json,os
from pathlib import Path
import xml.etree.ElementTree as ET
root=Path('evidence');checks={}
for name,expected in [('attraction_postgres.xml',8),('control_bridge.xml',24)]:
    p=root/name
    if not p.is_file():checks[name]={'passed':False,'reason':'MISSING'};continue
    data=p.read_bytes();cases=list(ET.fromstring(data).iter('testcase'))
    bad=[c.get('name') for c in cases if any(c.find(t) is not None for t in ('failure','error','skipped'))]
    checks[name]={'passed':len(cases)==expected and not bad,'tests':len(cases),'bad':bad,'sha256':hashlib.sha256(data).hexdigest()}
    print('GO_DEPTH26_XML '+name+' '+base64.b64encode(data).decode())
gate={'build':'DEPTH26','runtime_gate':'PASS' if os.environ.get('PRIOR_STEPS_STATUS')=='success' and all(c['passed'] for c in checks.values()) else 'HOLD',
      'checks':checks,'postgres':'disposable PostgreSQL 16.4','control_transport':'isolated TestClient, not HK HTTPS',
      'FINAL_RELEASE_GATE':'HOLD','hk_connected':False,'commit':os.environ.get('GITHUB_SHA')}
(root/'DEPTH26_RUNTIME_GATE.json').write_text(json.dumps(gate,indent=2)+'\n')
print('GO_DEPTH26_GATE '+json.dumps(gate))
