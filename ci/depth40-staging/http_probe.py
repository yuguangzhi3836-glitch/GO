import json
import os
import time
from urllib.request import Request, build_opener, ProxyHandler
from urllib.error import HTTPError, URLError
client=build_opener(ProxyHandler({}))
checks=[]
def request(path,body=None):
    data=None if body is None else json.dumps(body).encode()
    r=client.open(Request('http://api:8000'+path,data=data,headers={'Content-Type':'application/json'}),timeout=8)
    return r.status,r.read()
for _ in range(70):
    try:
        if request('/health')[0]==200: break
    except (HTTPError,URLError,TimeoutError): pass
    time.sleep(1)
else: raise RuntimeError('API_START_TIMEOUT')
for path in ['/health','/go-app/','/supplier-console/','/go-admin/','/console-assets/api.js']:
    status,body=request(path)
    assert status==200 and len(body)>0, path
    checks.append({'path':path,'status':status})
for role in ('ADMIN','SUPPLIER'):
    status,body=request('/bff/auth/login',{'username':os.environ['BOOTSTRAP_'+role+'_USERNAME'],
        'password':os.environ['BOOTSTRAP_'+role+'_PASSWORD']})
    assert status==200
    checks.append({'check':role.lower()+'_http_login','status':status})
print(json.dumps({'status':'PASS','checks':checks,'browser_gate':'NOT_RUN'}))
